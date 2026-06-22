import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.paths import BASE_DIR, DATA_DIR, WORKFLOW_DIR


BUILTIN_WORKFLOWS = {
    "Z-Image.json",
    "Z-Image-Enhance.json",
    "2511.json",
    "klein-enhance.json",
    "Flux2-Klein.json",
    "upscale.json",
    "MotionTransfer.json",
}
CUSTOM_WORKFLOW_FOLDER = "custom"
LEGACY_CUSTOM_WORKFLOW_FOLDER = "\u81ea\u5b9a\u4e49"
WORKFLOW_NAME_RE = re.compile(
    rf"^(?:(?:{CUSTOM_WORKFLOW_FOLDER}|{LEGACY_CUSTOM_WORKFLOW_FOLDER})/)?[a-zA-Z0-9_\u4e00-\u9fff.\-]+\.json$"
)

COMFY_EXPORT_TOOL_DIR = os.path.join(BASE_DIR, "tools", "comfyui_export")
COMFY_EXPORT_REPORT_DIR = os.path.join(DATA_DIR, "comfyui_exports")
_COMFY_EXPORT_CONVERTER = None
_COMFY_EXPORT_CONVERTER_MTIME = None


def workflow_path_from_name(name: str) -> str:
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    path = os.path.abspath(os.path.join(WORKFLOW_DIR, *name.split("/")))
    workflow_root = os.path.abspath(WORKFLOW_DIR)
    if os.path.commonpath([workflow_root, path]) != workflow_root:
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    return path


def workflow_config_path(name: str) -> str:
    return workflow_path_from_name(name).replace(".json", ".config.json")


def is_builtin_workflow(name: str) -> bool:
    return "/" not in name and os.path.basename(name) in BUILTIN_WORKFLOWS


def comfy_export_workflow_dir() -> str:
    local_dir = os.path.join(WORKFLOW_DIR, "comfyui_full")
    os.makedirs(local_dir, exist_ok=True)
    return os.path.abspath(local_dir)


def read_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def safe_comfy_export_path(path: str) -> str:
    if not path:
        raise HTTPException(status_code=400, detail="workflow_path is required")
    raw_path = os.path.abspath(path.strip().strip('"'))
    root = comfy_export_workflow_dir()
    try:
        inside_root = os.path.commonpath([root, raw_path]) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise HTTPException(status_code=400, detail="Workflow path must be inside the configured ComfyUI workflow folder")
    if not os.path.exists(raw_path):
        raise HTTPException(status_code=404, detail="ComfyUI workflow file not found")
    return raw_path


def safe_custom_workflow_filename(name: str, fallback: str) -> str:
    base = os.path.basename(str(name or fallback or "ComfyUI_api_fixed").strip().strip('"'))
    if base.lower().endswith(".json"):
        base = base[:-5]
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip("._-")
    if not base:
        base = "ComfyUI_api_fixed"
    return f"{base}.json"


def load_comfy_export_converter():
    global _COMFY_EXPORT_CONVERTER, _COMFY_EXPORT_CONVERTER_MTIME
    converter_path = os.path.join(COMFY_EXPORT_TOOL_DIR, "comfy_api_workflow_converter.py")
    if not os.path.exists(converter_path):
        raise HTTPException(status_code=404, detail=f"ComfyUI export converter not found: {converter_path}")
    converter_mtime = os.path.getmtime(converter_path)
    if _COMFY_EXPORT_CONVERTER is not None and _COMFY_EXPORT_CONVERTER_MTIME == converter_mtime:
        return _COMFY_EXPORT_CONVERTER
    if COMFY_EXPORT_TOOL_DIR not in sys.path:
        sys.path.insert(0, COMFY_EXPORT_TOOL_DIR)
    spec = importlib.util.spec_from_file_location("oct_comfy_api_workflow_converter", converter_path)
    if not spec or not spec.loader:
        raise HTTPException(status_code=500, detail="Failed to load ComfyUI export converter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _COMFY_EXPORT_CONVERTER = module
    _COMFY_EXPORT_CONVERTER_MTIME = converter_mtime
    return module


def is_full_comfy_workflow(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list)


def is_api_prompt_workflow(data: Any) -> bool:
    if not isinstance(data, dict) or "nodes" in data or not data:
        return False
    sample = next(iter(data.values()), None)
    return isinstance(sample, dict) and "class_type" in sample and "inputs" in sample


def detect_comfy_export_profile(workflow_data: Dict[str, Any], requested: str) -> str:
    requested = (requested or "auto").lower()
    if requested in {"motiontransfer", "generic"}:
        return requested
    node_types = {node.get("type") for node in workflow_data.get("nodes", []) if isinstance(node, dict)}
    motion_markers = {"WanVideoAnimateEmbeds", "WanVideoSamplerSettings", "BodyRatioMapperProportionTransfer"}
    return "motiontransfer" if motion_markers.issubset(node_types) else "generic"


def infer_workflow_field_type(value: Any, input_name: str, class_type: str = "") -> str:
    key = f"{input_name or ''} {class_type or ''}".lower()
    input_key = str(input_name or "").lower()
    class_key = str(class_type or "").lower()
    if input_key == "rgthree_comparer" or "image comparer" in class_key:
        return "ignored"
    if "layerutility: imagereel" in class_key and re.fullmatch(r"image\d+_text", input_key):
        return "ignored"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "slider" if re.search(r"strength|cfg|denoise|scale|weight|ratio|rate", key) else "number"
    if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
        return "dropdown"
    if re.search(r"(?:^|[_\-.])(text|prompt|caption|positive|negative)(?:$|[_\-.])", input_key):
        return "textarea"
    if re.search(r"\b(audio|sound|music|voice)\b|\.((mp3|wav|ogg|m4a|flac|aac|wma|opus|aiff|aif|amr))$", key):
        return "audio"
    if re.search(r"\b(video|movie)\b|\.((mp4|webm|mov|m4v|mkv|avi|wmv|flv|mpg|mpeg))$", key):
        return "video"
    if re.search(r"\b(image|img|mask|photo|picture)\b|\.((png|jpe?g|webp|gif|bmp))$", key):
        return "image"
    if re.search(r"prompt|text|caption|positive|negative", key) or len(str(value or "")) > 120:
        return "textarea"
    return "text"


def comfy_field_stable_key(field: Dict[str, Any]) -> str:
    return f"{field.get('node') or ''}.{field.get('input') or ''}"


def is_essential_comfy_field(field: Dict[str, Any]) -> bool:
    field_type = str(field.get("type") or "").lower()
    input_name = str(field.get("input") or "").lower()
    class_type = str(field.get("classType") or field.get("class_type") or "").lower()
    label = f"{field.get('name') or ''} {field.get('nodeTitle') or ''} {field.get('classType') or ''}".lower()
    if input_name in {"filename_prefix", "filename", "prefix"}:
        return False
    if field_type in {"image", "video", "audio"}:
        return True
    if class_type == "loadimage" and input_name == "image":
        return True
    if class_type in {"vhs_loadvideo", "loadvideo", "videoload"} and input_name == "video":
        return True
    if input_name in {"positive_prompt", "prompt", "text", "text1", "caption"} and re.search(r"textencode|prompt|caption|positive", label):
        return True
    return False


def lock_essential_comfy_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    locked = []
    for field in fields:
        item = dict(field)
        if is_essential_comfy_field(item):
            item["locked"] = True
        locked.append(item)
    return locked


def is_stale_locked_comfy_media_field(field: Dict[str, Any]) -> bool:
    field_type = str(field.get("type") or "").lower()
    return (
        field.get("locked") is True
        and field_type in {"image", "video", "audio"}
    )


def is_comfy_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and str(value[0]).isdigit()


def repair_comfy_workflow_config(workflow: Dict[str, Any], config: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    if not is_api_prompt_workflow(workflow):
        return config, False
    cfg = dict(config or {})
    current_fields = [dict(field) for field in (cfg.get("fields") or []) if isinstance(field, dict)]
    extracted = lock_essential_comfy_fields(extract_api_prompt_fields(workflow))
    essential_by_key = {
        comfy_field_stable_key(field): field
        for field in extracted
        if is_essential_comfy_field(field)
    }
    if not essential_by_key:
        cfg["fields"] = current_fields
        return cfg, False

    changed = False
    used_keys = set()
    repaired = []
    for field in current_fields:
        key = comfy_field_stable_key(field)
        essential = essential_by_key.get(key)
        if essential:
            used_keys.add(key)
            merged = {**essential, **field}
            if merged.get("type") != essential.get("type"):
                merged["type"] = essential.get("type")
            if merged.get("classType") != essential.get("classType"):
                merged["classType"] = essential.get("classType")
            if merged.get("nodeTitle") != essential.get("nodeTitle") and not merged.get("nodeTitle"):
                merged["nodeTitle"] = essential.get("nodeTitle")
            if merged.get("locked") is not True:
                merged["locked"] = True
                changed = True
            if merged != field:
                changed = True
            repaired.append(merged)
        else:
            if is_stale_locked_comfy_media_field(field):
                changed = True
                continue
            repaired.append(field)

    for key, field in essential_by_key.items():
        if key in used_keys:
            continue
        repaired.append(field)
        changed = True

    cfg["fields"] = repaired
    if "mini_cards" not in cfg or not isinstance(cfg.get("mini_cards"), dict):
        cfg["mini_cards"] = {}
    return cfg, changed


def extract_api_prompt_fields(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        class_type = str(node.get("class_type") or "")
        title = str((node.get("_meta") or {}).get("title") or class_type or f"Node {node_id}")
        for input_name, value in inputs.items():
            if is_comfy_link(value):
                continue
            if class_type == "LoadImage" and input_name == "upload":
                continue
            field_type = infer_workflow_field_type(value, input_name, class_type)
            if field_type == "ignored":
                continue
            options = [str(item) for item in value] if field_type == "dropdown" and isinstance(value, list) else []
            default_value = options[0] if options else ("" if isinstance(value, (dict, list)) else value)
            field: Dict[str, Any] = {
                "id": f"{node_id}.{input_name}",
                "node": str(node_id),
                "input": str(input_name),
                "name": f"{title} / {input_name}",
                "nodeTitle": title,
                "classType": class_type,
                "type": field_type,
                "default": default_value if default_value is not None else "",
                "options": options,
                "random_enabled": False,
                "locked": False,
            }
            if field_type in {"number", "slider"}:
                n = default_value if isinstance(default_value, (int, float)) and not isinstance(default_value, bool) else None
                field["min"] = 0
                field["max"] = max(float(n) * 2, 10) if isinstance(n, (int, float)) and n > 0 else 10
                field["step"] = 0.1 if isinstance(n, float) and 0 < abs(n) < 5 else 1
                if re.search(r"seed|noise", f"{input_name} {title}", re.I):
                    field["random_enabled"] = True
            fields.append(field)
    return fields


def motion_transfer_workflow_fields() -> List[Dict[str, Any]]:
    workflow_path = workflow_path_from_name("MotionTransfer.json")
    if not os.path.exists(workflow_path):
        raise HTTPException(status_code=404, detail="MotionTransfer.json workflow was not found.")
    workflow = read_json_file(workflow_path)

    fields = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        title = str((node.get("_meta") or {}).get("title") or "")
        prefix = "input" if title.lower().startswith("input") else "output" if title.lower().startswith("output") else ""
        if not prefix:
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        clean_title = re.sub(r"^(Input|Output)_?", "", title, flags=re.I).strip() or title
        editable_items = []
        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                continue
            field_type = "text"
            if isinstance(value, bool):
                field_type = "boolean"
            elif isinstance(value, int):
                field_type = "integer"
            elif isinstance(value, float):
                field_type = "number"
            elif input_name == "image":
                field_type = "image"
            elif input_name == "video":
                field_type = "video"
            editable_items.append({
                "id": f"{node_id}.{input_name}",
                "node": str(node_id),
                "input": input_name,
                "name": clean_title if len(inputs) == 1 else f"{clean_title} / {input_name}",
                "section": prefix,
                "type": field_type,
                "default": value,
                "class_type": node.get("class_type") or "",
                "title": title,
            })
        if not editable_items:
            fields.append({
                "id": f"{node_id}.__readonly",
                "node": str(node_id),
                "input": "",
                "name": clean_title,
                "section": prefix,
                "type": "readonly",
                "default": "",
                "class_type": node.get("class_type") or "",
                "title": title,
            })
        else:
            fields.extend(editable_items)
    return fields
