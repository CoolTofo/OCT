import os
import re
from typing import Dict, List

import requests


DEFAULT_DISCOVERY_PORTS = [
    int(p) for p in os.getenv("COMFYUI_DISCOVERY_PORTS", "8188,8001,8002,8003,8004,8005,8006,8007,8008,8009,8010").split(",")
    if p.strip().isdigit()
]


def normalize_address(addr: str) -> str:
    s = str(addr or "").strip()
    s = re.sub(r"^https?://", "", s)
    return s.rstrip("/")


def is_reachable(addr: str, timeout: float = 0.8) -> bool:
    try:
        response = requests.get(f"http://{addr}/queue", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def discover_local_instances(configured: List[str], ports: List[int] | None = None) -> List[str]:
    candidates = []
    for addr in configured:
        addr = normalize_address(addr)
        if addr and addr not in candidates:
            candidates.append(addr)
    for port in ports or DEFAULT_DISCOVERY_PORTS:
        addr = f"127.0.0.1:{port}"
        if addr not in candidates:
            candidates.append(addr)
    return [addr for addr in candidates if is_reachable(addr)]


def active_instances(configured: List[str], backend_load: Dict[str, int], lock=None) -> List[str]:
    active = discover_local_instances(configured)
    if active:
        if lock is None:
            for addr in active:
                backend_load.setdefault(addr, 0)
        else:
            with lock:
                for addr in active:
                    backend_load.setdefault(addr, 0)
    return active or configured


def validate_instances(items: List[str]) -> List[str]:
    cleaned = []
    for item in items:
        s = normalize_address(item)
        if not s:
            continue
        if ":" not in s:
            raise ValueError(f"Address is missing a port: {item} (expected host:port, e.g. 127.0.0.1:8188)")
        host, _, port = s.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"Invalid address: {item} (expected host:port, e.g. 127.0.0.1:8188)")
        if s in cleaned:
            continue
        cleaned.append(s)
    if not cleaned:
        raise ValueError("Keep at least one ComfyUI backend address.")
    return cleaned


def reset_backend_load(cleaned: List[str], current_load: Dict[str, int] | None = None) -> Dict[str, int]:
    new_load = {addr: 0 for addr in cleaned}
    for addr, count in (current_load or {}).items():
        if addr in new_load:
            new_load[addr] = count
    return new_load
