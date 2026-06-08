import json
import urllib.parse
import urllib.request
from typing import Dict, List

import requests


def check_images_exist(backend_addr: str, images: List[str] | None) -> bool:
    if not images:
        return True
    for img in images:
        try:
            url = f"http://{backend_addr}/view?filename={urllib.parse.quote(img)}&type=input"
            response = requests.get(url, stream=True, timeout=0.5)
            response.close()
            if response.status_code != 200:
                return False
        except Exception:
            return False
    return True


def select_best_backend(
    active_instances: List[str],
    backend_local_load: Dict[str, int],
    load_lock,
    required_images: List[str] | None = None,
) -> str:
    best_backend = active_instances[0]
    min_queue_size = float("inf")
    candidates_with_images = []
    candidates_others = []
    backend_stats = {}

    for addr in active_instances:
        try:
            with urllib.request.urlopen(f"http://{addr}/queue", timeout=1) as response:
                data = json.loads(response.read())
                remote_load = len(data.get("queue_running", [])) + len(data.get("queue_pending", []))
                with load_lock:
                    local_load = backend_local_load.get(addr, 0)
                effective_load = max(remote_load, local_load)
                has_images = check_images_exist(addr, required_images)
                backend_stats[addr] = {"load": effective_load, "has_images": has_images}
                if has_images:
                    candidates_with_images.append(addr)
                else:
                    candidates_others.append(addr)
        except Exception as exc:
            print(f"Backend {addr} unreachable: {exc}")
            continue

    target_candidates = candidates_with_images if candidates_with_images else candidates_others
    if not target_candidates:
        if candidates_others:
            target_candidates = candidates_others
        else:
            return active_instances[0]

    for addr in target_candidates:
        load = backend_stats[addr]["load"]
        if load < min_queue_size:
            min_queue_size = load
            best_backend = addr

    return best_backend
