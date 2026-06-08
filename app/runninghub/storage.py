"""Persistence helpers for saved RunningHub workflow templates."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List


Normalizer = Callable[[Dict[str, Any]], Dict[str, Any]]


def load_workflows(path: str, normalize: Normalizer) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        items = data.get("workflows") if isinstance(data, dict) else data
        return [normalize(item) for item in (items or []) if isinstance(item, dict)]
    except Exception as exc:
        print(f"Failed to load RunningHub workflows: {exc}")
        return []


def save_workflows(path: str, data_dir: str, items: List[Dict[str, Any]], lock=None) -> None:
    os.makedirs(data_dir, exist_ok=True)

    def write() -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"workflows": items}, handle, ensure_ascii=False, indent=2)

    if lock is None:
        write()
        return
    with lock:
        write()

