import re
from typing import Any


def is_comfy_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def is_reroute_node(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    class_type = str(node.get("class_type") or "")
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    node_title = str(meta.get("title") or "")
    return "reroute" in f"{class_type} {node_title}".lower()


def first_link_input(node: Any):
    inputs = node.get("inputs") if isinstance(node, dict) else None
    if not isinstance(inputs, dict):
        return None
    for key in ("", "input", "in", "value"):
        value = inputs.get(key)
        if is_comfy_link(value):
            return value
    for value in inputs.values():
        if is_comfy_link(value):
            return value
    return None


def resolve_reroute_link(workflow: Any, link: Any, seen=None):
    if not is_comfy_link(link):
        return link
    if seen is None:
        seen = set()
    source_id = str(link[0])
    if source_id in seen:
        return link
    node = workflow.get(source_id)
    if not is_reroute_node(node):
        return link
    seen.add(source_id)
    upstream = first_link_input(node)
    if not is_comfy_link(upstream):
        return link
    return resolve_reroute_link(workflow, upstream, seen)


def strip_reroute_nodes(workflow: Any) -> int:
    if not isinstance(workflow, dict):
        return 0
    reroute_ids = {
        str(node_id)
        for node_id, node in workflow.items()
        if is_reroute_node(node)
    }
    if not reroute_ids:
        return 0

    for node_id, node in list(workflow.items()):
        if str(node_id) in reroute_ids or not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name, value in list(inputs.items()):
            if is_comfy_link(value) and str(value[0]) in reroute_ids:
                resolved = resolve_reroute_link(workflow, value)
                if is_comfy_link(resolved):
                    inputs[input_name] = list(resolved)

    for node_id in reroute_ids:
        workflow.pop(node_id, None)
    return len(reroute_ids)


def node_class(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("class_type") or "")


def normalize_class_name(class_type: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(class_type or "").lower())


def coerce_bool(value: Any):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off", ""}:
            return False
    return None


def is_api_helper_node(node: Any) -> bool:
    class_name = normalize_class_name(node_class(node))
    return class_name in {
        "apibooleanand",
        "apibooleanor",
        "apibooleannot",
        "apilazyswitch",
        "primitiveboolean",
    }


def resolve_api_helper_value(workflow: Any, value: Any, seen=None):
    if not is_comfy_link(value):
        return value
    if seen is None:
        seen = set()

    source_id = str(value[0])
    if source_id in seen:
        return value
    node = workflow.get(source_id)
    class_name = normalize_class_name(node_class(node))
    if class_name not in {"apibooleanand", "apibooleanor", "apibooleannot", "apilazyswitch", "primitiveboolean"}:
        return value

    seen.add(source_id)
    inputs = node.get("inputs") if isinstance(node, dict) else {}
    if not isinstance(inputs, dict):
        return value

    if class_name == "primitiveboolean":
        resolved = resolve_api_helper_value(workflow, inputs.get("value"), seen)
        bool_value = coerce_bool(resolved)
        return value if bool_value is None else bool_value

    if class_name in {"apibooleanand", "apibooleanor"}:
        left = coerce_bool(resolve_api_helper_value(workflow, inputs.get("a"), seen.copy()))
        right = coerce_bool(resolve_api_helper_value(workflow, inputs.get("b"), seen.copy()))
        if left is None or right is None:
            return value
        return left and right if class_name == "apibooleanand" else left or right

    if class_name == "apibooleannot":
        item = inputs.get("value", inputs.get("a"))
        bool_value = coerce_bool(resolve_api_helper_value(workflow, item, seen))
        return value if bool_value is None else not bool_value

    if class_name == "apilazyswitch":
        cond = coerce_bool(resolve_api_helper_value(workflow, inputs.get("cond"), seen.copy()))
        if cond is None:
            return value
        branch = inputs.get("on_true") if cond else inputs.get("on_false")
        return resolve_api_helper_value(workflow, branch, seen)

    return value


def fold_api_helper_nodes(workflow: Any) -> int:
    if not isinstance(workflow, dict):
        return 0
    helper_ids = {
        str(node_id)
        for node_id, node in workflow.items()
        if is_api_helper_node(node)
    }
    if not helper_ids:
        return 0

    for node_id, node in list(workflow.items()):
        if str(node_id) in helper_ids or not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name, value in list(inputs.items()):
            if is_comfy_link(value) and str(value[0]) in helper_ids:
                resolved = resolve_api_helper_value(workflow, value)
                inputs[input_name] = list(resolved) if is_comfy_link(resolved) else resolved

    unresolved_refs = []
    for node_id, node in list(workflow.items()):
        if str(node_id) in helper_ids or not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if is_comfy_link(value) and str(value[0]) in helper_ids:
                unresolved_refs.append(f"{node_id}.{input_name}->{value[0]}")

    if unresolved_refs:
        raise ValueError(f"Unable to fold API helper nodes: {', '.join(unresolved_refs[:8])}")

    for node_id in helper_ids:
        workflow.pop(node_id, None)
    return len(helper_ids)


def repair_body_ratio_mapper_api_values(workflow: Any):
    if not isinstance(workflow, dict):
        return []
    fixes = []
    anchor_modes = {"single_frame_multi_person", "multi_frame_single_person"}
    for node_id, node in workflow.items():
        if node_class(node) != "BodyRatioMapperProportionTransfer":
            continue
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        changed = []
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
            fixes.append({"node_id": str(node_id), "inputs": changed})
    return fixes


def validate_body_ratio_mapper_api_values(workflow: Any):
    if not isinstance(workflow, dict):
        return []
    issues = []
    anchor_modes = {"single_frame_multi_person", "multi_frame_single_person"}
    for node_id, node in workflow.items():
        if node_class(node) != "BodyRatioMapperProportionTransfer":
            continue
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        anchor_mode = inputs.get("anchor_output_mode")
        if anchor_mode is not None and anchor_mode not in anchor_modes:
            issues.append({"node_id": str(node_id), "input": "anchor_output_mode", "value": anchor_mode})
        print_logs = inputs.get("print_detailed_logs")
        if print_logs is not None and not isinstance(print_logs, bool):
            issues.append({"node_id": str(node_id), "input": "print_detailed_logs", "value_type": type(print_logs).__name__})
        confidence = inputs.get("confidence_threshold")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))):
            issues.append({"node_id": str(node_id), "input": "confidence_threshold", "value_type": type(confidence).__name__})
        absolute = inputs.get("output_absolute_coordinates")
        if absolute is not None and not isinstance(absolute, bool):
            issues.append({"node_id": str(node_id), "input": "output_absolute_coordinates", "value_type": type(absolute).__name__})
    return issues
