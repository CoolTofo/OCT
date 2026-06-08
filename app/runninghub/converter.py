"""RunningHub workflow conversion facade.

This module owns the translation from exported frontend/API workflow JSON into
the field list used by the RunningHub node UI. Route code should call this
facade instead of knowing ComfyUI conversion internals.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.comfyui import workflows as comfy_workflows
from app.runninghub import extractors, fields, frontend, service
from app.runninghub.schemas import RunningHubWorkflowConvertRequest


def parse_jsonish(value: Any, label: str = "workflow") -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            text = fenced.group(1).strip()
        try:
            return json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{label} JSON is invalid: {exc}") from exc
    return value


def unwrap_workflow_object(value: Any) -> Any:
    value = parse_jsonish(value)
    if not isinstance(value, dict):
        return value
    if frontend.has_frontend_nodes(value) or comfy_workflows.is_api_prompt_workflow(value):
        return value
    for key in ("workflow", "api_workflow", "prompt"):
        nested = value.get(key)
        if isinstance(nested, str) and nested.strip():
            try:
                return json.loads(nested)
            except Exception:
                pass
        if isinstance(nested, dict):
            return nested
    data = value.get("data")
    if isinstance(data, dict):
        prompt = data.get("prompt") or data.get("workflow") or data.get("api_workflow")
        if isinstance(prompt, str) and prompt.strip():
            try:
                return json.loads(prompt)
            except Exception:
                pass
        if isinstance(prompt, dict):
            return prompt
    return value


def field_key(field: Dict[str, Any]) -> str:
    return f"{field.get('node') or field.get('nodeId') or ''}.{field.get('input') or field.get('fieldName') or ''}"


def comfy_field_to_field(
    field: Dict[str, Any],
    fallback_index: int = 0,
    label_override: str = "",
    default_override: Any = None,
) -> Dict[str, Any]:
    node_id = str(field.get("node") or field.get("nodeId") or "").strip()
    input_name = str(field.get("input") or field.get("fieldName") or "").strip()
    field_type = str(field.get("type") or "text").strip().lower()
    if field_type == "slider":
        field_type = "number"
    default = field.get("default", "")
    if default_override is not None:
        default = default_override
    accept = field.get("accept") or {"image": "image/*", "video": "video/*", "audio": "audio/*"}.get(field_type, "")
    return service.normalize_field(
        {
            "id": f"{node_id}.{input_name}" if node_id and input_name else field.get("id", ""),
            "label": label_override
            or field.get("name")
            or field.get("label")
            or f"{field.get('nodeTitle') or node_id} / {input_name}",
            "nodeId": node_id,
            "nodeTitle": field.get("nodeTitle") or "",
            "classType": field.get("classType") or "",
            "fieldName": input_name,
            "type": field_type,
            "default": default,
            "required": bool(field.get("required", False)),
            "accept": accept,
            "options": field.get("options") if isinstance(field.get("options"), list) else [],
        },
        fallback_index,
    )


def mapping_switch_entries(mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    runtime = mapping.get("runtime_switches") if isinstance(mapping, dict) else {}
    if isinstance(runtime, dict):
        for name, item in runtime.items():
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "name": str(name),
                    "node_id": str(item.get("enabled_node_id") or ""),
                    "input": str(item.get("enabled_input") or "value"),
                    "default": item.get("default", False),
                    "source": "runtime_switches",
                }
            )
    frontend_switches = mapping.get("frontend_switches") if isinstance(mapping, dict) else {}
    converted = frontend_switches.get("converted") if isinstance(frontend_switches, dict) else []
    if isinstance(converted, list):
        for item in converted:
            for switch in (item.get("switches") if isinstance(item, dict) else []) or []:
                if not isinstance(switch, dict):
                    continue
                entries.append(
                    {
                        "name": str(switch.get("name") or switch.get("group") or "frontend_switch"),
                        "node_id": str(switch.get("enabled_node_id") or ""),
                        "input": str(switch.get("enabled_input") or "value"),
                        "default": switch.get("default", False),
                        "source": "frontend_switches",
                    }
                )
    deduped = []
    seen = set()
    for item in entries:
        key = (item.get("node_id"), item.get("input"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def should_expose_comfy_field(field: Dict[str, Any], mapped_keys=None) -> bool:
    mapped_keys = mapped_keys or set()
    key = field_key(field)
    if key in mapped_keys:
        return True
    input_name = str(field.get("input") or "").strip().lower()
    if input_name in {"filename_prefix", "filename", "prefix", "save_metadata", "preview", "no_preview"}:
        return False
    field_type = str(field.get("type") or "").lower()
    class_type = str(field.get("classType") or "").lower()
    title = str(field.get("nodeTitle") or "").lower()
    label = f"{field.get('name') or ''} {field.get('nodeTitle') or ''} {field.get('classType') or ''}".lower()
    if comfy_workflows.is_essential_comfy_field(field):
        return True
    if re.search(r"(^|\s|/)(octinput|input_|get_|set_)", label):
        return True
    if "octinput" in title or title.startswith(("input_", "get_", "set_")):
        return True
    if class_type in {"primitiveboolean", "boolean", "bool"} and re.search(r"enable|switch|toggle|bool|uni3c|face|pose", label):
        return True
    important_inputs = {
        "image",
        "video",
        "audio",
        "text",
        "prompt",
        "positive",
        "negative",
        "positive_prompt",
        "negative_prompt",
        "width",
        "height",
        "custom_width",
        "custom_height",
        "seed",
        "steps",
        "cfg",
        "cfg_scale",
        "denoise",
        "frame_rate",
        "fps",
        "frame_load_cap",
        "skip_first_frames",
        "value",
        "default_value",
    }
    if input_name in important_inputs:
        if field_type in {"image", "video", "audio", "textarea", "boolean"}:
            return True
        if re.search(r"width|height|seed|step|cfg|denoise|frame|fps|rate|count|swap|strength|scale|ratio", label):
            return True
    return False


def fields_from_comfy_api_prompt(
    api_prompt: Dict[str, Any],
    mapping: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    mapping = mapping or {}
    comfy_fields = comfy_workflows.extract_api_prompt_fields(api_prompt)
    by_key = {field_key(field): field for field in comfy_fields}
    switch_entries = mapping_switch_entries(mapping)
    mapped_keys = {f"{item['node_id']}.{item['input']}" for item in switch_entries}
    output: List[Dict[str, Any]] = []
    seen = set()

    def add_field(field, label_override="", default_override=None):
        key = field_key(field)
        if not key or key in seen:
            return
        seen.add(key)
        output.append(comfy_field_to_field(field, len(output), label_override, default_override))

    for switch in switch_entries:
        key = f"{switch['node_id']}.{switch['input']}"
        field = by_key.get(key) or {
            "node": switch["node_id"],
            "input": switch["input"],
            "name": switch["name"],
            "nodeTitle": f"Input_{switch['name']}",
            "classType": "PrimitiveBoolean",
            "type": "boolean",
            "default": switch.get("default", False),
            "options": [],
        }
        field = dict(field)
        field["type"] = "boolean"
        add_field(field, switch["name"], switch.get("default", field.get("default", False)))

    for field in comfy_fields:
        if should_expose_comfy_field(field, mapped_keys):
            add_field(field)

    output = fields.hide_video_loader_internal_fields(output)
    output = fields.external_input_fields(output)
    if not output:
        output = extractors.fields_from_workflow_json(api_prompt)
    return output, {
        "field_count": len(output),
        "candidate_count": len(comfy_fields),
        "switch_count": len(switch_entries),
    }


def all_fields_from_comfy_api_prompt(
    api_prompt: Dict[str, Any],
    mapping: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    mapping = mapping or {}
    comfy_fields = comfy_workflows.extract_api_prompt_fields(api_prompt)
    switch_entries = mapping_switch_entries(mapping)
    output: List[Dict[str, Any]] = []
    seen = set()

    def add_field(field, label_override="", default_override=None):
        key = field_key(field)
        if not key or key in seen:
            return
        seen.add(key)
        output.append(comfy_field_to_field(field, len(output), label_override, default_override))

    by_key = {field_key(field): field for field in comfy_fields}
    for switch in switch_entries:
        key = f"{switch['node_id']}.{switch['input']}"
        field = dict(
            by_key.get(key)
            or {
                "node": switch["node_id"],
                "input": switch["input"],
                "name": switch["name"],
                "nodeTitle": f"Input_{switch['name']}",
                "classType": "PrimitiveBoolean",
                "type": "boolean",
                "default": switch.get("default", False),
                "options": [],
            }
        )
        field["type"] = "boolean"
        add_field(field, switch["name"], switch.get("default", field.get("default", False)))

    for field in comfy_fields:
        add_field(field)

    return output, {
        "field_count": len(output),
        "candidate_count": len(comfy_fields),
        "switch_count": len(switch_entries),
    }


def convert_frontend_workflow(payload: RunningHubWorkflowConvertRequest) -> Dict[str, Any]:
    workflow = unwrap_workflow_object(payload.workflow)
    api_workflow = unwrap_workflow_object(payload.api_workflow)
    profile = str(payload.profile or "auto").strip().lower()
    if profile not in {"auto", "motiontransfer", "generic"}:
        profile = "auto"
    output_mode = str(payload.output_mode or "external").strip().lower()
    if output_mode not in {"external", "all", "main"}:
        output_mode = "external"
    main_output_id = str(payload.main_output_id or "312").strip() or "312"

    if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
        converter = comfy_workflows.load_comfy_export_converter()
        detected_profile = comfy_workflows.detect_comfy_export_profile(workflow, profile)
        try:
            source = json.loads(json.dumps(workflow, ensure_ascii=False))
            converted = converter.Workflow(source)
            widget_report = converter.normalize_legacy_widgets(converted)
            compatible_nodes_report = converter.replace_compatible_custom_nodes(converted)
            reroute_report = converter.strip_reroute_nodes(converted)
            flatten_report = converter.flatten_set_get(converted)
            frontend_switch_report = converter.convert_oct_posture_bypasser(converted)
            profile_mapping = converter.apply_motiontransfer_profile(converted) if detected_profile == "motiontransfer" else {"profile": detected_profile}
            keep_ids = converter.all_executable_nodes(converted) if output_mode in {"all", "external"} else converter.reachable_nodes(converted, main_output_id)
            pruned = converter.prune_workflow(converted, keep_ids)
            api_prompt = converter.build_api_prompt(pruned)
            body_ratio_widget_report = converter.apply_body_ratio_mapper_widget_values(pruned, api_prompt)
            overlay_report = {"updated": [], "skipped": []}
            if isinstance(api_workflow, dict) and comfy_workflows.is_api_prompt_workflow(api_workflow):
                overlay_report = converter.overlay_api_values(api_workflow, api_prompt)
            body_ratio_report = converter.repair_body_ratio_mapper_prompt(api_prompt)
            body_ratio_validation = converter.validate_body_ratio_mapper_prompt(api_prompt)
            if body_ratio_validation.get("issues"):
                raise ValueError(f"BodyRatioMapper API prompt validation failed: {body_ratio_validation['issues']}")
            mapping = {
                **profile_mapping,
                "main_output_node_id": str(main_output_id),
                "output_mode": output_mode,
                "workflow_output": None,
                "api_output": None,
                "api_input": "inline" if isinstance(api_workflow, dict) and comfy_workflows.is_api_prompt_workflow(api_workflow) else None,
                "normalize_legacy_widgets": widget_report,
                "compatible_custom_nodes": compatible_nodes_report,
                "strip_reroute_nodes": reroute_report,
                "flatten_set_get": flatten_report,
                "frontend_switches": frontend_switch_report,
                "body_ratio_mapper_widget_values": body_ratio_widget_report,
                "api_value_overlay": overlay_report,
                "body_ratio_mapper_api_repair": body_ratio_report,
                "body_ratio_mapper_api_validation": body_ratio_validation,
                "validation": converter.validate_workflow(pruned),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Frontend workflow conversion failed: {exc}") from exc
        output_fields, summary = all_fields_from_comfy_api_prompt(api_prompt, mapping)
        existing_keys = {f"{field.get('nodeId')}.{field.get('fieldName')}" for field in output_fields if isinstance(field, dict)}
        frontend_switch_fields = frontend.switch_fields(workflow, existing_keys)
        if frontend_switch_fields:
            frontend_switch_names = {
                frontend.switch_semantic_name(field.get("label") or field.get("nodeTitle"))
                for field in frontend_switch_fields
            }
            output_fields = [
                field for field in output_fields
                if not (
                    fields.clean_field_type(field.get("type")) in {"boolean", "dropdown"}
                    and frontend.switch_semantic_name(field.get("label") or field.get("nodeTitle")) in frontend_switch_names
                )
            ]
            output_fields = frontend.merge_fields_preserving_order(frontend_switch_fields, output_fields)
        frontend_node_ids = {str(node.get("id") or "") for node in frontend.workflow_nodes(workflow)}
        output_fields = frontend.dedupe_switch_fields(output_fields, frontend_node_ids)
        output_fields = fields.hide_video_loader_internal_fields(output_fields)
        all_field_count = len(output_fields)
        if output_mode == "external":
            output_fields = fields.external_input_fields(output_fields)
        summary.update({
            "mode": "frontend",
            "profile": detected_profile,
            "output_mode": output_mode,
            "workflow_output": None,
            "api_output": None,
            "mapping_output": None,
            "frontend_node_switch_count": len(frontend_switch_fields),
            "switch_count": int(summary.get("switch_count") or 0) + len(frontend_switch_fields),
            "field_count": len(output_fields),
            "all_field_count": all_field_count,
        })
        return {"fields": output_fields, "workflow": api_prompt, "mapping": mapping, "conversion": summary}

    frontend_nodes = frontend.workflow_nodes(workflow)
    if frontend_nodes:
        output_fields = frontend.merge_fields_preserving_order(
            frontend.switch_fields(workflow),
            extractors.fields_from_workflow_json(workflow),
        )
        output_fields = frontend.dedupe_switch_fields(output_fields, {frontend.node_id(node) for node in frontend_nodes})
        output_fields = fields.hide_video_loader_internal_fields(output_fields)
        all_field_count = len(output_fields)
        if output_mode == "external":
            output_fields = fields.external_input_fields(output_fields)
        return {
            "fields": output_fields,
            "workflow": workflow or {},
            "mapping": {},
            "conversion": {
                "mode": "frontend",
                "profile": "runninghub",
                "output_mode": "fields",
                "field_count": len(output_fields),
                "all_field_count": all_field_count,
                "candidate_count": len(frontend_nodes),
                "switch_count": len(frontend.switch_fields(workflow)),
                "frontend_node_switch_count": len(frontend.switch_fields(workflow)),
            },
        }

    source = api_workflow if isinstance(api_workflow, dict) else workflow
    if isinstance(source, dict) and comfy_workflows.is_api_prompt_workflow(source):
        output_fields, summary = fields_from_comfy_api_prompt(source, {})
        summary.update({"mode": "api", "profile": "api", "output_mode": "api"})
        return {"fields": output_fields, "workflow": source, "mapping": {}, "conversion": summary}
    output_fields = extractors.fields_from_workflow_json(source)
    return {
        "fields": output_fields,
        "workflow": source or {},
        "mapping": {},
        "conversion": {"mode": "raw", "field_count": len(output_fields), "candidate_count": len(output_fields), "switch_count": 0},
    }
