"""RunningHub full frontend workflow inspection helpers.

These functions read exported frontend workflow JSON and identify useful
runtime controls, especially switch-like nodes and group bypassers.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import fields


UI_ONLY_FRONTEND_NODE_TYPES = {
    "Note",
    "MarkdownNote",
    "Reroute",
    "GetNode",
    "SetNode",
    "Fast Groups Bypasser (rgthree)",
    "Fast Groups Muter (rgthree)",
}


def node_id(node: Dict[str, Any]) -> str:
    return str(node.get("id") or node.get("nodeId") or node.get("node_id") or node.get("nodeID") or "").strip()


def node_type(node: Dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return str(
        node.get("type")
        or node.get("class_type")
        or node.get("classType")
        or node.get("nodeType")
        or props.get("Node name for S&R")
        or ""
    ).strip()


def list_looks_like_frontend_nodes(items: Any) -> bool:
    if not isinstance(items, list):
        return False
    sample = [item for item in items[:8] if isinstance(item, dict)]
    if not sample:
        return False
    for item in sample:
        if node_id(item) and (
            node_type(item)
            or "widgets_values" in item
            or "inputs" in item
            or "outputs" in item
            or "fieldName" in item
        ):
            return True
    return False


def node_lists(value: Any, depth: int = 0) -> List[List[Dict[str, Any]]]:
    if depth > 8:
        return []
    lists: List[List[Dict[str, Any]]] = []
    node_keys = {"nodes", "nodeList", "node_list", "workflowNodes", "workflow_nodes", "nodeInfoList"}
    if isinstance(value, dict):
        for key in node_keys:
            items = value.get(key)
            if list_looks_like_frontend_nodes(items):
                lists.append([item for item in items if isinstance(item, dict)])
        for key, item in value.items():
            if key in node_keys:
                continue
            if isinstance(item, (dict, list)):
                lists.extend(node_lists(item, depth + 1))
    elif isinstance(value, list):
        if list_looks_like_frontend_nodes(value):
            lists.append([item for item in value if isinstance(item, dict)])
        else:
            for item in value[:30]:
                if isinstance(item, (dict, list)):
                    lists.extend(node_lists(item, depth + 1))
    return lists


def workflow_nodes(workflow: Any) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    seen = set()
    for node_list in node_lists(workflow):
        for node in node_list:
            current_id = node_id(node)
            key = current_id or str(id(node))
            if key in seen:
                continue
            seen.add(key)
            nodes.append(node)
    return nodes


def has_frontend_nodes(workflow: Any) -> bool:
    return bool(workflow_nodes(workflow))


def node_title(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    title = node.get("title")
    if title not in (None, ""):
        return fields.repair_text(str(title)).strip()
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    value = (
        props.get("Node name for S&R")
        or props.get("name")
        or node.get("nodeTitle")
        or node.get("nodeName")
        or node.get("label")
        or node.get("name")
        or node_type(node)
        or ""
    )
    return fields.repair_text(str(value)).strip()


def widget_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "false", "yes", "no", "on", "off", "0", "1"}:
            return value
    return None


def io_has_opt_connection(items: Any) -> bool:
    if isinstance(items, list):
        return any(
            isinstance(item, dict)
            and re.search(r"opt[_\s-]*connection", f"{item.get('type') or ''} {item.get('name') or ''} {item.get('label') or ''}", re.I)
            for item in items
        )
    if isinstance(items, dict):
        return any(
            re.search(r"opt[_\s-]*connection", f"{key} {value}", re.I)
            for key, value in items.items()
        )
    return False


def node_position(node: Dict[str, Any]) -> tuple[float, float]:
    pos = node.get("pos")
    if isinstance(pos, list) and len(pos) >= 2:
        try:
            return float(pos[0]), float(pos[1])
        except Exception:
            pass
    return 0.0, 0.0


def group_contains_node(group: Dict[str, Any], node: Dict[str, Any]) -> bool:
    bounding = group.get("bounding")
    if not isinstance(bounding, list) or len(bounding) < 4:
        return False
    try:
        gx, gy, width, height = (float(bounding[0]), float(bounding[1]), float(bounding[2]), float(bounding[3]))
    except Exception:
        return False
    x, y = node_position(node)
    return gx <= x <= gx + width and gy <= y <= gy + height


def groups(workflow: Any) -> List[Dict[str, Any]]:
    if not isinstance(workflow, dict):
        return []
    raw_groups = workflow.get("groups")
    if isinstance(raw_groups, list):
        return [group for group in raw_groups if isinstance(group, dict)]
    data = workflow.get("data")
    if isinstance(data, dict) and data is not workflow:
        return groups(data)
    return []


def rgthree_group_bypasser_default(workflow: Any, node: Dict[str, Any]) -> Optional[str]:
    current_type = node_type(node).lower()
    title = node_title(node).lower()
    if not any(token in current_type for token in ("fast groups bypasser", "groups bypasser", "fast groups muter", "groups muter")):
        return None
    if not (io_has_opt_connection(node.get("outputs")) or "switch" in title):
        return None
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    match_title = str(props.get("matchTitle") or "").strip()
    nodes = workflow_nodes(workflow)
    matched_groups = [
        group for group in groups(workflow)
        if match_title and match_title in str(group.get("title") or "")
    ]
    if not matched_groups:
        return "yes" if int(node.get("mode") or 0) != 4 else "no"
    for group in matched_groups:
        group_nodes = [
            item for item in nodes
            if node_id(item) != node_id(node) and group_contains_node(group, item)
        ]
        for item in group_nodes:
            current_type = node_type(item)
            if current_type in UI_ONLY_FRONTEND_NODE_TYPES:
                continue
            if int(item.get("mode") or 0) != 4:
                return "yes"
    return "no"


def widget_field_names(node: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    inputs = node.get("inputs")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict):
                continue
            widget = item.get("widget") if isinstance(item.get("widget"), dict) else {}
            name = str(widget.get("name") or item.get("name") or item.get("label") or "").strip()
            item_text = f"{item.get('type') or ''} {name}".lower()
            if name and not re.search(r"opt[_\s-]*connection", item_text):
                names.append(name)
    elif isinstance(inputs, dict):
        for name, value in inputs.items():
            if widget_scalar(value) is not None:
                names.append(str(name))
    return names


def switch_default(node: Dict[str, Any]) -> tuple[str, Any]:
    for key in ("fieldName", "field_name", "input", "name"):
        if key in node and any(value_key in node for value_key in ("fieldValue", "field_value", "default", "value")):
            for value_key in ("fieldValue", "field_value", "default", "value"):
                scalar = widget_scalar(node.get(value_key))
                if scalar is not None:
                    return str(node.get(key) or "value"), scalar
    widgets = node.get("widgets_values")
    if isinstance(widgets, list):
        names = widget_field_names(node)
        for index, value in enumerate(widgets):
            scalar = widget_scalar(value)
            if scalar is not None:
                return (names[index] if index < len(names) else "value"), scalar
    inputs = node.get("inputs")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("label") or "").strip()
            if name and re.search(r"value|default|enabled|enable|switch|toggle|bool|condition|cond", name, re.I):
                scalar = widget_scalar(item.get("value"))
                if scalar is not None:
                    return name, scalar
    if isinstance(inputs, dict):
        for name, value in inputs.items():
            scalar = widget_scalar(value)
            if scalar is not None:
                return str(name), scalar
    return "", None


def switch_fields(workflow: Any, existing_keys: set[str] | None = None) -> List[Dict[str, Any]]:
    existing_keys = set(existing_keys or [])
    output: List[Dict[str, Any]] = []
    for node in workflow_nodes(workflow):
        current_id = node_id(node)
        if not current_id:
            continue
        current_type = node_type(node)
        if re.search(r"shellagentplugininput", current_type, re.I):
            continue
        title = node_title(node)
        combined = f"{current_type} {title}".lower()
        field_name, default = switch_default(node)
        has_opt_connection = (
            io_has_opt_connection(node.get("inputs"))
            or io_has_opt_connection(node.get("outputs"))
            or re.search(r"opt[_\s-]*connection", json.dumps(node, ensure_ascii=False)[:2500], re.I) is not None
        )
        switchish = any(key in combined for key in [
            "primitiveboolean", "boolean", "bool", "switch", "toggle", "enable",
            "enabled", "opt_connection", "optconnection",
        ]) or has_opt_connection
        if not switchish:
            continue
        if default is None:
            default = rgthree_group_bypasser_default(workflow, node)
        if default is None:
            continue
        if not field_name:
            field_name = "value"
        key = f"{current_id}.{field_name}"
        if key in existing_keys:
            continue
        field_type, options = fields.switch_type_and_options(default)
        output.append(fields.normalize_field(
            {
                "id": key,
                "label": title or f"Node {current_id} / {field_name}",
                "nodeId": current_id,
                "nodeTitle": title,
                "classType": current_type,
                "fieldName": field_name,
                "type": field_type,
                "default": default,
                "options": options,
            },
            len(output),
        ))
        existing_keys.add(key)
    return output


def merge_fields_preserving_order(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for group in groups:
        for field in group or []:
            key = fields.field_key({"node": field.get("nodeId"), "input": field.get("fieldName")})
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(field)
    return merged


def switch_semantic_name(value: Any) -> str:
    text = fields.repair_text(str(value or "")).lower()
    text = re.split(r"\s*/\s*", text, maxsplit=1)[0]
    text = re.sub(r"\b(input|api|octinput)[_-]+", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)
    return re.sub(r"(defaultvalue|value)$", "", text)


def field_switchish_for_dedupe(field: Dict[str, Any]) -> bool:
    if fields.clean_field_type((field or {}).get("type")) not in {"boolean", "dropdown"}:
        return False
    text = f"{field.get('label') or ''} {field.get('nodeTitle') or ''} {field.get('classType') or ''} {field.get('fieldName') or ''}".lower()
    return any(key in text for key in ["enable", "enabled", "switch", "toggle", "opt_connection", "optconnection", "primitiveboolean", "boolean"])


def dedupe_switch_fields(items: List[Dict[str, Any]], preferred_node_ids: set[str] | None = None) -> List[Dict[str, Any]]:
    preferred_node_ids = {str(item) for item in (preferred_node_ids or set())}
    output: List[Dict[str, Any]] = []
    semantic_index: Dict[str, int] = {}
    for field in items or []:
        semantic = switch_semantic_name(field.get("label") or field.get("nodeTitle"))
        if not semantic or not field_switchish_for_dedupe(field):
            output.append(field)
            continue
        if semantic not in semantic_index:
            semantic_index[semantic] = len(output)
            output.append(field)
            continue
        old_index = semantic_index[semantic]
        old = output[old_index]
        old_preferred = str(old.get("nodeId") or "") in preferred_node_ids
        new_preferred = str(field.get("nodeId") or "") in preferred_node_ids
        if new_preferred and not old_preferred:
            output[old_index] = field
    return output
