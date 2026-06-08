"""Online image result assembly service."""

import asyncio
import re
import time
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from app.schemas import OnlineImageRequest

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)


async def build_online_image_result(payload: OnlineImageRequest):
    provider = get_api_provider(payload.provider_id)
    default_models = provider.get("image_models") or (
        HOLO_DEFAULT_IMAGE_MODELS if is_holo_provider(provider) else [IMAGE_MODEL]
    )
    default_model = default_models[0]
    model = selected_model(payload.model, default_model)
    refs = [ref.dict() for ref in payload.reference_images if ref.url]
    count = max(1, min(8, int(payload.n or 1)))
    try:
        if is_holo_provider(provider):
            image_items, raw = await generate_holo_images(
                payload.prompt, payload.size, model, refs, provider, count
            )
            local_urls = []
            for item in image_items:
                value = item.get("value") or item.get("url")
                if value:
                    local_urls.append(value)
        elif is_apimart_provider(provider) or is_t8api_provider(provider):
            image_items, raw = await generate_t8api_images(
                payload.prompt, payload.size, payload.quality, model, refs, provider, count
            )
            local_urls = []
            for image_data in image_items:
                local_urls.append(await save_ai_image_to_output(image_data, prefix="online_"))
        else:
            image_data, raw = await generate_ai_image(
                payload.prompt, payload.size, payload.quality, model, refs, provider["id"]
            )
            local_urls = [await save_ai_image_to_output(image_data, prefix="online_")]
    except httpx.HTTPStatusError as exc:
        text = exc.response.text or ""
        friendly = _friendly_image_error(text, payload.size, model)
        detail = friendly or f"Upstream image generation API error: {text[:300]}"
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to request upstream image generation API: {exc}",
        ) from exc

    task_ids = raw.get("task_ids") if isinstance(raw, dict) and isinstance(raw.get("task_ids"), list) else []
    raw_primary = (
        raw.get("raws", [{}])[0]
        if isinstance(raw, dict) and isinstance(raw.get("raws"), list) and raw.get("raws")
        else raw
    )
    result = {
        "prompt": payload.prompt,
        "images": local_urls,
        "timestamp": time.time(),
        "type": "online",
        "model": model,
        "provider_id": provider["id"],
        "provider_name": provider.get("name") or provider["id"],
        "task_id": task_ids[0] if task_ids else (extract_task_id(raw) if isinstance(raw, dict) else None),
        "task_ids": task_ids,
        "request_id": raw_primary.get("id") if isinstance(raw_primary, dict) else None,
        "params": {
            "provider_id": provider["id"],
            "model": model,
            "size": payload.size,
            "quality": payload.quality,
            "n": count if (is_apimart_provider(provider) or is_t8api_provider(provider) or is_holo_provider(provider)) else 1,
            "reference_images": refs,
        },
        "raw_usage": raw_primary.get("usage") if isinstance(raw_primary, dict) else None,
    }
    save_to_history(result)
    loop = get_global_loop()
    if loop:
        asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), loop)
    return result


def _friendly_image_error(text: str, size: str, model: str) -> str | None:
    match = re.search(r"longest edge must be less than or equal to (\d+)", text)
    if match:
        limit = match.group(1)
        return (
            "This model does not support the current resolution: "
            f"longest side exceeds {limit}px. Reduce the image resolution or choose a high-resolution model."
        )
    if "Invalid size" in text or "invalid_value" in text:
        return f"This model does not support the current size: {size}. Try another resolution or model."
    if "rate limit" in text.lower() or "429" in text:
        return "Requests are too frequent and were rate limited upstream. Try again later."
    if "Unauthorized" in text or "401" in text:
        return "The API key is invalid or expired. Check it in API settings."
    if "model_not_found" in text or "channel not found" in text:
        return (
            f"The upstream platform has no available route for model {model}. "
            "The model may not be enabled for this account. Choose an enabled model."
        )
    return None
