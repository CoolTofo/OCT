"""Small service facade for RunningHub workflow parameter handling.

The route layer can depend on this module while the implementation underneath
keeps growing into smaller files.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List

from . import fields


def normalize_field(raw: Dict[str, Any] | None, fallback_index: int = 0) -> Dict[str, Any]:
    return fields.normalize_field(raw, fallback_index)


def normalize_fields(raw_fields: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    normalized = [
        fields.normalize_field(field, index)
        for index, field in enumerate(raw_fields or [])
        if isinstance(field, dict)
    ]
    return fields.hide_video_loader_internal_fields(normalized)


def normalize_workflow(raw: Dict[str, Any], now_ms: int | None = None) -> Dict[str, Any]:
    raw = raw or {}
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    workflow_id = str(raw.get("workflowId") or raw.get("workflow_id") or "").strip()
    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        item_id = f"rh_{uuid.uuid4().hex[:12]}"
    retain = raw.get("defaultRetainSeconds", raw.get("default_retain_seconds", 0))
    try:
        retain = int(retain or 0)
    except Exception:
        retain = 0
    if retain and not 10 <= retain <= 180:
        retain = 0
    title = re.sub(
        r"\s+",
        " ",
        str(raw.get("title") or raw.get("name") or "RunningHub Workflow").strip(),
    )[:120] or "RunningHub Workflow"
    return {
        "id": item_id[:80],
        "title": title,
        "workflowId": workflow_id[:80],
        "accessPassword": str(raw.get("accessPassword") or raw.get("access_password") or "").strip()[:200],
        "defaultRetainSeconds": retain,
        "fields": normalize_fields(raw.get("fields") or []),
        "options": raw.get("options") if isinstance(raw.get("options"), dict) else {},
        "created_at": int(raw.get("created_at") or now),
        "updated_at": int(raw.get("updated_at") or now),
    }


def field_key(field: Dict[str, Any]) -> str:
    return fields.field_key(field)


def field_key_set(raw_fields: List[Dict[str, Any]] | None) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for field in raw_fields or []:
        if not isinstance(field, dict):
            continue
        node_id = str(field.get("nodeId") or field.get("node_id") or field.get("node") or "").strip()
        field_name = str(field.get("fieldName") or field.get("field_name") or field.get("input") or "").strip()
        if node_id and field_name:
            keys.add((node_id, field_name))
    return keys


def filter_node_info_by_fields(node_info: List[Dict[str, Any]] | None, raw_fields: List[Dict[str, Any]] | None) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    allowed = field_key_set(raw_fields)
    if not allowed:
        return list(node_info or []), []
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for item in node_info or []:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("nodeId") or item.get("node_id") or "").strip(),
            str(item.get("fieldName") or item.get("field_name") or "").strip(),
        )
        if key in allowed:
            kept.append(item)
        else:
            dropped.append(item)
    return kept, dropped


def is_unresolved_string_format_placeholder(value: Any, field: Dict[str, Any] | None) -> bool:
    field = field or {}
    class_type = str(field.get("classType") or field.get("class_type") or "").strip().lower()
    field_name = str(field.get("fieldName") or field.get("field_name") or "").strip().lower()
    if "stringformat" not in class_type or field_name not in {"f_string", "format", "text"}:
        return False
    text = str(value or "").strip()
    default = str(field.get("default", "") or "").strip()
    if default and text != default:
        return False
    return re.fullmatch(r"\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}", text) is not None


def coerce_value(value: Any, field: Dict[str, Any] | None, use_default_for_empty: bool = True) -> Any:
    if is_unresolved_string_format_placeholder(value, field):
        return ""
    if value == "" and not use_default_for_empty:
        return ""
    return fields.coerce_value(value, field)
