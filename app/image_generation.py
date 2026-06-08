"""Online image generation strategy helpers."""

import asyncio
import os
import re
import time
import urllib.parse
from typing import Any, Dict

import httpx
from fastapi import HTTPException

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

async def wait_for_image_task(client, task_id, provider=None):
    base_url = (provider.get("base_url") if provider else AI_BASE_URL).rstrip("/")
    is_apimart = is_apimart_provider(provider)
    is_async_image_provider = is_apimart or is_t8api_provider(provider)
    if is_apimart:
        task_url = f"{base_url}/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/tasks/{task_id}"
    elif is_async_image_provider:
        task_url = f"{base_url}/images/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/images/tasks/{task_id}"
    else:
        task_url = f"{base_url}/images/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/images/tasks/{task_id}"
    timeout = APIMART_IMAGE_TASK_TIMEOUT if is_async_image_provider else IMAGE_TASK_TIMEOUT
    interval = APIMART_IMAGE_POLL_INTERVAL if is_async_image_provider else IMAGE_POLL_INTERVAL
    initial_delay = APIMART_IMAGE_INITIAL_POLL_DELAY if is_async_image_provider else 0
    deadline = time.monotonic() + timeout
    last_payload = {}
    while time.monotonic() < deadline:
        if initial_delay:
            await asyncio.sleep(min(initial_delay, max(0.0, deadline - time.monotonic())))
            initial_delay = 0
            if time.monotonic() >= deadline:
                break
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        last_payload = response.json()
        task_data = last_payload.get("data") if isinstance(last_payload.get("data"), dict) else last_payload
        status = str(task_data.get("status") or task_data.get("task_status") or "").upper()
        if status in {"SUCCESS", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE", "DONE", "FINISHED", "OK", "READY"}:
            try:
                extract_images(last_payload)
            except HTTPException:
                await asyncio.sleep(min(interval, max(0.0, deadline - time.monotonic())))
                continue
            return last_payload
        if status in {"FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED", "CANCELED", "CANCELLED", "TIMEOUT", "REJECTED", "EXPIRED"}:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("fail_reason") or task_data.get("message") or error.get("message") or last_payload.get("message") or "image generation task failed"
            raise HTTPException(status_code=502, detail=f"Image generation task failed: {reason}")
        await asyncio.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raise HTTPException(status_code=504, detail=f"Image generation task timed out after {int(timeout)} seconds: task_id={task_id}")

# Media storage, asset library, preview, and public upload helpers live in app.media_store.


def parse_size_pair(size):
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", str(size or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))

GPT_IMAGE2_MAX_EDGE = 3840
GPT_IMAGE2_MAX_PIXELS = 8_294_400
GPT_IMAGE2_MIN_PIXELS = 655_360

def is_gpt_image_2_model(model):
    return str(model or "").strip().lower() == "gpt-image-2"

def is_t8api_provider(provider):
    provider = provider or {}
    base_url = str(provider.get("base_url") or "").lower()
    name = str(provider.get("name") or provider.get("id") or "").lower()
    return "t8star.org" in base_url or "t8api" in name

def normalize_gpt_image_2_size(size):
    width, height = parse_size_pair(size)
    if not width or not height:
        return size or "auto"
    if width == height and (width > 2048 or width * height > 4_194_304):
        return "3840x2160"
    ratio = width / height
    if ratio > 3:
        width = height * 3
    elif ratio < 1 / 3:
        height = width * 3
    scale = min(
        1.0,
        GPT_IMAGE2_MAX_EDGE / max(width, height),
        (GPT_IMAGE2_MAX_PIXELS / max(1, width * height)) ** 0.5,
    )
    width = max(16, int((width * scale) // 16) * 16)
    height = max(16, int((height * scale) // 16) * 16)
    if width * height < GPT_IMAGE2_MIN_PIXELS:
        grow = (GPT_IMAGE2_MIN_PIXELS / max(1, width * height)) ** 0.5
        width = int((width * grow + 15) // 16) * 16
        height = int((height * grow + 15) // 16) * 16
    return f"{width}x{height}"

def apimart_size_resolution(size):
    width, height = parse_size_pair(size)
    if not width or not height:
        raw = str(size or "").strip().lower()
        if raw in {"1k", "2k", "4k"}:
            return "1:1", raw
        if re.fullmatch(r"(auto|\d+\s*:\s*\d+)", raw):
            return raw.replace(" ", ""), "1k"
        return "1:1", "1k"
    long_edge = max(width, height)
    pixels = width * height
    if long_edge >= 3000 or pixels > 4_500_000:
        resolution = "4k"
    elif long_edge >= 1800 or pixels > 1_800_000:
        resolution = "2k"
    else:
        resolution = "1k"
    common = [
        (1, 1, "1:1"), (3, 2, "3:2"), (2, 3, "2:3"), (4, 3, "4:3"), (3, 4, "3:4"),
        (5, 4, "5:4"), (4, 5, "4:5"), (16, 9, "16:9"), (9, 16, "9:16"),
        (2, 1, "2:1"), (1, 2, "1:2"), (3, 1, "3:1"), (1, 3, "1:3"),
        (21, 9, "21:9"), (9, 21, "9:21"),
    ]
    ratio = width / height
    best = min(common, key=lambda item: abs(ratio - item[0] / item[1]))
    return best[2], resolution

async def generate_modelscope_provider_image(prompt, size, model, reference_images=None, provider=None):
    clean_token = MODELSCOPE_API_KEY.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="ModelScope API key is not configured. Set it in API settings.")
    width, height = parse_size_pair(size)
    refs = []
    for ref in (reference_images or [])[:4]:
        if not ref.get("url"):
            continue
        # Compress reference images into data URLs to keep payloads bounded.
        refs.append(modelscope_image_url(ref.get("url", ""), max_size=1536))
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true",
    }
    payload = {
        "model": selected_model(model, "Tongyi-MAI/Z-Image-Turbo"),
        "prompt": prompt.strip(),
    }
    if width and height:
        payload["width"] = width
        payload["height"] = height
        payload["size"] = f"{width}x{height}"
    if refs:
        payload["image_url"] = refs

    base_root = ((provider or {}).get("base_url") or MODELSCOPE_CHAT_BASE_URL).rstrip("/")
    api_root = base_root if base_root.endswith("/v1") else f"{base_root}/v1"
    async with httpx.AsyncClient(timeout=AI_REQUEST_TIMEOUT) as client:
        submit_res = await client.post(f"{api_root}/images/generations", headers=headers, json=payload)
        submit_res.raise_for_status()
        raw = submit_res.json()
        task_id = raw.get("task_id")
        if not task_id:
            try:
                return extract_image(raw), raw
            except HTTPException:
                raise HTTPException(status_code=502, detail=f"ModelScope did not return task_id: {raw}")

        deadline = time.monotonic() + AI_REQUEST_TIMEOUT
        last_payload = raw
        while time.monotonic() < deadline:
            await asyncio.sleep(IMAGE_POLL_INTERVAL)
            result = await client.get(
                f"{api_root}/tasks/{task_id}",
                headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
            )
            result.raise_for_status()
            data = result.json()
            last_payload = data
            status = str(data.get("task_status") or "").upper()
            if status == "SUCCEED":
                images = data.get("output_images") or []
                if not images:
                    raise HTTPException(status_code=502, detail=f"ModelScope succeeded but returned no images: {data}")
                return {"type": "url", "value": images[0]}, data
            if status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}:
                detail = data.get("error_info") or data.get("message") or data.get("detail") or str(data)
                raise HTTPException(status_code=502, detail=f"ModelScope task failed: {detail}")
        raise HTTPException(status_code=504, detail=f"ModelScope image task timed out: {last_payload}")

def gemini_model_name(model):
    value = selected_model(model, "gemini-3-pro-image-preview").strip()
    return value[len("models/"):] if value.startswith("models/") else value

def gemini_endpoint_url(provider, model):
    model_name = urllib.parse.quote(gemini_model_name(model), safe="")
    return provider_endpoint_url(provider, "image_generation_endpoint", f"/v1beta/models/{model_name}:generateContent")

def gemini_image_config(size):
    width, height = parse_size_pair(size)
    if not width or not height:
        raw = str(size or "").strip().upper()
        if raw in {"1K", "2K", "4K"}:
            return {"aspectRatio": "1:1", "imageSize": raw}
        if re.fullmatch(r"\d+\s*:\s*\d+", raw):
            return {"aspectRatio": raw.replace(" ", ""), "imageSize": "1K"}
        return {"aspectRatio": "1:1", "imageSize": "2K"}
    aspect_ratio, resolution = apimart_size_resolution(size)
    return {"aspectRatio": aspect_ratio, "imageSize": resolution.upper()}

def gemini_reference_part(ref):
    value = reference_to_data_url(ref, max_size=1536)
    if not value:
        return None
    if isinstance(value, str) and value.startswith("data:image/") and ";base64," in value:
        header, encoded = value.split(";base64,", 1)
        mime_type = header.replace("data:", "", 1) or "image/png"
        return {"inlineData": {"mimeType": mime_type, "data": encoded}}
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return {"fileData": {"mimeType": "image/png", "fileUri": value}}
    return None

async def generate_gemini_provider_image(prompt, size, model, reference_images=None, provider=None):
    model_name = gemini_model_name(model)
    endpoint = gemini_endpoint_url(provider, model_name)
    parts = [{"text": prompt.strip()}]
    for ref in (reference_images or [])[:16]:
        part = gemini_reference_part(ref)
        if part:
            parts.append(part)
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": gemini_image_config(size),
        },
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=1800.0, write=120.0, pool=20.0)) as client:
        response = await client.post(endpoint, headers=api_headers(provider=provider), json=body)
        response.raise_for_status()
        raw = response.json()
        return extract_image(raw), raw

async def generate_t8api_images(prompt, size, quality, model, reference_images=None, provider=None, n=1):
    count = max(1, min(8, int(n or 1)))
    quality = str(quality or "").strip().lower()
    if quality not in {"low", "medium", "high"}:
        quality = ""
    is_apimart = is_apimart_provider(provider)
    gen_url = provider_endpoint_url(provider, "image_generation_endpoint", "/v1/images/generations")
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    request_timeout = httpx.Timeout(connect=20.0, read=1800.0, write=120.0, pool=20.0)
    task_ids = []
    raws = []

    async def image_payload_for_refs(client):
        if is_apimart:
            urls = []
            errors = []
            for ref in refs[:16]:
                uploaded = await upload_image_for_apimart(client, provider, ref.get("url"))
                if valid_apimart_video_image_input(uploaded):
                    urls.append(uploaded)
                elif uploaded:
                    errors.append(uploaded[4:] if str(uploaded).startswith("ERR:") else str(uploaded))
            if refs and not urls:
                reason = errors[0] if errors else "APIMart image upload returned no usable URL"
                raise HTTPException(status_code=400, detail=f"APIMart reference image upload failed: {reason}")
            return urls
        image_payload = [reference_to_data_url(ref, max_size=1536) for ref in refs[:16]]
        return [value for value in image_payload if value]

    def make_body(batch_count, image_payload):
        body_size = normalize_gpt_image_2_size(size) if is_gpt_image_2_model(model) else size
        body = {
            "model": model,
            "prompt": prompt,
            "size": body_size,
        }
        if is_apimart:
            aspect_ratio, resolution = apimart_size_resolution(body_size)
            body["size"] = aspect_ratio
            body["resolution"] = resolution
            body["response_format"] = "url"
        if quality:
            body["quality"] = quality
        if image_payload:
            body["image_urls" if is_apimart else "image"] = image_payload
        if not is_gpt_image_2_model(model):
            body["n"] = batch_count
        return body

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        image_payload = await image_payload_for_refs(client)

        async def submit_and_wait(batch_count):
            params = None if is_apimart else {"async": "true"}
            response = await client.post(
                gen_url,
                headers=api_headers(provider=provider),
                params=params,
                json=make_body(batch_count, image_payload),
            )
            response.raise_for_status()
            raw = response.json()
            task_id = extract_task_id(raw)
            if not task_id:
                images = extract_images(raw)
                return images, raw, None
            task_ids.append(task_id)
            task_result = await wait_for_image_task(client, task_id, provider)
            return extract_images(task_result), task_result, task_id

        images, raw, _ = await submit_and_wait(1 if is_gpt_image_2_model(model) else count)
        raws.append(raw)
        all_images = list(images)
        while len(all_images) < count:
            images, raw, _ = await submit_and_wait(1)
            raws.append(raw)
            all_images.extend(images)
        return all_images[:count], {"task_ids": task_ids, "raws": raws}

async def generate_holo_images(prompt, size, model, reference_images=None, provider=None, n=1):
    if not provider:
        raise HTTPException(status_code=400, detail="HOLO API provider is not specified.")
    count = max(1, min(8, int(n or 1)))
    model = selected_model(model, HOLO_DEFAULT_IMAGE_MODELS[0])
    body_base = {
        "model": model,
        "messages": build_holo_messages(prompt, reference_images),
    }
    if size:
        body_base["size"] = str(size).strip()
    submit_url = holo_api_url(provider, "/v1/generate")
    timeout = httpx.Timeout(connect=20.0, read=1800.0, write=120.0, pool=20.0)
    task_ids = []
    raws = []
    image_items = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for _ in range(count):
            response = await holo_request_with_retry(client, "POST", submit_url, headers=holo_headers(provider), json=body_base, max_attempts=3)
            raw = response.json() if response.text else {}
            task_id = extract_holo_task_id(raw)
            task_payload = raw
            if task_id:
                task_ids.append(task_id)
                task_payload = await wait_for_holo_task(client, provider, task_id, timeout_seconds=VIDEO_POLL_TIMEOUT)
                local_url = await save_holo_file_to_output(client, provider, task_id, task_payload, media_type="image")
                image_items.append({"type": "url", "value": local_url, "task_id": task_id, "raw": task_payload})
            else:
                images = extract_images(raw)
                for image in images:
                    local_url = await save_ai_image_to_output(image, prefix="holo_image_")
                    image_items.append({"type": "url", "value": local_url, "task_id": None, "raw": raw})
            raws.append(task_payload)
    if not image_items:
        raise HTTPException(status_code=502, detail="HOLO image generation completed but returned no image file.")
    return image_items[:count], {"task_ids": task_ids, "raws": raws}

async def generate_ai_image(prompt, size, quality, model, reference_images=None, provider_id="comfly"):
    provider = get_api_provider(provider_id)
    if provider["id"] == "modelscope":
        if is_holo_provider(provider):
            fallback_models = HOLO_DEFAULT_VIDEO_MODELS if "sora" in str(model).lower() or "video" in str(model).lower() else HOLO_DEFAULT_IMAGE_MODELS
            provider["image_models"] = model_list_from_values([*(provider.get("image_models") or []), *fallback_models])
            if fallback_models == HOLO_DEFAULT_VIDEO_MODELS:
                provider["video_models"] = model_list_from_values([*(provider.get("video_models") or []), *HOLO_DEFAULT_VIDEO_MODELS])
        return await generate_modelscope_provider_image(prompt, size, model, reference_images, provider)
    if is_holo_provider(provider):
        images, raw = await generate_holo_images(prompt, size, model, reference_images, provider, 1)
        first = images[0]
        return {"type": "url", "value": first.get("value") or first.get("url")}, raw
    if is_gemini_provider(provider):
        return await generate_gemini_provider_image(prompt, size, model, reference_images, provider)
    is_gpt2 = is_gpt_image_2_model(model)
    is_apimart = is_apimart_provider(provider)
    is_t8api = is_t8api_provider(provider)
    quality = str(quality or "").strip().lower()
    if quality not in {"low", "medium", "high"}:
        quality = ""
    if is_gpt_image_2_model(model) and not is_apimart:
        size = normalize_gpt_image_2_size(size)
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} Base URL is not configured.")
    gen_url = provider_endpoint_url(provider, "image_generation_endpoint", "/v1/images/generations")
    edit_url = provider_endpoint_url(provider, "image_edit_endpoint", "/v1/images/edits")
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    mask_refs = [ref for ref in refs if str(ref.get("role") or "").strip().lower() == "mask" or str(ref.get("name") or "").lower().endswith("_mask.png")]
    image_refs = [ref for ref in refs if ref not in mask_refs]
    request_timeout = httpx.Timeout(connect=20.0, read=1800.0, write=120.0, pool=20.0) if (is_gpt2 or is_apimart) else AI_REQUEST_TIMEOUT
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = None
        async def post_openai_edits(edit_files=None):
            data = {"model": model, "prompt": prompt, "size": size}
            if quality:
                data["quality"] = quality
            return await client.post(
                edit_url,
                headers=api_headers(json_body=False, provider=provider),
                data=data,
                files=edit_files if edit_files is not None else {},
            )

        if is_apimart or is_t8api:
            images, raw = await generate_t8api_images(prompt, size, quality, model, reference_images, provider, 1)
            return images[0], raw
        elif is_gpt2 and not image_refs and not mask_refs:
            body = {"model": model, "prompt": prompt, "size": size}
            if quality:
                body["quality"] = quality
            response = await client.post(gen_url, headers=api_headers(provider=provider), json=body)
            if response.status_code >= 400 and images_api_unsupported(response):
                response = await post_openai_edits()
        elif image_refs:
            # OpenAI-compatible image edits use multipart /images/edits.
            files = []
            opened = []
            edit_failed_status = None
            edit_failed_text = ""
            try:
                for ref in image_refs[:4]:
                    path = output_file_from_url(ref.get("url", ""))
                    if not path:
                        continue
                    fh = open(path, "rb")
                    opened.append(fh)
                    files.append(("image", (os.path.basename(path), fh, content_type_for_path(path))))
                if mask_refs:
                    mask_path = output_file_from_url(mask_refs[0].get("url", ""))
                    if mask_path:
                        fh = open(mask_path, "rb")
                        opened.append(fh)
                        files.append(("mask", (os.path.basename(mask_path), fh, content_type_for_path(mask_path))))
                try:
                    response = await post_openai_edits(files)
                    if response.status_code >= 400:
                        edit_failed_status = response.status_code
                        edit_failed_text = response.text[:500]
                        response = None
                except httpx.HTTPError as e:
                    edit_failed_status = -1
                    edit_failed_text = str(e)
                    response = None
            finally:
                for fh in opened:
                    fh.close()
            # If edits fail, non-GPT-Image-2 providers can fall back to generations.
            if response is None:
                if is_gpt2:
                    raise HTTPException(
                        status_code=502,
                        detail=f"GPT-Image-2 /images/edits failed: {edit_failed_text[:300] or edit_failed_status}"
                    )
                print(f"/images/edits failed ({edit_failed_status}): {edit_failed_text[:200]} -> fallback to /images/generations + image:[] JSON")
                image_payload = [reference_to_data_url(ref, max_size=1536) for ref in image_refs[:4]]
                body = {
                    "model": model, "prompt": prompt, "size": size,
                    "response_format": "url", "n": 1,
                    "image": image_payload,
                }
                if quality:
                    body["quality"] = quality
                response = await client.post(gen_url, headers=api_headers(provider=provider), json=body)
                if response.status_code >= 400 and images_api_unsupported(response):
                    raise HTTPException(
                        status_code=502,
                        detail=f"/images/edits failed and this provider does not support /images/generations: {edit_failed_text[:300] or edit_failed_status}"
                    )
        else:
            body = {"model": model, "prompt": prompt, "size": size, "response_format": "url", "n": 1}
            if quality:
                body["quality"] = quality
            response = await client.post(
                gen_url,
                headers=api_headers(provider=provider),
                json=body,
            )
            if response.status_code >= 400 and images_api_unsupported(response):
                response = await post_openai_edits()
        response.raise_for_status()
        raw = response.json()
        try:
            return extract_image(raw), raw
        except HTTPException:
            task_id = extract_task_id(raw)
            if not task_id:
                raise
        task_result = await wait_for_image_task(client, task_id, provider)
        return extract_image(task_result), task_result

def upstream_message_from_record(item):
    role = item.get("role")
    if role not in {"user", "assistant"} or item.get("type") == "image":
        return None
    refs = item.get("attachments") or []
    if refs and role == "user":
        content = [{"type": "text", "text": item.get("content", "")}]
        for ref in refs[:4]:
            url = reference_to_data_url(ref)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return {"role": role, "content": content}
    return {"role": role, "content": item.get("content", "")}
