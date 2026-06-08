"""Shared filesystem paths used by the OCT Studio server."""

import os
from pathlib import Path


BASE_DIR = str(Path(__file__).resolve().parents[1])

WORKFLOW_DIR = os.path.join(BASE_DIR, "workflows")
WORKFLOW_PATH = os.path.join(WORKFLOW_DIR, "Z-Image.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_INPUT_DIR = os.path.join(ASSETS_DIR, "input")
OUTPUT_OUTPUT_DIR = os.path.join(ASSETS_DIR, "output")
ASSET_LIBRARY_DIR = os.path.join(ASSETS_DIR, "library")

HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
API_DIR = os.path.join(BASE_DIR, "API")
API_ENV_FILE = os.path.join(API_DIR, ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
CONVERSATION_DIR = os.path.join(DATA_DIR, "conversations")
CANVAS_DIR = os.path.join(DATA_DIR, "canvases")
ASSET_LIBRARY_PATH = os.path.join(DATA_DIR, "asset_library.json")
API_PROVIDERS_FILE = os.path.join(DATA_DIR, "api_providers.json")
RUNNINGHUB_WORKFLOWS_FILE = os.path.join(DATA_DIR, "runninghub_workflows.json")
GLOBAL_CONFIG_FILE = os.path.join(BASE_DIR, "global_config.json")

RUNTIME_DIRS = (
    OUTPUT_DIR,
    ASSETS_DIR,
    OUTPUT_INPUT_DIR,
    OUTPUT_OUTPUT_DIR,
    ASSET_LIBRARY_DIR,
    STATIC_DIR,
    WORKFLOW_DIR,
    CONVERSATION_DIR,
    CANVAS_DIR,
)


def ensure_runtime_dirs() -> None:
    """Create directories expected to exist before routes are mounted."""
    for path in RUNTIME_DIRS:
        os.makedirs(path, exist_ok=True)

