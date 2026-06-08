#!/usr/bin/env python3
"""Convert a ComfyUI workflow graph into an API-friendly prompt."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


UI_ONLY_TYPES = {"Note", "MarkdownNote", "Fast Groups Bypasser (rgthree)"}
DEFAULT_MAIN_OUTPUT_ID = "312"
BODY_RATIO_MAPPER_WIDGET_INPUTS = [
    "enable_rpca",
    "hand_scaling",
    "foot_scaling",
    "offset_stabilizer_y",
    "offset_stabilizer_x",
    "best_hand_search",
    "use_shoulder_fk_for_hand",
    "use_torso_fk_for_arm",
    "use_torso_fk_for_foot",
    "best_neck_search",
    "final_offset_alignment",
    "base_offset_mode",
    "head_fixed_mode",
    "anchor_output_mode",
    "print_detailed_logs",
    "confidence_threshold",
    "output_absolute_coordinates",
]
COMPATIBLE_CUSTOM_NODE_REPLACEMENTS = {
    "ImageCompositeMaskedWithSwitch": {
        "replacement": "ImageCompositeMasked",
        "drop_inputs": {"enabled", "invert_mask"},
        "source": "comfyui-utils-nodes",
    }
}


class Workflow:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.nodes: list[dict[str, Any]] = data.get("nodes", [])
        self.links: list[list[Any]] = data.get("links", [])

    @property
    def node_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(node["id"]): node for node in self.nodes}

    @property
    def link_by_id(self) -> dict[str, list[Any]]:
        return {str(link[0]): link for link in self.links}

    def next_node_id(self) -> int:
        max_id = max([int(n["id"]) for n in self.nodes] + [int(self.data.get("last_node_id", 0))])
        return max_id + 1

    def next_link_id(self) -> int:
        max_id = max([int(l[0]) for l in self.links] + [int(self.data.get("last_link_id", 0))])
        return max_id + 1

    def add_link(self, link_id: int, src_id: int | str, src_slot: int, dst_id: int | str, dst_slot: int, link_type: Any) -> None:
        self.links.append([link_id, int(src_id), src_slot, int(dst_id), dst_slot, link_type])
        self.data["links"] = self.links

    def rebuild_link_refs(self) -> None:
        node_by_id = self.node_by_id
        for node in self.nodes:
            for input_slot in node.get("inputs", []) or []:
                input_slot["link"] = None
            for output_slot in node.get("outputs", []) or []:
                output_slot["links"] = None

        for link in self.links:
            src = node_by_id.get(str(link[1]))
            dst = node_by_id.get(str(link[3]))
            if not src or not dst:
                continue
            if link[2] < len(src.get("outputs", []) or []):
                out = src["outputs"][link[2]]
                if not isinstance(out.get("links"), list):
                    out["links"] = []
                out["links"].append(link[0])
            if link[4] < len(dst.get("inputs", []) or []):
                dst["inputs"][link[4]]["link"] = link[0]

    def remove_links(self, link_ids: set[str]) -> None:
        self.links = [link for link in self.links if str(link[0]) not in link_ids]
        self.data["links"] = self.links
        self.rebuild_link_refs()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def node_name(node: dict[str, Any]) -> str:
    values = node.get("widgets_values")
    if isinstance(values, list) and values:
        return str(values[0])
    return ""


def normalize_legacy_widgets(workflow: Workflow) -> dict[str, Any]:
    """Repair widget lists saved by older custom-node versions."""
    changes: list[dict[str, Any]] = []
    anchor_modes = {"single_frame_multi_person", "multi_frame_single_person"}

    for node in workflow.nodes:
        values = node.get("widgets_values")
        if node.get("type") != "BodyRatioMapperProportionTransfer" or not isinstance(values, list):
            continue

        # Older BodyRatioMapper workflows can contain a stale boolean just before
        # anchor_output_mode and no trailing output_absolute_coordinates value.
        if (
            len(values) == 17
            and isinstance(values[13], bool)
            and values[14] in anchor_modes
            and isinstance(values[15], bool)
            and isinstance(values[16], (int, float))
        ):
            old_values = list(values)
            node["widgets_values"] = values[:13] + [values[14], values[15], values[16], True]
            changes.append(
                {
                    "node_id": str(node["id"]),
                    "type": node["type"],
                    "repair": "removed stale pre-anchor boolean and appended output_absolute_coordinates=True",
                    "before": old_values,
                    "after": node["widgets_values"],
                }
            )

    return {"changes": changes}


def is_visual_reroute(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type") or "")
    title = str(node.get("title") or "")
    return "reroute" in f"{node_type} {title}".lower()


def first_input_link(workflow: Workflow, node: dict[str, Any]) -> list[Any] | None:
    links = workflow.link_by_id
    for input_slot in node.get("inputs", []) or []:
        link = links.get(str(input_slot.get("link")))
        if link:
            return link
    return None


def resolve_reroute_source(workflow: Workflow, node_id: str, seen: set[str] | None = None) -> list[Any] | None:
    if seen is None:
        seen = set()
    if node_id in seen:
        return None
    seen.add(node_id)

    node = workflow.node_by_id.get(str(node_id))
    if not node or not is_visual_reroute(node):
        return None

    upstream = first_input_link(workflow, node)
    if not upstream:
        return None

    upstream_node = workflow.node_by_id.get(str(upstream[1]))
    if upstream_node and is_visual_reroute(upstream_node):
        return resolve_reroute_source(workflow, str(upstream[1]), seen)
    return upstream


def strip_reroute_nodes(workflow: Workflow) -> dict[str, Any]:
    """Remove visual reroute nodes and reconnect consumers to the real source."""
    reroute_ids = {str(node["id"]) for node in workflow.nodes if is_visual_reroute(node)}
    if not reroute_ids:
        return {"removed": 0, "rewired": [], "unresolved": []}

    rewired: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for link in workflow.links:
        source_id = str(link[1])
        if source_id not in reroute_ids:
            continue
        upstream = resolve_reroute_source(workflow, source_id)
        if not upstream:
            unresolved.append({"link_id": str(link[0]), "reroute_id": source_id})
            continue
        old_source = [link[1], link[2]]
        link[1] = upstream[1]
        link[2] = upstream[2]
        if not link[5] and len(upstream) > 5:
            link[5] = upstream[5]
        rewired.append(
            {
                "link_id": str(link[0]),
                "from": old_source,
                "to": [link[1], link[2]],
            }
        )

    workflow.links = [
        link
        for link in workflow.links
        if str(link[1]) not in reroute_ids and str(link[3]) not in reroute_ids
    ]
    workflow.nodes = [node for node in workflow.nodes if str(node["id"]) not in reroute_ids]
    workflow.data["nodes"] = workflow.nodes
    workflow.data["links"] = workflow.links
    workflow.rebuild_link_refs()
    return {"removed": len(reroute_ids), "rewired": rewired, "unresolved": unresolved}


def replace_compatible_custom_nodes(workflow: Workflow) -> dict[str, Any]:
    """Swap known compatibility wrapper nodes for ComfyUI core node types."""
    converted: list[dict[str, Any]] = []
    removed_link_ids: set[str] = set()

    for node in workflow.nodes:
        node_type = node.get("type")
        replacement = COMPATIBLE_CUSTOM_NODE_REPLACEMENTS.get(str(node_type))
        if not replacement:
            continue

        drop_inputs = set(replacement.get("drop_inputs", set()))
        removed_inputs: list[str] = []
        kept_inputs = []
        for input_slot in node.get("inputs", []) or []:
            input_name = input_slot.get("name")
            if input_name in drop_inputs:
                removed_inputs.append(str(input_name))
                if input_slot.get("link") is not None:
                    removed_link_ids.add(str(input_slot["link"]))
                continue
            kept_inputs.append(input_slot)

        new_type = str(replacement["replacement"])
        node["inputs"] = kept_inputs
        node["type"] = new_type
        if node.get("title") == node_type:
            node["title"] = new_type
        properties = node.setdefault("properties", {})
        if isinstance(properties, dict):
            properties["Node name for S&R"] = new_type
            if properties.get("cnr_id") == replacement.get("source"):
                properties["cnr_id"] = "comfy-core"
                properties.pop("ver", None)

        converted.append(
            {
                "node_id": str(node["id"]),
                "from": str(node_type),
                "to": new_type,
                "removed_inputs": removed_inputs,
            }
        )

    if removed_link_ids:
        workflow.remove_links(removed_link_ids)
    elif converted:
        workflow.rebuild_link_refs()
    return {"converted": converted}


def flatten_set_get(workflow: Workflow) -> dict[str, Any]:
    nodes = workflow.nodes
    links_by_id = workflow.link_by_id
    set_nodes = [node for node in nodes if node.get("type") == "SetNode"]
    get_nodes = [node for node in nodes if node.get("type") == "GetNode"]
    if not set_nodes and not get_nodes:
        return {"converted": [], "skipped": []}

    set_by_name: dict[str, list[dict[str, Any]]] = {}
    for node in set_nodes:
        name = node_name(node)
        if name:
            set_by_name.setdefault(name, []).append(node)

    removed_node_ids = {str(node["id"]) for node in set_nodes + get_nodes}
    removed_link_ids: set[str] = set()
    added_links: list[list[Any]] = []
    next_link = workflow.next_link_id()
    converted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def output_consumers(node: dict[str, Any]) -> list[dict[str, Any]]:
        consumers = []
        outputs = node.get("outputs", []) or []
        if not outputs:
            return consumers
        for link_id in outputs[0].get("links") or []:
            link = links_by_id.get(str(link_id))
            if link:
                consumers.append({"target_id": link[3], "target_slot": link[4], "type": link[5]})
                removed_link_ids.add(str(link[0]))
        return consumers

    for name, setters in set_by_name.items():
        if len(setters) != 1:
            skipped.append({"name": name, "reason": f"expected 1 SetNode, found {len(setters)}"})
            continue
        setter = setters[0]
        source_link_id = (setter.get("inputs") or [{}])[0].get("link")
        source_link = links_by_id.get(str(source_link_id))
        if not source_link:
            skipped.append({"name": name, "set_id": setter["id"], "reason": "SetNode input is not linked"})
            continue
        removed_link_ids.add(str(source_link[0]))

        matching_getters = [getter for getter in get_nodes if node_name(getter) == name]
        consumers = []
        for getter in matching_getters:
            consumers.extend(output_consumers(getter))
        consumers.extend(output_consumers(setter))

        for consumer in consumers:
            added_links.append(
                [next_link, source_link[1], source_link[2], consumer["target_id"], consumer["target_slot"], consumer["type"] or source_link[5]]
            )
            next_link += 1

        converted.append(
            {
                "name": name,
                "set_id": setter["id"],
                "getter_ids": [getter["id"] for getter in matching_getters],
                "consumers": len(consumers),
            }
        )

    workflow.links = [
        link
        for link in workflow.links
        if str(link[0]) not in removed_link_ids
        and str(link[1]) not in removed_node_ids
        and str(link[3]) not in removed_node_ids
    ]
    workflow.links.extend(added_links)
    workflow.nodes = [node for node in workflow.nodes if str(node["id"]) not in removed_node_ids]
    workflow.data["nodes"] = workflow.nodes
    workflow.data["links"] = workflow.links
    workflow.data["last_link_id"] = max(int(workflow.data.get("last_link_id", 0)), next_link - 1)
    workflow.rebuild_link_refs()
    return {"converted": converted, "skipped": skipped}


def make_primitive_boolean(node_id: int, title: str, default: bool, pos: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "PrimitiveBoolean",
        "pos": pos or [0, 0],
        "size": [210, 58],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "value", "type": "BOOLEAN", "widget": {"name": "value"}, "link": None}],
        "outputs": [{"name": "BOOLEAN", "type": "BOOLEAN", "links": None}],
        "title": title,
        "properties": {"Node name for S&R": "PrimitiveBoolean"},
        "widgets_values": [default],
    }


def make_lazy_optional(node_id: int, title: str, pos: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "APILazyOptional",
        "pos": pos or [0, 0],
        "size": [240, 80],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [
            {"name": "enabled", "type": "BOOLEAN", "link": None},
            {"name": "value", "type": "*", "link": None},
        ],
        "outputs": [{"name": "value", "type": "*", "links": None}],
        "title": title,
        "properties": {"Node name for S&R": "APILazyOptional"},
        "widgets_values": [],
    }


def make_lazy_switch(node_id: int, title: str, pos: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "APILazySwitch",
        "pos": pos or [0, 0],
        "size": [260, 110],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [
            {"name": "cond", "type": "BOOLEAN", "link": None},
            {"name": "on_false", "type": "*", "link": None},
            {"name": "on_true", "type": "*", "link": None},
        ],
        "outputs": [{"name": "value", "type": "*", "links": None}],
        "title": title,
        "properties": {"Node name for S&R": "APILazySwitch"},
        "widgets_values": [],
    }


def make_conditioning_zero_out(node_id: int, title: str, pos: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "ConditioningZeroOut",
        "pos": pos or [0, 0],
        "size": [225, 48],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [{"name": "conditioning", "type": "CONDITIONING", "link": None}],
        "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": None}],
        "title": title,
        "properties": {"Node name for S&R": "ConditioningZeroOut"},
        "widgets_values": [],
    }


def make_boolean_and(node_id: int, title: str, pos: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "APIBooleanAnd",
        "pos": pos or [0, 0],
        "size": [240, 80],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [
            {"name": "a", "type": "BOOLEAN", "widget": {"name": "a"}, "link": None},
            {"name": "b", "type": "BOOLEAN", "widget": {"name": "b"}, "link": None},
        ],
        "outputs": [{"name": "value", "type": "BOOLEAN", "links": None}],
        "title": title,
        "properties": {"Node name for S&R": "APIBooleanAnd"},
        "widgets_values": [True, True],
    }


def find_input_index(node: dict[str, Any], name: str) -> int | None:
    for index, input_slot in enumerate(node.get("inputs", []) or []):
        if input_slot.get("name") == name:
            return index
    return None


def set_node_mode(workflow: Workflow, node_ids: list[int], mode: int) -> None:
    nodes = workflow.node_by_id
    for node_id in node_ids:
        node = nodes.get(str(node_id))
        if node:
            node["mode"] = mode


def insert_optional_gate(
    workflow: Workflow,
    switch_name: str,
    target_id: int,
    target_input_name: str,
    default: bool,
    mapping: dict[str, Any],
    existing_bool_node_id: int | None = None,
) -> dict[str, Any] | None:
    nodes = workflow.node_by_id
    links = workflow.link_by_id
    target = nodes.get(str(target_id))
    if not target:
        return None
    input_index = find_input_index(target, target_input_name)
    if input_index is None:
        return None
    input_slot = target["inputs"][input_index]
    old_link = links.get(str(input_slot.get("link")))
    if not old_link:
        return None

    next_node = workflow.next_node_id()
    next_link = workflow.next_link_id()
    if existing_bool_node_id is None:
        bool_node_id = next_node
        next_node += 1
        bool_node = make_primitive_boolean(bool_node_id, f"Input_{switch_name}", default, [target.get("pos", [0, 0])[0] - 520, target.get("pos", [0, 0])[1]])
        workflow.nodes.append(bool_node)
    else:
        bool_node_id = existing_bool_node_id

    lazy_node_id = next_node
    lazy_node = make_lazy_optional(lazy_node_id, f"API_{switch_name}_optional", [target.get("pos", [0, 0])[0] - 260, target.get("pos", [0, 0])[1]])
    workflow.nodes.append(lazy_node)

    workflow.remove_links({str(old_link[0])})
    workflow.add_link(next_link, bool_node_id, 0, lazy_node_id, 0, "BOOLEAN")
    next_link += 1
    workflow.add_link(next_link, old_link[1], old_link[2], lazy_node_id, 1, old_link[5])
    next_link += 1
    workflow.add_link(next_link, lazy_node_id, 0, target_id, input_index, old_link[5])
    workflow.data["last_node_id"] = max(int(workflow.data.get("last_node_id", 0)), lazy_node_id)
    workflow.data["last_link_id"] = max(int(workflow.data.get("last_link_id", 0)), next_link - 1)
    workflow.rebuild_link_refs()

    entry = {
        "enabled_node_id": str(bool_node_id),
        "enabled_input": "value",
        "lazy_node_id": str(lazy_node_id),
        "target_node_id": str(target_id),
        "target_input": target_input_name,
        "default": default,
    }
    mapping.setdefault("runtime_switches", {})[switch_name] = entry
    return entry


def nodes_in_group(workflow: Workflow, group: dict[str, Any]) -> list[dict[str, Any]]:
    bounding = group.get("bounding")
    if not isinstance(bounding, list) or len(bounding) != 4:
        return []
    x, y, width, height = bounding
    result = []
    for node in workflow.nodes:
        pos = node.get("pos")
        if isinstance(pos, list) and len(pos) >= 2 and x <= pos[0] <= x + width and y <= pos[1] <= y + height:
            result.append(node)
    return result


def add_lazy_switch_for_link(
    workflow: Workflow,
    bool_node_id: int | str,
    false_source: list[Any],
    true_link: list[Any],
    title: str,
    pos: list[float] | None = None,
) -> dict[str, Any]:
    switch_id = workflow.next_node_id()
    next_link = workflow.next_link_id()
    switch_node = make_lazy_switch(switch_id, title, pos)
    workflow.nodes.append(switch_node)
    workflow.data["nodes"] = workflow.nodes

    workflow.remove_links({str(true_link[0])})
    workflow.add_link(next_link, bool_node_id, 0, switch_id, 0, "BOOLEAN")
    next_link += 1
    workflow.add_link(next_link, false_source[0], false_source[1], switch_id, 1, false_source[2])
    next_link += 1
    workflow.add_link(next_link, true_link[1], true_link[2], switch_id, 2, true_link[5])
    next_link += 1
    workflow.add_link(next_link, switch_id, 0, true_link[3], true_link[4], true_link[5])
    workflow.data["last_node_id"] = max(int(workflow.data.get("last_node_id", 0)), switch_id)
    workflow.data["last_link_id"] = max(int(workflow.data.get("last_link_id", 0)), next_link)
    workflow.rebuild_link_refs()
    return {
        "switch_node_id": str(switch_id),
        "target_node_id": str(true_link[3]),
        "target_input_slot": true_link[4],
        "replaced_link_id": str(true_link[0]),
    }


def add_conditioning_zero_from_source(workflow: Workflow, source: list[Any], title: str, pos: list[float] | None = None) -> dict[str, Any]:
    zero_id = workflow.next_node_id()
    next_link = workflow.next_link_id()
    zero_node = make_conditioning_zero_out(zero_id, title, pos)
    workflow.nodes.append(zero_node)
    workflow.data["nodes"] = workflow.nodes
    workflow.add_link(next_link, source[0], source[1], zero_id, 0, source[2])
    workflow.data["last_node_id"] = max(int(workflow.data.get("last_node_id", 0)), zero_id)
    workflow.data["last_link_id"] = max(int(workflow.data.get("last_link_id", 0)), next_link)
    workflow.rebuild_link_refs()
    return {"zero_node_id": str(zero_id), "source": source}


def add_boolean_and(workflow: Workflow, bool_a_id: int | str, bool_b_id: int | str, title: str, pos: list[float] | None = None) -> dict[str, Any]:
    and_id = workflow.next_node_id()
    next_link = workflow.next_link_id()
    and_node = make_boolean_and(and_id, title, pos)
    workflow.nodes.append(and_node)
    workflow.data["nodes"] = workflow.nodes
    workflow.add_link(next_link, bool_a_id, 0, and_id, 0, "BOOLEAN")
    next_link += 1
    workflow.add_link(next_link, bool_b_id, 0, and_id, 1, "BOOLEAN")
    workflow.data["last_node_id"] = max(int(workflow.data.get("last_node_id", 0)), and_id)
    workflow.data["last_link_id"] = max(int(workflow.data.get("last_link_id", 0)), next_link)
    workflow.rebuild_link_refs()
    return {"and_node_id": str(and_id), "input_a_node_id": str(bool_a_id), "input_b_node_id": str(bool_b_id)}


def describe1_group_switch_name(group_title: str) -> str:
    if "Pose / Depth" in group_title or "姿势/深度" in group_title:
        return "enable_describe1_pose_depth"
    return "enable_describe1"


def convert_oct_posture_bypasser(workflow: Workflow) -> dict[str, Any]:
    """Convert OCTInput rgthree group bypasser into lazy API switches."""
    converted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    groups = workflow.data.get("groups", []) or []

    for bypasser in list(workflow.nodes):
        if bypasser.get("type") != "Fast Groups Bypasser (rgthree)":
            continue
        title = bypasser.get("title") or ""
        match_title = (bypasser.get("properties") or {}).get("matchTitle") or ""
        if not title.startswith("OCTInput_Posture control switch") and match_title != "Describe1":
            continue

        matched_groups = [group for group in groups if match_title and match_title in (group.get("title") or "")]
        if not matched_groups:
            skipped.append({"node_id": str(bypasser["id"]), "reason": "no matching groups", "match_title": match_title})
            continue

        group_nodes_by_title: dict[str, list[dict[str, Any]]] = {}
        group_nodes: list[dict[str, Any]] = []
        for group in matched_groups:
            group_title = group.get("title") or ""
            current_group_nodes = nodes_in_group(workflow, group)
            group_nodes_by_title[group_title] = current_group_nodes
            group_nodes.extend(current_group_nodes)
        apply_nodes = [node for node in group_nodes if node.get("type") == "ControlNetApplySD3"]
        if not apply_nodes:
            skipped.append({"node_id": str(bypasser["id"]), "reason": "no ControlNetApplySD3 node in matching groups"})
            continue

        group_switches: list[dict[str, Any]] = []
        switch_ids: dict[str, int] = {}
        for index, (group_title, current_group_nodes) in enumerate(group_nodes_by_title.items()):
            switch_name = describe1_group_switch_name(group_title)
            default = any(node.get("mode", 0) != 4 and node.get("type") not in UI_ONLY_TYPES for node in current_group_nodes)
            bool_id = workflow.next_node_id()
            bool_node = make_primitive_boolean(
                bool_id,
                f"Input_{switch_name}",
                default,
                [bypasser.get("pos", [0, 0])[0], bypasser.get("pos", [0, 0])[1] + 150 + index * 80],
            )
            workflow.nodes.append(bool_node)
            workflow.data["nodes"] = workflow.nodes
            workflow.data["last_node_id"] = max(int(workflow.data.get("last_node_id", 0)), bool_id)
            workflow.rebuild_link_refs()
            switch_ids[switch_name] = bool_id
            group_switches.append(
                {
                    "name": switch_name,
                    "enabled_node_id": str(bool_id),
                    "enabled_input": "value",
                    "default": default,
                    "group": group_title,
                }
            )

        for node in group_nodes:
            if node.get("type") not in UI_ONLY_TYPES:
                node["mode"] = 0

        describe_id = switch_ids.get("enable_describe1")
        pose_depth_id = switch_ids.get("enable_describe1_pose_depth")
        condition_report: dict[str, Any] | None = None
        if describe_id and pose_depth_id:
            condition_report = add_boolean_and(
                workflow,
                describe_id,
                pose_depth_id,
                "API_enable_describe1_and_pose_depth",
                [bypasser.get("pos", [0, 0])[0] + 280, bypasser.get("pos", [0, 0])[1] + 150],
            )
            condition_node_id: int | str = int(condition_report["and_node_id"])
        else:
            condition_node_id = describe_id or pose_depth_id

        if condition_node_id is None:
            skipped.append({"node_id": str(bypasser["id"]), "reason": "no API switch nodes created"})
            continue

        apply_reports = []
        for apply_node in apply_nodes:
            links = workflow.link_by_id
            positive_link = links.get(str((apply_node.get("inputs") or [{}])[0].get("link")))
            negative_link = links.get(str((apply_node.get("inputs") or [{}, {}])[1].get("link")))
            if not positive_link:
                skipped.append({"node_id": str(apply_node["id"]), "reason": "ControlNetApplySD3 positive input is not linked"})
                continue
            positive_source = [positive_link[1], positive_link[2], positive_link[5]]
            negative_source = [negative_link[1], negative_link[2], negative_link[5]] if negative_link else positive_source

            output_reports = []
            output_links = list((apply_node.get("outputs") or [{}, {}])[0].get("links") or [])
            for link_id in output_links:
                true_link = workflow.link_by_id.get(str(link_id))
                if true_link:
                    output_reports.append(
                        add_lazy_switch_for_link(
                            workflow,
                            condition_node_id,
                            positive_source,
                            true_link,
                            "API_enable_describe1_positive",
                            [apply_node.get("pos", [0, 0])[0] + 360, apply_node.get("pos", [0, 0])[1]],
                        )
                    )

            negative_reports = []
            negative_output_links = list((apply_node.get("outputs") or [{}, {}])[1].get("links") or [])
            for link_id in negative_output_links:
                neg_link = workflow.link_by_id.get(str(link_id))
                neg_target = workflow.node_by_id.get(str(neg_link[3])) if neg_link else None
                if not neg_link or not neg_target or neg_target.get("type") != "ConditioningZeroOut":
                    continue
                false_zero = add_conditioning_zero_from_source(
                    workflow,
                    negative_source,
                    "API_enable_describe1_false_negative",
                    [neg_target.get("pos", [0, 0])[0], neg_target.get("pos", [0, 0])[1] + 90],
                )
                zero_output_links = list((neg_target.get("outputs") or [{}])[0].get("links") or [])
                for zero_link_id in zero_output_links:
                    true_zero_link = workflow.link_by_id.get(str(zero_link_id))
                    if true_zero_link:
                        report = add_lazy_switch_for_link(
                            workflow,
                            condition_node_id,
                            [int(false_zero["zero_node_id"]), 0, true_zero_link[5]],
                            true_zero_link,
                            "API_enable_describe1_negative",
                            [neg_target.get("pos", [0, 0])[0] + 300, neg_target.get("pos", [0, 0])[1]],
                        )
                        report["false_zero_node_id"] = false_zero["zero_node_id"]
                        negative_reports.append(report)

            apply_reports.append(
                {
                    "controlnet_apply_node_id": str(apply_node["id"]),
                    "positive_switches": output_reports,
                    "negative_switches": negative_reports,
                }
            )

        converted.append(
            {
                "frontend_node_id": str(bypasser["id"]),
                "frontend_title": title,
                "match_title": match_title,
                "switches": group_switches,
                "condition": condition_report
                or {
                    "condition_node_id": str(condition_node_id),
                    "single_switch": True,
                },
                "groups": [group.get("title") for group in matched_groups],
                "apply_nodes": apply_reports,
            }
        )

    return {"converted": converted, "skipped": skipped}


def apply_motiontransfer_profile(workflow: Workflow) -> dict[str, Any]:
    mapping: dict[str, Any] = {"profile": "motiontransfer", "runtime_switches": {}}

    # Uni3C was a bypassed optional branch in the canvas workflow.
    set_node_mode(workflow, [537, 538, 546, 547], 0)
    insert_optional_gate(workflow, "enable_uni3c", 530, "uni3c_embeds", False, mapping)

    insert_optional_gate(workflow, "enable_face", 904, "face_images", True, mapping)

    first_multi = insert_optional_gate(workflow, "enable_multi_person", 1068, "bboxes", True, mapping)
    if first_multi:
        insert_optional_gate(
            workflow,
            "enable_multi_person_video",
            1069,
            "bboxes",
            True,
            mapping,
            existing_bool_node_id=int(first_multi["enabled_node_id"]),
        )
        # Keep one public switch name while reporting both lazy gates.
        extra = mapping["runtime_switches"].pop("enable_multi_person_video", None)
        if extra:
            mapping["runtime_switches"]["enable_multi_person"]["extra_gates"] = [extra]

    if "1097" in workflow.node_by_id:
        mapping["runtime_switches"]["enable_pose_align"] = {
            "enabled_node_id": "1097",
            "enabled_input": "value",
            "default": workflow.node_by_id["1097"].get("widgets_values", [False])[0],
            "reused_existing_node": True,
        }

    return mapping


def include_node(node: dict[str, Any]) -> bool:
    if node.get("type") in UI_ONLY_TYPES:
        return False
    if node.get("mode", 0) == 4:
        return False
    return True


def reachable_nodes(workflow: Workflow, output_id: str) -> set[str]:
    nodes = workflow.node_by_id
    links = workflow.link_by_id
    seen: set[str] = set()

    def visit(node_id: str) -> None:
        node = nodes.get(str(node_id))
        if not node or str(node_id) in seen or not include_node(node):
            return
        seen.add(str(node_id))
        for input_slot in node.get("inputs", []) or []:
            link = links.get(str(input_slot.get("link")))
            if link:
                visit(str(link[1]))

    visit(str(output_id))
    return seen


def all_executable_nodes(workflow: Workflow) -> set[str]:
    return {str(node["id"]) for node in workflow.nodes if include_node(node)}


def prune_workflow(workflow: Workflow, keep_ids: set[str]) -> dict[str, Any]:
    pruned = copy.deepcopy(workflow.data)
    pruned_nodes = [node for node in pruned.get("nodes", []) if str(node["id"]) in keep_ids]
    pruned_links = [
        link
        for link in pruned.get("links", [])
        if str(link[1]) in keep_ids and str(link[3]) in keep_ids
    ]
    pruned["nodes"] = pruned_nodes
    pruned["links"] = pruned_links
    pruned_wf = Workflow(pruned)
    pruned_wf.rebuild_link_refs()
    return pruned


def widget_value(node: dict[str, Any], widget_index: int, input_name: str) -> Any:
    values = node.get("widgets_values", [])
    if isinstance(values, dict):
        return values.get(input_name)
    if isinstance(values, list) and widget_index < len(values):
        return values[widget_index]
    return None


def widget_consume_count(node: dict[str, Any], widget_index: int, input_name: str) -> int:
    values = node.get("widgets_values", [])
    if not isinstance(values, list):
        return 1
    seed_modes = {"fixed", "randomize", "increment", "decrement"}
    if input_name == "seed" and widget_index + 1 < len(values) and values[widget_index + 1] in seed_modes:
        return 2
    return 1


def build_api_prompt(workflow_data: dict[str, Any]) -> dict[str, Any]:
    workflow = Workflow(workflow_data)
    links = workflow.link_by_id
    prompt: dict[str, Any] = {}
    ids = {str(node["id"]) for node in workflow.nodes}

    for node in sorted(workflow.nodes, key=lambda item: int(item["id"])):
        inputs: dict[str, Any] = {}
        values = node.get("widgets_values", [])
        if node.get("type") == "Seed (rgthree)" and isinstance(values, list) and values:
            inputs["seed"] = values[0]

        widget_index = 0
        for input_slot in node.get("inputs", []) or []:
            input_name = input_slot.get("name")
            link = links.get(str(input_slot.get("link")))
            if link and str(link[1]) in ids:
                inputs[input_name] = [str(link[1]), link[2]]
            elif input_slot.get("widget") is not None:
                inputs[input_name] = widget_value(node, widget_index, input_slot.get("widget", {}).get("name", input_name))

            if input_slot.get("widget") is not None:
                widget_index += widget_consume_count(node, widget_index, input_slot.get("widget", {}).get("name", input_name))

        prompt[str(node["id"])] = {
            "inputs": inputs,
            "class_type": node.get("type"),
            "_meta": {"title": node.get("title") or node.get("type")},
        }

    return prompt


def apply_body_ratio_mapper_widget_values(workflow_data: dict[str, Any], api_prompt: dict[str, Any]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []

    for node in workflow_data.get("nodes", []) or []:
        if node.get("type") != "BodyRatioMapperProportionTransfer":
            continue
        prompt_node = api_prompt.get(str(node.get("id")))
        if not prompt_node:
            continue

        inputs = prompt_node.setdefault("inputs", {})
        changed: list[str] = []
        for index, input_name in enumerate(BODY_RATIO_MAPPER_WIDGET_INPUTS):
            value = widget_value(node, index, input_name)
            if value is None:
                continue
            if inputs.get(input_name) != value:
                inputs[input_name] = copy.deepcopy(value)
                changed.append(input_name)

        if changed:
            changes.append(
                {
                    "node_id": str(node.get("id")),
                    "class_type": prompt_node.get("class_type"),
                    "inputs": changed,
                }
            )

    return {"changes": changes}


def is_link_value(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def values_are_type_compatible(current_value: Any, new_value: Any) -> bool:
    if current_value is None:
        return True
    if isinstance(current_value, bool):
        return isinstance(new_value, bool)
    if isinstance(current_value, (int, float)) and not isinstance(current_value, bool):
        return isinstance(new_value, (int, float)) and not isinstance(new_value, bool)
    if isinstance(current_value, str):
        return isinstance(new_value, str)
    return isinstance(new_value, type(current_value))


def compatible_replacement_class(api_class_type: Any, repaired_class_type: Any) -> bool:
    replacement = COMPATIBLE_CUSTOM_NODE_REPLACEMENTS.get(str(api_class_type))
    return bool(replacement and replacement.get("replacement") == repaired_class_type)


def overlay_api_values(api_prompt: dict[str, Any], repaired_prompt: dict[str, Any]) -> dict[str, Any]:
    """Copy user-facing scalar values from an exported API prompt.

    The repaired prompt may intentionally alter links to flatten virtual Set/Get
    nodes or insert optional gates, so link inputs are left alone.
    """
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for node_id, api_node in api_prompt.items():
        repaired_node = repaired_prompt.get(str(node_id))
        if not repaired_node:
            skipped.append({"node_id": str(node_id), "reason": "node not present in repaired prompt"})
            continue
        class_was_replaced = compatible_replacement_class(api_node.get("class_type"), repaired_node.get("class_type"))
        if api_node.get("class_type") != repaired_node.get("class_type") and not class_was_replaced:
            skipped.append(
                {
                    "node_id": str(node_id),
                    "reason": "class_type mismatch",
                    "api_class_type": api_node.get("class_type"),
                    "repaired_class_type": repaired_node.get("class_type"),
                }
            )
            continue

        repaired_inputs = repaired_node.setdefault("inputs", {})
        changed_inputs: list[str] = []
        for input_name, api_value in (api_node.get("inputs") or {}).items():
            if is_link_value(api_value):
                continue
            if class_was_replaced and input_name not in repaired_inputs:
                skipped.append(
                    {
                        "node_id": str(node_id),
                        "input": input_name,
                        "reason": "input not supported by replacement class",
                        "api_class_type": api_node.get("class_type"),
                        "repaired_class_type": repaired_node.get("class_type"),
                    }
                )
                continue
            current_value = repaired_inputs.get(input_name)
            if not values_are_type_compatible(current_value, api_value):
                skipped.append(
                    {
                        "node_id": str(node_id),
                        "input": input_name,
                        "reason": "type mismatch; keeping repaired value",
                        "api_value_type": type(api_value).__name__,
                        "repaired_value_type": type(current_value).__name__,
                    }
                )
                continue
            if current_value != api_value:
                repaired_inputs[input_name] = copy.deepcopy(api_value)
                changed_inputs.append(input_name)

        if changed_inputs:
            updated.append(
                {
                    "node_id": str(node_id),
                    "class_type": repaired_node.get("class_type"),
                    "inputs": changed_inputs,
                }
            )

    return {"updated": updated, "skipped": skipped}


def repair_body_ratio_mapper_prompt(api_prompt: dict[str, Any]) -> dict[str, Any]:
    """Repair BodyRatioMapper API values shifted by custom-node schema drift."""
    changes: list[dict[str, Any]] = []
    anchor_modes = {"single_frame_multi_person", "multi_frame_single_person"}
    keys = [
        "anchor_output_mode",
        "print_detailed_logs",
        "confidence_threshold",
        "output_absolute_coordinates",
    ]

    for node_id, node in api_prompt.items():
        if node.get("class_type") != "BodyRatioMapperProportionTransfer":
            continue
        inputs = node.setdefault("inputs", {})
        before = {key: copy.deepcopy(inputs.get(key)) for key in keys if key in inputs}
        changed: list[str] = []

        if inputs.get("anchor_output_mode") not in anchor_modes:
            displaced_anchor = inputs.get("print_detailed_logs")
            inputs["anchor_output_mode"] = displaced_anchor if displaced_anchor in anchor_modes else "single_frame_multi_person"
            changed.append("anchor_output_mode")

        if "print_detailed_logs" in inputs and not isinstance(inputs.get("print_detailed_logs"), bool):
            candidate = inputs.get("confidence_threshold")
            inputs["print_detailed_logs"] = candidate if isinstance(candidate, bool) else False
            changed.append("print_detailed_logs")

        confidence = inputs.get("confidence_threshold")
        if "confidence_threshold" in inputs and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        ):
            candidate = inputs.get("output_absolute_coordinates")
            inputs["confidence_threshold"] = (
                candidate
                if isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                else 0.3
            )
            changed.append("confidence_threshold")

        if "output_absolute_coordinates" in inputs and not isinstance(inputs.get("output_absolute_coordinates"), bool):
            inputs["output_absolute_coordinates"] = True
            changed.append("output_absolute_coordinates")

        if changed:
            changes.append(
                {
                    "node_id": str(node_id),
                    "class_type": node.get("class_type"),
                    "inputs": changed,
                    "before": before,
                    "after": {key: copy.deepcopy(inputs.get(key)) for key in keys if key in inputs},
                }
            )

    return {"changes": changes}


def validate_body_ratio_mapper_prompt(api_prompt: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    anchor_modes = {"single_frame_multi_person", "multi_frame_single_person"}

    for node_id, node in api_prompt.items():
        if node.get("class_type") != "BodyRatioMapperProportionTransfer":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}

        anchor_mode = inputs.get("anchor_output_mode")
        if anchor_mode is not None and anchor_mode not in anchor_modes:
            issues.append(
                {
                    "node_id": str(node_id),
                    "input": "anchor_output_mode",
                    "value": anchor_mode,
                    "expected": sorted(anchor_modes),
                }
            )

        print_logs = inputs.get("print_detailed_logs")
        if print_logs is not None and not isinstance(print_logs, bool):
            issues.append(
                {
                    "node_id": str(node_id),
                    "input": "print_detailed_logs",
                    "value_type": type(print_logs).__name__,
                    "expected": "bool",
                }
            )

        confidence = inputs.get("confidence_threshold")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))):
            issues.append(
                {
                    "node_id": str(node_id),
                    "input": "confidence_threshold",
                    "value_type": type(confidence).__name__,
                    "expected": "number",
                }
            )

        absolute = inputs.get("output_absolute_coordinates")
        if absolute is not None and not isinstance(absolute, bool):
            issues.append(
                {
                    "node_id": str(node_id),
                    "input": "output_absolute_coordinates",
                    "value_type": type(absolute).__name__,
                    "expected": "bool",
                }
            )

    return {"issues": issues}


def validate_workflow(workflow_data: dict[str, Any]) -> dict[str, Any]:
    node_by_id = {str(node["id"]): node for node in workflow_data.get("nodes", [])}
    bad_links = []
    for link in workflow_data.get("links", []):
        src = node_by_id.get(str(link[1]))
        dst = node_by_id.get(str(link[3]))
        if not src or not dst:
            bad_links.append(link)
            continue
        if link[2] >= len(src.get("outputs", []) or []) or link[4] >= len(dst.get("inputs", []) or []):
            bad_links.append(link)
    return {
        "nodes": len(workflow_data.get("nodes", [])),
        "links": len(workflow_data.get("links", [])),
        "bad_links": len(bad_links),
        "residual_ui_nodes": [
            {"id": node["id"], "type": node.get("type")}
            for node in workflow_data.get("nodes", [])
            if node.get("type") in UI_ONLY_TYPES or node.get("type") in {"GetNode", "SetNode"}
        ],
    }


def convert(args: argparse.Namespace) -> dict[str, Any]:
    source = read_json(args.input)
    workflow = Workflow(copy.deepcopy(source))

    widget_report = normalize_legacy_widgets(workflow)
    compatible_nodes_report = replace_compatible_custom_nodes(workflow)
    reroute_report = strip_reroute_nodes(workflow)
    flatten_report = flatten_set_get(workflow)
    frontend_switch_report = convert_oct_posture_bypasser(workflow)
    profile_mapping = apply_motiontransfer_profile(workflow) if args.profile == "motiontransfer" else {"profile": args.profile}
    if args.output_mode == "all":
        keep_ids = all_executable_nodes(workflow)
    else:
        keep_ids = reachable_nodes(workflow, str(args.main_output_id))
    pruned = prune_workflow(workflow, keep_ids)
    api_prompt = build_api_prompt(pruned)
    body_ratio_widget_report = apply_body_ratio_mapper_widget_values(pruned, api_prompt)
    overlay_report = {"updated": [], "skipped": []}
    if args.api_input:
        overlay_report = overlay_api_values(read_json(args.api_input), api_prompt)
    body_ratio_report = repair_body_ratio_mapper_prompt(api_prompt)
    body_ratio_validation = validate_body_ratio_mapper_prompt(api_prompt)
    if body_ratio_validation["issues"]:
        raise ValueError(f"BodyRatioMapper API prompt validation failed: {body_ratio_validation['issues']}")

    mapping = {
        **profile_mapping,
        "main_output_node_id": str(args.main_output_id),
        "output_mode": args.output_mode,
        "workflow_output": str(args.workflow_output),
        "api_output": str(args.api_output),
        "api_input": str(args.api_input) if args.api_input else None,
        "normalize_legacy_widgets": widget_report,
        "compatible_custom_nodes": compatible_nodes_report,
        "strip_reroute_nodes": reroute_report,
        "flatten_set_get": flatten_report,
        "frontend_switches": frontend_switch_report,
        "body_ratio_mapper_widget_values": body_ratio_widget_report,
        "api_value_overlay": overlay_report,
        "body_ratio_mapper_api_repair": body_ratio_report,
        "body_ratio_mapper_api_validation": body_ratio_validation,
        "validation": validate_workflow(pruned),
    }

    write_json(args.workflow_output, pruned)
    write_json(args.api_output, api_prompt)
    write_json(args.mapping_output, mapping)
    return mapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Source ComfyUI workflow JSON.")
    parser.add_argument("--api-input", type=Path, help="Existing exported API prompt whose scalar values should be preserved.")
    parser.add_argument("--workflow-output", type=Path, required=True, help="Output API-friendly workflow JSON.")
    parser.add_argument("--api-output", type=Path, required=True, help="Output API prompt JSON.")
    parser.add_argument("--mapping-output", type=Path, required=True, help="Output parameter mapping report JSON.")
    parser.add_argument("--main-output-id", default=DEFAULT_MAIN_OUTPUT_ID, help="Main output node id to keep.")
    parser.add_argument(
        "--output-mode",
        default="main",
        choices=["main", "all"],
        help="Use 'main' to keep only the main output ancestry, or 'all' to keep every executable node.",
    )
    parser.add_argument("--profile", default="motiontransfer", choices=["motiontransfer", "generic"], help="Conversion profile.")
    return parser.parse_args()


if __name__ == "__main__":
    result = convert(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
