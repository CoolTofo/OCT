"""RunningHub response parsing helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .fields import repair_text


def task_status_from_legacy(raw: Dict[str, Any]) -> str:
    code = raw.get("code") if isinstance(raw, dict) else None
    if code == 0 and raw.get("data"):
        return "SUCCESS"
    if code in {804, 813}:
        return "RUNNING" if code == 804 else "QUEUED"
    if code and code != 0:
        return "FAILED"
    return "RUNNING"


def task_status(raw: Dict[str, Any], fallback: str = "RUNNING") -> str:
    if not isinstance(raw, dict):
        return fallback
    status = str(raw.get("status") or raw.get("taskStatus") or "").strip().upper()
    if status:
        return status
    error_code = str(raw.get("errorCode") or raw.get("error_code") or "").strip()
    error_message = str(raw.get("errorMessage") or raw.get("error_message") or raw.get("message") or raw.get("msg") or "").strip()
    if error_code and error_code not in {"0", "NONE", "NULL"}:
        return "FAILED"
    code = raw.get("code")
    if code not in (None, "", 0, "0"):
        return "FAILED"
    if error_message:
        return "FAILED"
    return fallback


def error_message(raw: Any) -> str:
    if not isinstance(raw, dict):
        return str(raw)
    parts: List[str] = []

    def add(value: Any) -> None:
        if value in (None, ""):
            return
        text = repair_text(str(value)).strip()
        if text and text not in parts:
            parts.append(text)

    add(raw.get("errorMessage") or raw.get("msg") or raw.get("message"))
    error_code = raw.get("errorCode") or raw.get("error_code") or raw.get("code")
    if error_code not in (None, "", 0, "0"):
        add(f"errorCode={error_code}")
    failed = raw.get("failedReason") or raw.get("failed_reason")
    if isinstance(failed, dict):
        node_name = failed.get("node_name") or failed.get("nodeName") or ""
        node_id = failed.get("node_id") or failed.get("nodeId") or ""
        exception_message = failed.get("exception_message") or failed.get("message") or ""
        prefix = f"{node_name or 'node'} {node_id}".strip()
        if exception_message:
            add(f"{prefix}: {exception_message}" if prefix else exception_message)
        traceback = failed.get("traceback")
        if isinstance(traceback, str):
            trace_text = traceback.strip()
            try:
                parsed_trace = json.loads(trace_text)
                if isinstance(parsed_trace, list):
                    trace_text = "; ".join(str(item) for item in parsed_trace if item)
            except Exception:
                pass
            add(trace_text[:500])
        elif isinstance(traceback, list):
            add("; ".join(str(item) for item in traceback if item)[:500])
    return "; ".join(parts) or str(raw)


def response_json(resp: Any) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"code": resp.status_code, "msg": (resp.text or "")[:500]}


def result_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    results = raw.get("results")
    if isinstance(results, list):
        return [
            {
                "url": item.get("url") or item.get("fileUrl") or item.get("download_url") or "",
                "nodeId": item.get("nodeId") or item.get("node_id") or "",
                "outputType": item.get("outputType") or item.get("fileType") or item.get("type") or "",
                "text": item.get("text"),
            }
            for item in results
            if isinstance(item, dict)
        ]
    data = raw.get("data")
    if isinstance(data, list):
        return [
            {
                "url": item.get("fileUrl") or item.get("url") or item.get("download_url") or "",
                "nodeId": item.get("nodeId") or item.get("node_id") or "",
                "outputType": item.get("fileType") or item.get("outputType") or item.get("type") or "",
                "text": item.get("text"),
            }
            for item in data
            if isinstance(item, dict)
        ]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return result_items(data)
    return []


def api_error_text(raw: Any, fallback: str = "RunningHub request failed") -> str:
    if isinstance(raw, dict):
        for key in ("message", "msg", "errorMessage", "error", "detail"):
            value = raw.get(key)
            if value not in (None, ""):
                return repair_text(str(value)).strip()
        safe = {key: value for key, value in raw.items() if key not in {"data", "prompt"}}
        if safe:
            return json.dumps(safe, ensure_ascii=False)[:500]
    text = repair_text(str(raw or "")).strip()
    return text or fallback
