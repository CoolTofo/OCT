"""RunningHub workflow field extraction helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from . import fields


def is_shellagent_input(class_type: str = "", node_title: str = "", label: str = "") -> bool:
    text = f"{class_type or ''} {node_title or ''} {label or ''}".lower()
    return "shellagentplugininput" in text or ("shellagent plugin" in text and "input" in text)


def infer_field_type(input_name: str, value: Any) -> str:
    name = str(input_name or "").lower()
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and any(k in name for k in ["cfg", "denoise", "strength", "scale", "weight", "ratio", "rate"]):
        return "number"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    if any(k in name for k in ["image", "img", "picture", "photo"]):
        return "image"
    if "video" in name:
        return "video"
    if "audio" in name or "sound" in name:
        return "audio"
    if name in {"prompt", "text", "positive", "negative"} or len(str(value or "")) > 120:
        return "textarea"
    return "text"


def shellagent_field_type(class_type: str = "", input_name: str = "", default: Any = None) -> str:
    text = f"{class_type or ''} {input_name or ''}".lower()
    if "boolean" in text or isinstance(default, bool):
        return "boolean"
    if "integer" in text or "int" in text:
        return "integer"
    if "float" in text or "number" in text:
        return "number"
    if "image" in text:
        return "image"
    if "video" in text:
        return "video"
    if "audio" in text:
        return "audio"
    if "text" in text or "string" in text:
        return "textarea" if len(str(default or "")) > 120 else "text"
    return infer_field_type(input_name, default)


def is_octinput_switch(class_type: str = "", node_title: str = "", label: str = "", field_name: str = "") -> bool:
    text = f"{class_type or ''} {node_title or ''} {label or ''} {field_name or ''}".lower()
    has_octinput = "octinput" in text
    has_switch = any(key in text for key in [
        "switch",
        "toggle",
        "enable",
        "enabled",
        "boolean",
        "bool",
        "opt_connection",
        "optconnection",
        "primitiveboolean",
    ])
    return has_octinput and has_switch


def link_source_matches(value: Any, source_node_id: str) -> bool:
    if isinstance(value, (list, tuple)) and value:
        return str(value[0]) == str(source_node_id)
    return False


def node_title(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    return fields.repair_text(str((node.get("_meta") or {}).get("title") or ""))


def workflow_node_items(workflow: Any) -> List[tuple[str, Dict[str, Any]]]:
    if not isinstance(workflow, dict):
        return []
    items: List[tuple[str, Dict[str, Any]]] = []
    for node_id, node in workflow.items():
        if isinstance(node, dict) and ("inputs" in node or "class_type" in node):
            items.append((str(node_id), node))
    data = workflow.get("data")
    if isinstance(data, dict) and data is not workflow:
        nested = workflow_node_items(data)
        if nested:
            items.extend(nested)
    return items


def shellagent_video_target(workflow: Any, source_node_id: str) -> Dict[str, Any] | None:
    direct_matches: List[Dict[str, Any]] = []
    fallback_matches: List[Dict[str, Any]] = []
    for target_node_id, node in workflow_node_items(workflow):
        if target_node_id == str(source_node_id) or not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        class_type = str(node.get("class_type") or "")
        title = node_title(node)
        class_text = f"{class_type} {title}".replace("_", "").replace(" ", "").lower()
        is_loader = "vhsloadvideo" in class_text or "loadvideo" in class_text
        for field_name, value in inputs.items():
            if not link_source_matches(value, source_node_id):
                continue
            field_text = str(field_name or "").lower()
            item = {
                "nodeId": target_node_id,
                "fieldName": str(field_name),
                "nodeTitle": title,
                "classType": class_type,
            }
            if is_loader and field_text == "video":
                direct_matches.append(item)
            elif is_loader or "video" in field_text:
                fallback_matches.append(item)
    return (direct_matches or fallback_matches or [None])[0]


def octinput_switch_fields_from_nodes(workflow: Any, skip_node_ids: set[str] | None = None) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    skip_node_ids = set(skip_node_ids or [])
    if not isinstance(workflow, dict):
        return output
    data = workflow.get("data")
    if isinstance(data, dict) and data is not workflow:
        nested = octinput_switch_fields_from_nodes(data, skip_node_ids)
        if nested:
            return nested
    preferred_names = ["value", "default_value", "enabled", "enable", "switch", "toggle", "boolean", "bool", "cond", "condition"]
    for node_id, node in workflow.items():
        if str(node_id) in skip_node_ids or not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = fields.repair_text(str((node.get("_meta") or {}).get("title") or ""))
        class_type = str(node.get("class_type") or "")
        if not is_octinput_switch(class_type, title):
            continue
        field_name = ""
        default = None
        for name in preferred_names:
            if name in inputs and fields.scalar_switch_value(inputs.get(name)):
                field_name = name
                default = inputs.get(name)
                break
        if not field_name:
            for name, value in inputs.items():
                if fields.scalar_switch_value(value):
                    field_name = str(name)
                    default = value
                    break
        if not field_name:
            continue
        field_type, options = fields.switch_type_and_options(default)
        output.append(fields.normalize_field(
            {
                "id": f"{node_id}.{field_name}",
                "label": title or f"Node {node_id} / {field_name}",
                "nodeId": str(node_id),
                "nodeTitle": title,
                "classType": class_type,
                "fieldName": field_name,
                "type": field_type,
                "default": default,
                "options": options,
            },
            len(output),
        ))
    return output


def shellagent_fields_from_nodes(workflow: Any) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(workflow, dict):
        return output
    data = workflow.get("data")
    if isinstance(data, dict) and data is not workflow:
        nested = shellagent_fields_from_nodes(data)
        if nested:
            return nested
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or "")
        class_type = str(node.get("class_type") or "")
        if not is_shellagent_input(class_type, title):
            continue
        input_name = fields.repair_text(str(inputs.get("input_name") or title or f"Node {node_id}").strip())
        field_name = "default_value" if "default_value" in inputs else "value"
        default = inputs.get(field_name, "")
        field_type = shellagent_field_type(class_type, input_name, default)
        target = shellagent_video_target(workflow, node_id) if field_type == "video" else None
        out_node_id = str((target or {}).get("nodeId") or node_id)
        out_field_name = str((target or {}).get("fieldName") or field_name)
        out_title = (target or {}).get("nodeTitle") or title or input_name
        out_class_type = (target or {}).get("classType") or class_type
        required = field_type == "video" and str(default or "").strip().lower() in {"", "none", "null"}
        output.append(fields.normalize_field(
            {
                "id": f"{out_node_id}.{out_field_name}",
                "label": input_name,
                "nodeId": out_node_id,
                "nodeTitle": out_title,
                "classType": out_class_type,
                "fieldName": out_field_name,
                "type": field_type,
                "default": "" if required else default,
                "required": required,
                "accept": fields.shellagent_accept(field_type),
                "options": fields.shellagent_options(inputs.get("choices")),
            },
            len(output),
        ))
    return output


def merge_external_fields(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for group in groups:
        for field in group or []:
            key = (str(field.get("nodeId") or ""), str(field.get("fieldName") or ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(field)
    return merged


def shellagent_fields_from_field_list(raw_fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for raw in raw_fields or []:
        if not isinstance(raw, dict):
            continue
        field = fields.normalize_field(raw, len(order))
        if not is_shellagent_input(field.get("classType"), field.get("nodeTitle"), field.get("label")):
            continue
        node_id = str(field.get("nodeId") or "").strip()
        if not node_id:
            continue
        group = groups.setdefault(node_id, {"fields": {}, "sample": field})
        if node_id not in order:
            order.append(node_id)
        group["fields"][str(field.get("fieldName") or "")] = field
        if field.get("classType") or field.get("nodeTitle"):
            group["sample"] = {**group.get("sample", {}), **field}
    output: List[Dict[str, Any]] = []
    for node_id in order:
        group = groups.get(node_id) or {}
        by_name = group.get("fields") or {}
        sample = group.get("sample") or {}
        name_field = by_name.get("input_name")
        value_field = by_name.get("default_value") or by_name.get("value") or name_field
        if not value_field:
            continue
        input_name = fields.repair_text(str((name_field or {}).get("default") or sample.get("label") or sample.get("nodeTitle") or f"Node {node_id}").strip())
        field_name = value_field.get("fieldName") or "default_value"
        default = value_field.get("default", "")
        field_type = shellagent_field_type(sample.get("classType"), input_name, default)
        choice_field = by_name.get("choices")
        output.append(fields.normalize_field(
            {
                "id": f"{node_id}.{field_name}",
                "label": input_name,
                "nodeId": node_id,
                "nodeTitle": sample.get("nodeTitle") or input_name,
                "classType": sample.get("classType") or "",
                "fieldName": field_name,
                "type": field_type,
                "default": default,
                "accept": fields.shellagent_accept(field_type),
                "options": fields.shellagent_options((choice_field or {}).get("default", "")),
            },
            len(output),
        ))
    return output


def octinput_switch_fields_from_field_list(raw_fields: List[Dict[str, Any]], skip_node_ids: set[str] | None = None) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    skip_node_ids = set(skip_node_ids or [])
    for raw in raw_fields or []:
        if not isinstance(raw, dict):
            continue
        field = fields.normalize_field(raw, len(output))
        node_id = str(field.get("nodeId") or "").strip()
        if not node_id or node_id in skip_node_ids:
            continue
        if not is_octinput_switch(field.get("classType"), field.get("nodeTitle"), field.get("label"), field.get("fieldName")):
            continue
        default = field.get("default", "")
        if not fields.scalar_switch_value(default):
            continue
        field_type, options = fields.switch_type_and_options(default)
        field["type"] = field_type
        field["options"] = options
        output.append(field)
    return output


def is_shellagent_proxy_field(field: Dict[str, Any]) -> bool:
    field_type = fields.clean_field_type((field or {}).get("type"))
    field_name = str((field or {}).get("fieldName") or "").strip().lower()
    class_text = f"{(field or {}).get('classType') or ''} {(field or {}).get('nodeTitle') or ''}".replace("_", "").replace(" ", "").lower()
    label = str((field or {}).get("label") or "").strip().lower()
    if field_type == "video" and field_name == "video" and ("vhsloadvideo" in class_text or "loadvideo" in class_text):
        return label.startswith("input") or "octinput" in label
    return False


def shellagent_proxy_fields_from_field_list(raw_fields: List[Dict[str, Any]], skip_keys: set[tuple[str, str]] | None = None) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    skip_keys = set(skip_keys or [])
    for raw in raw_fields or []:
        if not isinstance(raw, dict):
            continue
        field = fields.normalize_field(raw, len(output))
        key = (str(field.get("nodeId") or ""), str(field.get("fieldName") or ""))
        if key in skip_keys or not is_shellagent_proxy_field(field):
            continue
        default = field.get("default", "")
        if str(default or "").strip().lower() in {"", "none", "null"}:
            field["default"] = ""
            field["required"] = True
        field["accept"] = field.get("accept") or fields.shellagent_accept(field.get("type"))
        output.append(field)
    return output


def fields_from_workflow_json(workflow: Any) -> List[Dict[str, Any]]:
    workflow = fields.repair_mojibake(workflow)
    output: List[Dict[str, Any]] = []
    if not isinstance(workflow, dict):
        return output
    shell_fields = shellagent_fields_from_nodes(workflow)
    switch_fields = octinput_switch_fields_from_nodes(workflow, {field.get("nodeId") for field in shell_fields})
    external_fields = merge_external_fields(shell_fields, switch_fields)
    if external_fields:
        return external_fields
    node_info_list = workflow.get("nodeInfoList") or workflow.get("node_info_list")
    if isinstance(node_info_list, list):
        shell_fields = shellagent_fields_from_field_list(node_info_list)
        switch_fields = octinput_switch_fields_from_field_list(node_info_list, {field.get("nodeId") for field in shell_fields})
        external_fields = merge_external_fields(shell_fields, switch_fields)
        if external_fields:
            return external_fields
        for item in node_info_list:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("nodeId") or item.get("node_id") or "").strip()
            field_name = str(item.get("fieldName") or item.get("field_name") or "").strip()
            if not node_id or not field_name:
                continue
            default = item.get("fieldValue", item.get("field_value", ""))
            node_title_value = fields.first_text(item, "nodeTitle", "node_title", "nodeName", "node_name", "nodeLabel", "node_label", "title")
            class_type = fields.first_text(item, "classType", "class_type")
            label = fields.first_text(item, "label", "fieldLabel", "field_label", "fieldTitle", "field_title", "displayName", "display_name", "name")
            output.append(fields.normalize_field(
                {
                    "id": f"{node_id}.{field_name}",
                    "label": label or (f"{node_title_value} / {field_name}" if node_title_value else f"Node {node_id} / {field_name}"),
                    "nodeId": node_id,
                    "nodeTitle": node_title_value,
                    "classType": class_type,
                    "fieldName": field_name,
                    "type": infer_field_type(field_name, default),
                    "default": default,
                },
                len(output),
            ))
        return output
    data = workflow.get("data")
    if isinstance(data, dict) and data is not workflow:
        nested_fields = fields_from_workflow_json(data)
        if nested_fields:
            return nested_fields
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or "")
        class_type = str(node.get("class_type") or "")
        label = title or class_type or f"Node {node_id}"
        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                continue
            options = value if isinstance(value, list) and all(isinstance(x, (str, int, float)) for x in value) else []
            default = options[0] if options else value
            field_type = "dropdown" if options else infer_field_type(input_name, value)
            output.append(fields.normalize_field(
                {
                    "id": f"{node_id}.{input_name}",
                    "label": f"{label} / {input_name}",
                    "nodeId": str(node_id),
                    "nodeTitle": title,
                    "classType": class_type,
                    "fieldName": str(input_name),
                    "type": field_type,
                    "default": default,
                    "options": options,
                },
                len(output),
            ))
    return output
