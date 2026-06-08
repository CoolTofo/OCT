import json
import os
import re
import time
import uuid
from threading import Lock
from typing import Any, Dict

from fastapi import HTTPException

from app.paths import CANVAS_DIR, CONVERSATION_DIR


CANVAS_TRASH_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
CONVERSATION_LOCK = Lock()
CANVAS_LOCK = Lock()


def now_ms() -> int:
    return int(time.time() * 1000)


def safe_user_id(user_id, request):
    candidate = (user_id or "").strip()
    if not candidate and getattr(request, "client", None):
        candidate = f"ip-{request.client.host}"
    if not candidate:
        candidate = "anonymous"
    candidate = re.sub(r"[^a-zA-Z0-9_.-]", "-", candidate)[:80].strip(".-")
    return candidate or "anonymous"


def user_dir(user_id: str) -> str:
    path = os.path.join(CONVERSATION_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def conversation_path(user_id: str, conversation_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", conversation_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid conversation ID.")
    return os.path.join(user_dir(user_id), f"{cleaned}.json")


def save_conversation(user_id: str, conversation: Dict[str, Any]) -> None:
    with CONVERSATION_LOCK:
        path = conversation_path(user_id, conversation["id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(conversation, f, ensure_ascii=False, indent=2)


def new_conversation(user_id: str, title: str = "\u65b0\u5bf9\u8bdd") -> Dict[str, Any]:
    timestamp = now_ms()
    conversation = {
        "id": uuid.uuid4().hex,
        "title": (title or "\u65b0\u5bf9\u8bdd")[:80],
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": [],
    }
    save_conversation(user_id, conversation)
    return conversation


def load_conversation(user_id: str, conversation_id: str) -> Dict[str, Any]:
    path = conversation_path(user_id, conversation_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Conversation was not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_conversations(user_id: str):
    records = []
    directory = user_dir(user_id)
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        messages = data.get("messages", [])
        last_message = next((m for m in reversed(messages) if m.get("role") != "system"), None)
        records.append({
            "id": data.get("id"),
            "title": data.get("title", "\u65b0\u5bf9\u8bdd"),
            "created_at": data.get("created_at", 0),
            "updated_at": data.get("updated_at", 0),
            "last_message": (last_message or {}).get("content", ""),
        })
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)


def canvas_path(canvas_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", canvas_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid canvas ID.")
    return os.path.join(CANVAS_DIR, f"{cleaned}.json")


def write_canvas_file(canvas: Dict[str, Any]) -> None:
    with CANVAS_LOCK:
        with open(canvas_path(canvas["id"]), "w", encoding="utf-8") as f:
            json.dump(canvas, f, ensure_ascii=False, indent=2)


def save_canvas(canvas: Dict[str, Any]) -> None:
    canvas["updated_at"] = now_ms()
    write_canvas_file(canvas)


def is_unresumable_runninghub_pending(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict) or item.get("canvasTaskId"):
        return False
    run = item.get("run")
    if not isinstance(run, dict) or run.get("nodeType") != "rh":
        return False
    request = run.get("request")
    if not isinstance(request, dict):
        return True
    task_id = request.get("task_id") or request.get("taskId")
    return not str(task_id or "").strip()


def prune_unresumable_runninghub_pending(canvas: Dict[str, Any]) -> bool:
    nodes = canvas.get("nodes")
    if not isinstance(nodes, list):
        return False
    changed = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        pending = node.get("_pending")
        if not isinstance(pending, list) or not pending:
            continue
        kept = [item for item in pending if not is_unresumable_runninghub_pending(item)]
        if len(kept) == len(pending):
            continue
        node["_pending"] = kept
        if not kept and node.get("runStatus") == "running":
            node["runStatus"] = "failed"
            node["runError"] = "RunningHub task was interrupted: missing task_id. Please run it again."
        changed = True
    return changed


def normalize_canvas_kind(kind: str = "classic") -> str:
    return "smart" if str(kind or "").strip().lower() == "smart" else "classic"


def new_canvas(title: str = "\u672a\u547d\u540d\u753b\u5e03", icon: str = "layers", kind: str = "classic") -> Dict[str, Any]:
    timestamp = now_ms()
    canvas_kind = normalize_canvas_kind(kind)
    canvas = {
        "id": uuid.uuid4().hex,
        "title": (title or ("\u667a\u80fd\u753b\u5e03" if canvas_kind == "smart" else "\u672a\u547d\u540d\u753b\u5e03"))[:80],
        "icon": (icon or ("sparkles" if canvas_kind == "smart" else "layers"))[:32],
        "kind": canvas_kind,
        "created_at": timestamp,
        "updated_at": timestamp,
        "nodes": [],
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    save_canvas(canvas)
    return canvas


def load_canvas(canvas_id: str) -> Dict[str, Any]:
    path = canvas_path(canvas_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Canvas was not found.")
    with open(path, "r", encoding="utf-8") as f:
        canvas = json.load(f)
    if canvas.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Canvas is in trash.")
    if prune_unresumable_runninghub_pending(canvas):
        write_canvas_file(canvas)
    return canvas


def load_canvas_any(canvas_id: str) -> Dict[str, Any]:
    path = canvas_path(canvas_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Canvas was not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def canvas_record(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": data.get("id"),
        "title": data.get("title", "\u672a\u547d\u540d\u753b\u5e03"),
        "icon": data.get("icon", "layers"),
        "kind": normalize_canvas_kind(data.get("kind")),
        "created_at": data.get("created_at", 0),
        "updated_at": data.get("updated_at", 0),
        "deleted_at": data.get("deleted_at", 0),
        "node_count": len(data.get("nodes", [])),
    }


def cleanup_expired_canvas_trash() -> None:
    cutoff = now_ms() - CANVAS_TRASH_RETENTION_MS
    with CANVAS_LOCK:
        for filename in os.listdir(CANVAS_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(CANVAS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                deleted_at = int(data.get("deleted_at") or 0)
                if deleted_at and deleted_at < cutoff:
                    os.remove(path)
            except Exception:
                continue


def iter_canvas_records(include_deleted: bool = False):
    cleanup_expired_canvas_trash()
    records = []
    for filename in os.listdir(CANVAS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(CANVAS_DIR, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        is_deleted = bool(data.get("deleted_at"))
        if include_deleted != is_deleted:
            continue
        records.append(canvas_record(data))
    return records


def list_canvases():
    records = iter_canvas_records(include_deleted=False)
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)


def list_deleted_canvases():
    records = iter_canvas_records(include_deleted=True)
    return sorted(records, key=lambda item: item["deleted_at"], reverse=True)


def display_title(text: str) -> str:
    title = re.sub(r"\s+", " ", text or "").strip()
    return title[:24] or "\u65b0\u5bf9\u8bdd"
