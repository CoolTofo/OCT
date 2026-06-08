from threading import Lock
from typing import Dict, List


class TaskQueue:
    def __init__(self) -> None:
        self._items: List[Dict[str, object]] = []
        self._lock = Lock()
        self._next_task_id = 1

    def enqueue(self, client_id: str) -> Dict[str, object]:
        with self._lock:
            task_id = self._next_task_id
            self._next_task_id += 1
            item = {"task_id": task_id, "client_id": client_id}
            self._items.append(item)
            return item

    def remove(self, item: Dict[str, object] | None) -> None:
        if not item:
            return
        with self._lock:
            if item in self._items:
                self._items.remove(item)

    def status_for_client(self, client_id: str) -> Dict[str, int]:
        with self._lock:
            total = len(self._items)
            positions = [i + 1 for i, task in enumerate(self._items) if task.get("client_id") == client_id]
            position = positions[0] if positions else 0
        return {"total": total, "position": position}

    def snapshot(self) -> List[Dict[str, object]]:
        with self._lock:
            return [dict(item) for item in self._items]
