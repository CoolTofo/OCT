import json
import os
import time
from threading import Lock
from typing import Any, Callable, Dict, List


HISTORY_LOCK = Lock()


def save_record(history_file: str, record: Dict[str, Any], limit: int = 5000) -> None:
    with HISTORY_LOCK:
        history = []
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        if "timestamp" not in record:
            record["timestamp"] = time.time()
        history.insert(0, record)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history[:limit], f, ensure_ascii=False, indent=4)


def list_records(history_file: str, record_type: str | None = None) -> List[Dict[str, Any]]:
    if not os.path.exists(history_file):
        return []
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if record_type:
        data = [item for item in data if item.get("type", "zimage") == record_type]
    data = [
        item
        for item in data
        if (item.get("images") and len(item["images"]) > 0) or (item.get("videos") and len(item["videos"]) > 0)
    ]

    def sort_key(item):
        timestamp = item.get("timestamp", 0)
        try:
            return float(timestamp)
        except Exception:
            return 0

    return sorted(data, key=sort_key, reverse=True)


def delete_record(history_file: str, timestamp: float, output_file_from_url: Callable[[Any], str | None]) -> Dict[str, Any]:
    if not os.path.exists(history_file):
        return {"success": False, "message": "History file not found"}
    try:
        with HISTORY_LOCK:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            target_record = None
            new_history = []
            for item in history:
                is_match = False
                item_ts = item.get("timestamp", 0)
                if isinstance(timestamp, (int, float)) and isinstance(item_ts, (int, float)):
                    if abs(float(item_ts) - float(timestamp)) < 0.001:
                        is_match = True
                elif str(item_ts) == str(timestamp):
                    is_match = True
                if is_match:
                    target_record = item
                else:
                    new_history.append(item)
            if target_record:
                with open(history_file, "w", encoding="utf-8") as f:
                    json.dump(new_history, f, ensure_ascii=False, indent=4)

        if target_record:
            for media_url in [*target_record.get("images", []), *target_record.get("videos", [])]:
                file_path = output_file_from_url(media_url)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as exc:
                        print(f"Failed to delete file {file_path}: {exc}")
            return {"success": True}
        return {"success": False, "message": "Record not found"}
    except Exception as exc:
        print(f"Delete history error: {exc}")
        return {"success": False, "message": str(exc)}
