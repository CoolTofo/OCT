import os
from typing import Any, Dict


def ensure_runtime_config_files(api_env_file: str, data_dir: str) -> None:
    try:
        os.makedirs(os.path.dirname(api_env_file), exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        if not os.path.exists(api_env_file):
            with open(api_env_file, "a", encoding="utf-8"):
                pass
    except Exception as exc:
        print(f"Failed to initialize API config directory: {exc}")


def load_env_file(api_env_file: str) -> None:
    if not os.path.exists(api_env_file):
        return
    try:
        with open(api_env_file, "r", encoding="utf-8-sig") as f:
            for raw_line in f.read().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception as exc:
        print(f"Failed to load API/.env: {exc}")


def env_quote(value: Any) -> str:
    text = str(value or "")
    if not text or any(ch.isspace() for ch in text) or any(ch in text for ch in ['"', "'", "#"]):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def update_env_values(api_env_file: str, updates: Dict[str, Any], lock=None) -> None:
    os.makedirs(os.path.dirname(api_env_file), exist_ok=True)
    lines = []
    if os.path.exists(api_env_file):
        with open(api_env_file, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()

    def write_lines():
        seen = set()
        next_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                next_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in updates:
                value = str(updates[key] or "")
                if value:
                    next_lines.append(f"{key}={env_quote(value)}")
                seen.add(key)
            else:
                next_lines.append(line)
        for key, value in updates.items():
            if key in seen:
                continue
            value = str(value or "")
            if value:
                next_lines.append(f"{key}={env_quote(value)}")
        with open(api_env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(next_lines).rstrip() + ("\n" if next_lines else ""))
        for key, value in updates.items():
            os.environ[key] = str(value or "")

    if lock is None:
        write_lines()
    else:
        with lock:
            write_lines()
