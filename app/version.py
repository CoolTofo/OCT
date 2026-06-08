import os

from app.paths import BASE_DIR


APP_VERSION = "2026.05.19"


def current_version() -> str:
    version_file = os.path.join(BASE_DIR, "VERSION")
    try:
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                return (f.read().strip().splitlines() or [APP_VERSION])[0].strip() or APP_VERSION
    except Exception:
        pass
    return APP_VERSION
