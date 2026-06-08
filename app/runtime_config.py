"""Environment-backed runtime settings for the application."""

import os
from typing import Any, Dict

from app import providers as provider_utils
from app.runninghub import client as rh_client


MODELSCOPE_DEFAULT_IMAGE_MODELS = [
    "Tongyi-MAI/Z-Image-Turbo",
    "Qwen/Qwen-Image-2512",
    "Qwen/Qwen-Image-Edit-2511",
    "black-forest-labs/FLUX.2-klein-9B",
]

MODELSCOPE_DEFAULT_CHAT_MODELS = [
    "Qwen/Qwen3-235B-A22B",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "MiniMax/MiniMax-M2.7:MiniMax",
]

MODELSCOPE_DEFAULT_LORAS = [
    {
        "id": "Daniel8152/film",
        "name": "Z-Image Film",
        "target_model": "Tongyi-MAI/Z-Image-Turbo",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Qwen-Image-2512-Film",
        "name": "Qwen Image 2512 Film",
        "target_model": "Qwen/Qwen-Image-2512",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Klein-enhance",
        "name": "Klein enhance",
        "target_model": "black-forest-labs/FLUX.2-klein-9B",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
]

MODELSCOPE_DEFAULTS_VERSION = 3

DEFAULT_CHAT_MODELS = [
    "gpt-4o-mini",
    "gemini-3.1-flash-image-preview-2k",
]

DEFAULT_IMAGE_MODELS = ["nano-banana-pro"]

DEFAULT_VIDEO_MODELS = [
    "veo2",
    "veo2-fast",
    "veo2-pro",
    "veo3",
    "veo3-fast",
    "veo3-pro",
    "veo3.1",
    "veo3.1-fast",
    "veo3.1-quality",
    "veo3.1-lite",
    "sora-2",
    "sora-2-pro",
    "wan2.6-t2v",
    "wan2.6-i2v",
    "wan2.5-t2v-preview",
    "wan2.5-i2v-preview",
    "wan2.2-t2v-plus",
    "wan2.2-i2v-plus",
    "wan2.2-i2v-flash",
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-lite-t2v-250428",
    "doubao-seedance-1-0-lite-i2v-250428",
]

HOLO_DEFAULT_IMAGE_MODELS = ["gemini-3.0-pro-image-landscape"]
HOLO_DEFAULT_VIDEO_MODELS = ["Sora-2-12"]
SEEDANCE_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
SEEDANCE_DEFAULT_VIDEO_MODELS = [
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
]
VOLC_VISUAL_DEFAULT_BASE_URL = "https://visual.volcengineapi.com"
VOLC_VISUAL_MOTION_MODEL = "jimeng_dreamactor_m20_gen_video"
RUNNINGHUB_DEFAULT_BASE_URL = rh_client.DEFAULT_BASE_URL


def _configured_list(env_name: str) -> list[str]:
    return [item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()]


def _merged_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in items if item]))


def model_list(env_name: str, primary: str, defaults: list[str]) -> list[str]:
    return provider_utils.model_list_from_env(env_name, primary, defaults)


def load_settings() -> Dict[str, Any]:
    modelscope_image_models = _merged_unique([
        *MODELSCOPE_DEFAULT_IMAGE_MODELS,
        *_configured_list("MODELSCOPE_IMAGE_MODELS"),
    ])
    modelscope_chat_models = _merged_unique([
        *MODELSCOPE_DEFAULT_CHAT_MODELS,
        *_configured_list("MODELSCOPE_CHAT_MODELS"),
    ])
    modelscope_video_models = _merged_unique(_configured_list("MODELSCOPE_VIDEO_MODELS"))
    ai_request_timeout = float(os.getenv("REQUEST_TIMEOUT", "1800"))
    return {
        "AI_BASE_URL": os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/"),
        "AI_API_KEY": os.getenv("COMFLY_API_KEY", ""),
        "MODELSCOPE_API_KEY": os.getenv("MODELSCOPE_API_KEY", ""),
        "MODELSCOPE_CHAT_BASE_URL": os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1").rstrip("/"),
        "MODELSCOPE_DEFAULT_IMAGE_MODELS": MODELSCOPE_DEFAULT_IMAGE_MODELS,
        "MODELSCOPE_DEFAULT_CHAT_MODELS": MODELSCOPE_DEFAULT_CHAT_MODELS,
        "MODELSCOPE_IMAGE_MODELS": modelscope_image_models,
        "MODELSCOPE_CHAT_MODELS": modelscope_chat_models,
        "MODELSCOPE_VIDEO_MODELS": modelscope_video_models,
        "MODELSCOPE_DEFAULT_IMAGE_MODEL": (
            modelscope_image_models[0] if modelscope_image_models else MODELSCOPE_DEFAULT_IMAGE_MODELS[0]
        ),
        "MODELSCOPE_DEFAULT_CHAT_MODEL": "Qwen/Qwen3-235B-A22B",
        "MODELSCOPE_DEFAULT_LORAS": MODELSCOPE_DEFAULT_LORAS,
        "MODELSCOPE_DEFAULTS_VERSION": MODELSCOPE_DEFAULTS_VERSION,
        "CHAT_MODEL": os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        "IMAGE_MODEL": os.getenv("IMAGE_MODEL", "gpt-image-2"),
        "SYSTEM_PROMPT": os.getenv("SYSTEM_PROMPT", "You are a helpful assistant."),
        "MAX_HISTORY_MESSAGES": int(os.getenv("MAX_HISTORY_MESSAGES", "30")),
        "AI_REQUEST_TIMEOUT": ai_request_timeout,
        "IMAGE_POLL_INTERVAL": float(os.getenv("IMAGE_POLL_INTERVAL", "2")),
        "IMAGE_TASK_TIMEOUT": float(os.getenv("IMAGE_TASK_TIMEOUT", str(ai_request_timeout))),
        "COMFYUI_HISTORY_TIMEOUT": int(float(os.getenv("COMFYUI_HISTORY_TIMEOUT", "1800"))),
        "APIMART_IMAGE_TASK_TIMEOUT": float(os.getenv("APIMART_IMAGE_TASK_TIMEOUT", "1800")),
        "APIMART_IMAGE_POLL_INTERVAL": float(os.getenv("APIMART_IMAGE_POLL_INTERVAL", "5")),
        "APIMART_IMAGE_INITIAL_POLL_DELAY": float(os.getenv("APIMART_IMAGE_INITIAL_POLL_DELAY", "10")),
        "VIDEO_POLL_TIMEOUT": float(os.getenv("VIDEO_POLL_TIMEOUT", "1800")),
        "CHAT_MODELS": model_list("CHAT_MODELS", os.getenv("CHAT_MODEL", "gpt-4o-mini"), DEFAULT_CHAT_MODELS),
        "IMAGE_MODELS": model_list("IMAGE_MODELS", os.getenv("IMAGE_MODEL", "gpt-image-2"), DEFAULT_IMAGE_MODELS),
        "VIDEO_MODELS": model_list("VIDEO_MODELS", "veo3-fast", DEFAULT_VIDEO_MODELS),
        "HOLO_DEFAULT_IMAGE_MODELS": HOLO_DEFAULT_IMAGE_MODELS,
        "HOLO_DEFAULT_VIDEO_MODELS": HOLO_DEFAULT_VIDEO_MODELS,
        "SEEDANCE_DEFAULT_BASE_URL": SEEDANCE_DEFAULT_BASE_URL,
        "SEEDANCE_DEFAULT_VIDEO_MODELS": SEEDANCE_DEFAULT_VIDEO_MODELS,
        "VOLC_VISUAL_DEFAULT_BASE_URL": VOLC_VISUAL_DEFAULT_BASE_URL,
        "VOLC_VISUAL_MOTION_MODEL": VOLC_VISUAL_MOTION_MODEL,
        "RUNNINGHUB_DEFAULT_BASE_URL": RUNNINGHUB_DEFAULT_BASE_URL,
        "MOTION_TRANSFER_PUBLIC_BASE_URL": os.getenv(
            "MOTION_TRANSFER_PUBLIC_BASE_URL",
            os.getenv("PUBLIC_BASE_URL", ""),
        ).strip().rstrip("/"),
        "PUBLIC_UPLOAD_ENDPOINT": os.getenv(
            "PUBLIC_UPLOAD_ENDPOINT",
            os.getenv("CLOUD_UPLOAD_ENDPOINT", "https://cloudspace-245757829522.us-west1.run.app/api/upload"),
        ).strip(),
    }
