"""Configured API provider runtime helpers."""

import os
from typing import Any, Dict

from fastapi import HTTPException

from app import env_config
from app import providers as provider_utils
from app import provider_store

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

def provider_runtime_context():
    return {
        "modelscope_chat_base_url": MODELSCOPE_CHAT_BASE_URL,
        "modelscope_image_models": MODELSCOPE_IMAGE_MODELS,
        "modelscope_chat_models": MODELSCOPE_CHAT_MODELS,
        "modelscope_video_models": MODELSCOPE_VIDEO_MODELS,
        "modelscope_default_image_models": MODELSCOPE_DEFAULT_IMAGE_MODELS,
        "modelscope_default_chat_models": MODELSCOPE_DEFAULT_CHAT_MODELS,
        "modelscope_default_loras": MODELSCOPE_DEFAULT_LORAS,
        "modelscope_defaults_version": MODELSCOPE_DEFAULTS_VERSION,
        "holo_default_image_models": HOLO_DEFAULT_IMAGE_MODELS,
        "holo_default_video_models": HOLO_DEFAULT_VIDEO_MODELS,
        "seedance_default_base_url": SEEDANCE_DEFAULT_BASE_URL,
        "seedance_default_video_models": SEEDANCE_DEFAULT_VIDEO_MODELS,
        "volc_visual_default_base_url": VOLC_VISUAL_DEFAULT_BASE_URL,
        "volc_visual_motion_model": VOLC_VISUAL_MOTION_MODEL,
        "runninghub_default_base_url": RUNNINGHUB_DEFAULT_BASE_URL,
    }


def default_api_providers():
    return provider_store.default_api_providers(provider_runtime_context())

def merge_default_api_providers(providers):
    return provider_store.merge_default_api_providers(providers, provider_runtime_context())

def normalize_model_list(values):
    return model_list_from_values(values)

def model_list_from_values(values):
    return provider_utils.model_list_from_values(values)

def normalize_ms_loras(values):
    return provider_utils.normalize_ms_loras(values)

def normalize_endpoint_override(value, label):
    try:
        return provider_utils.normalize_endpoint_override(value, label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def provider_endpoint_url(provider, key, default_path):
    return provider_utils.provider_endpoint_url(provider, key, default_path, AI_BASE_URL)

def normalize_provider(item):
    try:
        return provider_store.normalize_provider(item, provider_runtime_context())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def load_api_providers():
    return provider_store.load_api_providers(API_PROVIDERS_FILE, provider_runtime_context())

def save_api_providers(providers):
    return provider_store.save_api_providers(API_PROVIDERS_FILE, DATA_DIR, providers, GLOBAL_CONFIG_LOCK)

def public_provider(provider):
    return provider_utils.public_provider(provider)

def get_primary_provider_id(providers=None):
    """Return the active default provider id."""
    providers = providers if providers is not None else load_api_providers()
    return provider_store.get_primary_provider_id(providers)

def get_api_provider(provider_id="comfly"):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    # Keep compatibility with old hard-coded provider IDs by falling back to primary.
    if not target or not any(p["id"] == target for p in providers):
        target = get_primary_provider_id(providers)
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"API provider not found: {target}")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API provider is disabled: {provider.get('name') or target}")
    return provider

def get_api_provider_exact(provider_id: str):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"API provider not found: {target or '(empty)'}. Save the provider first or use the current form values.")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API provider is disabled: {provider.get('name') or target}")
    return provider

def env_quote(value):
    return env_config.env_quote(value)

def update_env_values(updates):
    return env_config.update_env_values(API_ENV_FILE, updates, GLOBAL_CONFIG_LOCK)

def resolve_chat_provider(provider: str, model: str, ms_model: str):
    if provider == "modelscope":
        if not MODELSCOPE_API_KEY:
            raise HTTPException(status_code=400, detail="MODELSCOPE_API_KEY is not configured. Set it in API/.env.")
        base = MODELSCOPE_CHAT_BASE_URL
        hdrs = {"Authorization": f"Bearer {MODELSCOPE_API_KEY}", "Content-Type": "application/json"}
        mdl = selected_model(ms_model or model, MODELSCOPE_CHAT_MODELS[0] if MODELSCOPE_CHAT_MODELS else "MiniMax/MiniMax-M2.7")
        return base, hdrs, mdl
    api_provider = get_api_provider(provider or "")
    base_root = (api_provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if not base_root:
        raise HTTPException(status_code=400, detail=f"{api_provider.get('name') or api_provider['id']} Base URL is not configured.")
    base = base_root if base_root.endswith("/v1") else base_root + "/v1"
    hdrs = api_headers(provider=api_provider)
    default_model = (api_provider.get("chat_models") or [CHAT_MODEL])[0]
    mdl = selected_model(model, default_model)
    return base, hdrs, mdl

def api_headers(json_body=True, provider=None):
    if provider:
        key_env = provider_key_env(provider["id"])
        api_key = os.getenv(key_env, "")
        provider_name = provider.get("name") or provider["id"]
        if not api_key:
            raise HTTPException(status_code=400, detail=f"{provider_name} API key is not configured. Set it in API provider settings.")
    else:
        api_key = AI_API_KEY
        if not api_key:
            raise HTTPException(status_code=400, detail="COMFLY_API_KEY is not configured. Set it in API/.env.")
    if provider and provider_protocol(provider) == "gemini":
        headers = {"Accept": "application/json", "x-goog-api-key": api_key}
    else:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

def provider_protocol(provider):
    return str((provider or {}).get("protocol") or "openai").strip().lower()

def provider_holo_hint(provider):
    return provider_utils.holo_hint(provider)


def provider_seedance_hint(provider):
    return provider_utils.seedance_hint(provider)


def provider_volc_visual_hint(provider):
    return provider_utils.volc_visual_hint(provider)


def provider_runninghub_hint(provider):
    return provider_utils.runninghub_hint(provider)


def is_apimart_provider(provider):
    base_url = str((provider or {}).get("base_url") or "").lower()
    return provider_protocol(provider) == "apimart" or "apimart.ai" in base_url

def is_gemini_provider(provider):
    return provider_protocol(provider) == "gemini"

def is_holo_provider(provider):
    return provider_holo_hint(provider)


def is_seedance_provider(provider):
    return provider_seedance_hint(provider)


def is_volc_visual_provider(provider):
    return provider_volc_visual_hint(provider)


def is_runninghub_provider(provider):
    return provider_runninghub_hint(provider)

