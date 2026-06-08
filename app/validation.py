"""Shared request validation helpers.

Keep this module free of FastAPI route state so validation logic can be reused
by providers, canvas tools, and future feature modules.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import HTTPException


FIELD_LABELS = {
    "prompt": "prompt",
    "message": "message",
    "system_prompt": "system prompt",
}


def friendly_validation_error(errors: List[Dict[str, Any]] | None) -> str:
    parts: List[str] = []
    for err in errors or []:
        loc = [str(item) for item in err.get("loc", []) if item != "body"]
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, field or "request parameter")
        ctx = err.get("ctx") or {}
        limit = ctx.get("limit_value") or ctx.get("max_length") or ctx.get("min_length")
        err_type = str(err.get("type") or "")
        msg = str(err.get("msg") or "")
        if "max_length" in err_type or "at most" in msg:
            parts.append(f"{label} is too long; it exceeds the backend limit of {limit} characters.")
        elif "min_length" in err_type:
            parts.append(f"{label} cannot be empty.")
        else:
            parts.append(f"{label} is invalid: {msg}")
    return "\n".join(parts) or "Invalid request parameters."


def selected_model(requested: str | None, fallback: str) -> str:
    model = (requested or fallback).strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name cannot be empty.")
    if len(model) > 240 or any(ord(ch) < 32 or ord(ch) == 127 for ch in model):
        raise HTTPException(status_code=400, detail=f"Invalid model name: {model}")
    return model


def modelscope_size(value: Any, fallback: str = "1024x1024") -> str:
    size = str(value or fallback).strip().lower().replace("*", "x")
    if re.fullmatch(r"\d{2,5}x\d{2,5}", size):
        return size
    raise HTTPException(
        status_code=400,
        detail=f"Invalid ModelScope size: {value or fallback}; expected WxH, e.g. 1024x1024.",
    )
