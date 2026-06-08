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


def coerce_value(value: Any, field: Dict[str, Any] | None) -> Any:
    return fields.coerce_value(value, field)
