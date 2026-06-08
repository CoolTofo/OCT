import json
import os
from typing import Callable, List

from fastapi import APIRouter, HTTPException

from app.schemas import ApiProviderPayload


def create_router(
    *,
    get_context: Callable[[], dict],
    load_api_providers,
    public_provider,
    normalize_provider,
    provider_key_env,
    save_api_providers,
    update_env_values,
    reload_env_globals,
    discover_local_comfyui_instances,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config")
    async def ai_config():
        ctx = get_context()
        chat_models = ctx["CHAT_MODELS"]
        preferred_chat_model = next((m for m in chat_models if m == "gpt-5.5"), chat_models[0] if chat_models else ctx["CHAT_MODEL"])
        providers = [public_provider(p) for p in load_api_providers()]
        return {
            "base_url": ctx["AI_BASE_URL"],
            "chat_model": preferred_chat_model,
            "image_model": ctx["IMAGE_MODEL"],
            "chat_models": chat_models,
            "image_models": ctx["IMAGE_MODELS"],
            "video_models": ctx["VIDEO_MODELS"],
            "comfy_instances": ctx["COMFYUI_INSTANCES"],
            "active_comfy_instances": discover_local_comfyui_instances(),
            "api_providers": providers,
            "has_api_key": bool(ctx["AI_API_KEY"]),
            "ms_chat_models": ctx["MODELSCOPE_CHAT_MODELS"],
            "has_ms_key": bool(ctx["MODELSCOPE_API_KEY"]),
        }

    @router.get("/api/models")
    async def ai_models():
        ctx = get_context()
        return {
            "chat_models": ctx["CHAT_MODELS"],
            "image_models": ctx["IMAGE_MODELS"],
            "video_models": ctx["VIDEO_MODELS"],
        }

    @router.get("/api/providers")
    async def api_providers():
        return {"providers": [public_provider(p) for p in load_api_providers()]}

    @router.put("/api/providers")
    async def save_providers(payload: List[ApiProviderPayload]):
        providers = []
        env_updates = {}
        raw_primary_flags = [bool(getattr(item, "primary", False)) for item in payload]
        for item in payload:
            provider = normalize_provider(item.dict(exclude={"api_key"}))
            if any(existing["id"] == provider["id"] for existing in providers):
                raise HTTPException(status_code=400, detail=f"Duplicate API provider ID: {provider['id']}")
            providers.append(provider)
            key_env = provider_key_env(provider["id"])
            if item.clear_key:
                env_updates[key_env] = ""
            elif item.api_key is not None and item.api_key.strip():
                env_updates[key_env] = item.api_key.strip()
            if provider["id"] == "comfly":
                env_updates["COMFLY_BASE_URL"] = provider["base_url"]
                env_updates["IMAGE_MODELS"] = ",".join(provider["image_models"])
                env_updates["CHAT_MODELS"] = ",".join(provider["chat_models"])
                env_updates["VIDEO_MODELS"] = ",".join(provider.get("video_models") or [])
            if provider["id"] == "modelscope":
                env_updates["MODELSCOPE_BASE_URL"] = provider["base_url"]
                env_updates["MODELSCOPE_IMAGE_MODELS"] = ",".join(provider["image_models"])
                env_updates["MODELSCOPE_CHAT_MODELS"] = ",".join(provider["chat_models"])
                env_updates["MODELSCOPE_VIDEO_MODELS"] = ",".join(provider.get("video_models") or [])
        if not providers:
            raise HTTPException(status_code=400, detail="Keep at least one API provider.")
        primary_indices = [i for i, flag in enumerate(raw_primary_flags) if flag]
        if primary_indices:
            winner = primary_indices[-1]
            for i, provider in enumerate(providers):
                provider["primary"] = i == winner
        save_api_providers(providers)
        if env_updates:
            update_env_values(env_updates)
            reload_env_globals()
        return {"providers": [public_provider(p) for p in providers]}

    @router.get("/api/config/token")
    async def get_global_token():
        ctx = get_context()
        if ctx["MODELSCOPE_API_KEY"]:
            return {"token": ctx["MODELSCOPE_API_KEY"]}
        global_config_file = ctx["GLOBAL_CONFIG_FILE"]
        if os.path.exists(global_config_file):
            try:
                with open(global_config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return {"token": config.get("modelscope_token", "")}
            except Exception:
                pass
        return {"token": ""}

    return router
