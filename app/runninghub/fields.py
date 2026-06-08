"""Pure RunningHub field normalization and filtering helpers.

This module is intentionally independent from FastAPI and storage. Route code
can import these helpers without pulling in the whole application.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


VIDEO_LOADER_INTERNAL_FIELDS = {
    "force_rate",
    "force_size",
    "custom_width",
    "custom_height",
    "frame_load_cap",
    "skip_first_frames",
    "select_every_nth",
    "format",
}


def clean_field_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "str": "text",
        "string": "text",
        "int": "integer",
        "float": "number",
        "double": "number",
        "bool": "boolean",
        "file": "text",
    }
    text = aliases.get(text, text)
    if text in {"text", "textarea", "number", "integer", "boolean", "image", "video", "audio", "json", "dropdown"}:
        return text
    return "text"


def repair_text(value: str) -> str:
    if not isinstance(value, str) or not value:
        return value

    def score(text: str) -> int:
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        controls = sum(1 for ch in text if "\u0080" <= ch <= "\u009f")
        replacement = text.count("\ufffd")
        mojibake_marks = len(re.findall(r"[\u8119\u8117]|[\u5fd9\u83bd\u6c13\u732b\u8305][\x80-\xff]?", text))
        return cjk * 4 - controls * 3 - replacement * 6 - mojibake_marks

    best = value
    best_score = score(value)
    for encoding in ("latin1", "cp1252"):
        try:
            candidate = value.encode(encoding).decode("utf-8")
        except Exception:
            continue
        candidate_score = score(candidate)
        if candidate_score > best_score:
            best = candidate
            best_score = candidate_score
    return best


def repair_mojibake(value: Any) -> Any:
    if isinstance(value, str):
        return repair_text(value)
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    return value


def first_text(raw: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = repair_text(str(value)).strip()
        if text:
            return text
    return ""


def normalize_field(raw: Dict[str, Any] | None, fallback_index: int = 0) -> Dict[str, Any]:
    raw = raw or {}
    node_id = str(raw.get("nodeId") or raw.get("node_id") or raw.get("node") or "").strip()
    node_title = first_text(raw, "nodeTitle", "node_title", "nodeName", "node_name", "nodeLabel", "node_label", "title")
    class_type = first_text(raw, "classType", "class_type")
    field_name = first_text(raw, "fieldName", "field_name", "input")
    field_id = str(raw.get("id") or "").strip()
    if not field_id:
        base = f"{node_id}.{field_name}" if node_id and field_name else f"field_{fallback_index + 1}"
        field_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", base)[:80] or f"field_{fallback_index + 1}"
    options = raw.get("options") if isinstance(raw.get("options"), list) else []
    label_base = first_text(raw, "label", "fieldLabel", "field_label", "fieldTitle", "field_title", "displayName", "display_name", "name")
    if not label_base and node_title and field_name:
        label_base = f"{node_title} / {field_name}"
    elif not label_base and field_name:
        label_base = f"{class_type} / {field_name}" if class_type else field_name
    return {
        "id": field_id,
        "label": str(label_base or field_id).strip()[:120],
        "nodeId": node_id[:80],
        "nodeTitle": node_title[:120],
        "classType": class_type[:120],
        "fieldName": field_name[:120],
        "type": clean_field_type(raw.get("type") or raw.get("fieldType")),
        "default": repair_mojibake(raw.get("default", raw.get("fieldValue", ""))),
        "required": bool(raw.get("required", False)),
        "accept": str(raw.get("accept") or "").strip()[:120],
        "options": [str(item) for item in options if str(item).strip()][:200],
    }


def field_key(field: Dict[str, Any]) -> str:
    return f"{field.get('nodeId') or field.get('node') or ''}.{field.get('fieldName') or field.get('input') or ''}"


def scalar_switch_value(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)) and value in (0, 1):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "false", "yes", "no", "on", "off", "0", "1"}
    return False


def switch_type_and_options(value: Any) -> tuple[str, List[str]]:
    if isinstance(value, bool):
        return "boolean", []
    text = str(value).strip().lower()
    if text in {"yes", "no"}:
        return "dropdown", [text] + [item for item in ["yes", "no"] if item != text]
    if text in {"on", "off"}:
        return "dropdown", [text] + [item for item in ["on", "off"] if item != text]
    if text in {"true", "false"}:
        return "dropdown", [text] + [item for item in ["true", "false"] if item != text]
    if text in {"0", "1"}:
        return "dropdown", [text] + [item for item in ["0", "1"] if item != text]
    return "boolean", []


def shellagent_accept(field_type: str) -> str:
    return {"image": "image/*", "video": "video/*", "audio": "audio/*"}.get(field_type, "")


def shellagent_options(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:200]
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[\n,|]+", text)
    return [part.strip() for part in parts if part.strip()][:200]


def video_loader_internal_field(field: Dict[str, Any]) -> bool:
    field_name = str((field or {}).get("fieldName") or "").strip().lower()
    if field_name not in VIDEO_LOADER_INTERNAL_FIELDS:
        return False
    text = f"{(field or {}).get('label') or ''} {(field or {}).get('nodeTitle') or ''} {(field or {}).get('classType') or ''}".lower()
    return "vhs_loadvideo" in text or "load video" in text or "loadvideo" in text


def video_upload_field_from_sample(sample: Dict[str, Any], fallback_index: int = 0) -> Dict[str, Any]:
    node_id = str((sample or {}).get("nodeId") or "").strip()
    node_title = str((sample or {}).get("nodeTitle") or "").strip() or "Load Video"
    label_base = re.sub(
        r"\s*/\s*(force_rate|force_size|custom_width|custom_height|frame_load_cap|skip_first_frames|select_every_nth|format)\s*$",
        "",
        str((sample or {}).get("label") or node_title),
        flags=re.I,
    ).strip()
    if not label_base:
        label_base = node_title
    return normalize_field(
        {
            "id": f"{node_id}.video" if node_id else f"video_{fallback_index}",
            "label": f"{label_base} / video",
            "nodeId": node_id,
            "nodeTitle": node_title,
            "classType": (sample or {}).get("classType") or "",
            "fieldName": "video",
            "type": "video",
            "default": "",
            "required": False,
            "accept": "video/*",
            "options": [],
        },
        fallback_index,
    )


def hide_video_loader_internal_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = list(fields or [])
    explicit_video_node_ids = {
        str(field.get("nodeId") or "")
        for field in fields
        if clean_field_type(field.get("type")) == "video"
        and str(field.get("fieldName") or "").strip().lower() == "video"
    }
    internal_samples: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        node_id = str(field.get("nodeId") or "")
        if node_id and video_loader_internal_field(field):
            internal_samples.setdefault(node_id, field)
    video_loader_node_ids = explicit_video_node_ids | set(internal_samples.keys())
    if not video_loader_node_ids:
        return fields

    output: List[Dict[str, Any]] = []
    inserted_upload_nodes = set()
    for field in fields:
        node_id = str(field.get("nodeId") or "")
        field_name = str(field.get("fieldName") or "").strip().lower()
        if node_id not in video_loader_node_ids:
            output.append(field)
            continue
        if field_name == "video":
            output.append(field)
            inserted_upload_nodes.add(node_id)
            continue
        if node_id not in explicit_video_node_ids and node_id not in inserted_upload_nodes and video_loader_internal_field(field):
            output.append(video_upload_field_from_sample(field, len(output)))
            inserted_upload_nodes.add(node_id)
        if not video_loader_internal_field(field):
            output.append(field)
    return output


def external_input_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()
    for field in fields or []:
        field_type = clean_field_type(field.get("type"))
        field_name = str(field.get("fieldName") or "").strip().lower()
        text = f"{field.get('label') or ''} {field.get('nodeTitle') or ''} {field.get('classType') or ''}".lower()
        default_text = str(field.get("default") or "").strip().lower()
        is_named_external_input = (
            "octinput" in text
            or re.search(r"(^|[\s/_-])oct[_-]", text, re.I) is not None
            or re.search(r"(^|[\s/_-])(input|get|set)[_-]", text, re.I) is not None
        )
        is_group_switch = (
            "fast groups bypasser" in text
            or "opt_connection" in text
            or "boolean primitive" in text
            or "primitiveboolean" in text
            or "switch" in text
            or "toggle" in text
        ) and field_type in {"boolean", "dropdown"}
        is_video_upload = field_type == "video" and field_name == "video"
        is_other_media_upload = (
            field_type in {"image", "audio"}
            and field_name in {"image", "audio"}
            and (
                default_text in {"", "none", "null"}
                or re.search(r"upload", text, re.I)
            )
        )
        if not (is_named_external_input or is_group_switch or is_video_upload or is_other_media_upload):
            continue
        key = field_key({"node": field.get("nodeId"), "input": field.get("fieldName")})
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(field)
    return output or fields


def coerce_value(value: Any, field: Dict[str, Any] | None) -> Any:
    field_type = clean_field_type((field or {}).get("type"))
    if value is None or value == "":
        return (field or {}).get("default", "")
    if field_type == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if field_type == "integer":
        try:
            return int(float(value))
        except Exception:
            return value
    if field_type == "number":
        try:
            numeric = float(value)
            return int(numeric) if numeric.is_integer() else numeric
        except Exception:
            return value
    if field_type == "json" and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value
