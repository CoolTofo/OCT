"""Video generation and motion-transfer routes."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import CanvasVideoRequest, MotionTransferRequest

router = APIRouter()
_ROUTE_DEPS: Dict[str, Any] = {}


def create_router(deps: Dict[str, Any]) -> APIRouter:
    _ROUTE_DEPS.clear()
    _ROUTE_DEPS.update(deps)
    globals().update(deps)
    return router

def video_api_root(provider):
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if base_url.endswith("/v1") or base_url.endswith("/v2"):
        base_url = base_url.rsplit("/", 1)[0]
    return base_url

VIDEO_TASK_SUCCESS_STATUSES = {
    "SUCCESS", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE",
    "DONE", "FINISHED", "FINISH", "OK", "READY",
}
VIDEO_TASK_FAILURE_STATUSES = {
    "FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED",
    "CANCELED", "CANCELLED", "TIMEOUT", "TIMEDOUT", "REJECTED", "EXPIRED",
}


def volc_visual_api_root(provider):
    base_url = str((provider or {}).get("base_url") or VOLC_VISUAL_DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{(provider or {}).get('name') or 'Motion Transfer'} Base URL is not configured.")
    return base_url


def parse_volc_visual_credentials(provider):
    key_text = os.getenv(provider_key_env(provider["id"]), "").strip()
    ak = os.getenv("VOLCENGINE_ACCESS_KEY_ID", "").strip() or os.getenv("VOLC_ACCESS_KEY_ID", "").strip()
    sk = os.getenv("VOLCENGINE_SECRET_ACCESS_KEY", "").strip() or os.getenv("VOLC_SECRET_ACCESS_KEY", "").strip()
    if key_text:
        if key_text.startswith("{"):
            try:
                data = json.loads(key_text)
                ak = str(data.get("ak") or data.get("access_key") or data.get("access_key_id") or ak).strip()
                sk = str(data.get("sk") or data.get("secret_key") or data.get("secret_access_key") or sk).strip()
            except Exception:
                pass
        if not (ak and sk):
            for sep in ("::", "|", ",", "\n", ":"):
                if sep in key_text:
                    left, right = key_text.split(sep, 1)
                    ak = left.strip()
                    sk = right.strip()
                    break
    if not ak or not sk:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} Volcengine AccessKey/SecretKey is not configured. Set AK:SK in API settings, or configure VOLCENGINE_ACCESS_KEY_ID / VOLCENGINE_SECRET_ACCESS_KEY.")
    return ak, sk


def volc_visual_signed_headers(provider, action, body):
    access_key, secret_key = parse_volc_visual_credentials(provider)
    service = "cv"
    region = "cn-north-1"
    method = "POST"
    canonical_uri = "/"
    query = urllib.parse.urlencode({"Action": action, "Version": "2022-08-31"})
    parsed = urllib.parse.urlsplit(volc_visual_api_root(provider))
    host = parsed.netloc or "visual.volcengineapi.com"
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_hash = hashlib.sha256(payload).hexdigest()
    now = time.gmtime()
    x_date = time.strftime("%Y%m%dT%H%M%SZ", now)
    short_date = time.strftime("%Y%m%d", now)
    canonical_headers = (
        f"content-type:application/json\n"
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join([method, canonical_uri, query, canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join([
        "HMAC-SHA256",
        x_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    date_key = hmac.new(secret_key.encode("utf-8"), short_date.encode("utf-8"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("utf-8"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode("utf-8"), hashlib.sha256).digest()
    signing_key = hmac.new(service_key, b"request", hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = f"HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }, payload, f"{volc_visual_api_root(provider)}?{query}"


def motion_transfer_req_json(payload):
    meta = {}
    if payload.aigc_content_producer:
        meta["content_producer"] = payload.aigc_content_producer.strip()
    if payload.aigc_producer_id:
        meta["producer_id"] = payload.aigc_producer_id.strip()
    if payload.aigc_content_propagator:
        meta["content_propagator"] = payload.aigc_content_propagator.strip()
    if payload.aigc_propagate_id:
        meta["propagate_id"] = payload.aigc_propagate_id.strip()
    return json.dumps({"aigc_meta": meta}, ensure_ascii=False) if meta else ""


def motion_transfer_status(raw):
    data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        return ""
    return str(data.get("status") or "").strip().lower()


async def motion_transfer_public_video_url(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        host = urllib.parse.urlsplit(text).hostname or ""
        if host in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(status_code=400, detail="Template video cannot use localhost/127.0.0.1. Motion Transfer 2.0 requires a publicly accessible video URL.")
        return text
    if text.startswith("/assets/") or text.startswith("/output/"):
        path = output_file_from_url(text)
        if path and PUBLIC_UPLOAD_ENDPOINT:
            return await upload_path_to_public_storage(path)
        if MOTION_TRANSFER_PUBLIC_BASE_URL:
            return f"{MOTION_TRANSFER_PUBLIC_BASE_URL}{text}"
        raise HTTPException(status_code=400, detail="The local video was uploaded to this app, but Volcengine Motion Transfer only accepts a publicly accessible video_url. Configure PUBLIC_UPLOAD_ENDPOINT / CLOUD_UPLOAD_ENDPOINT, or provide a public video URL.")
    raise HTTPException(status_code=400, detail="Template video must be a public http(s) URL, or be uploaded to cloud storage from the panel first.")


async def motion_transfer_video_payload(value):
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Template video is required.")
    if text.startswith(("http://", "https://")):
        return {"video_url": await motion_transfer_public_video_url(text)}
    path = output_file_from_url(text)
    if not path:
        raise HTTPException(status_code=400, detail="Local template video file does not exist. Upload it again.")
    ext = os.path.splitext(path)[1].lower()
    if ext not in {".mp4", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="Template videos only support mp4, mov, or webm.")
    if PUBLIC_UPLOAD_ENDPOINT:
        return {"video_url": await upload_path_to_public_storage(path)}
    if MOTION_TRANSFER_PUBLIC_BASE_URL:
        return {"video_url": f"{MOTION_TRANSFER_PUBLIC_BASE_URL}{text}"}
    raise HTTPException(status_code=400, detail="The local video was uploaded, but Volcengine Motion Transfer only accepts a publicly accessible video_url. Configure PUBLIC_UPLOAD_ENDPOINT / CLOUD_UPLOAD_ENDPOINT first, or provide a public video URL.")


async def volc_visual_post(client, provider, action, body):
    headers, content, url = volc_visual_signed_headers(provider, action, body)
    response = await client.post(url, headers=headers, content=content)
    response.raise_for_status()
    return response.json() if response.text else {}


async def wait_for_motion_transfer_task(client, provider, task_id, req_key, req_json=""):
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(5.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        body = {"req_key": req_key, "task_id": task_id}
        if req_json:
            body["req_json"] = req_json
        raw = await volc_visual_post(client, provider, "CVSync2AsyncGetResult", body)
        last_payload = raw
        code = raw.get("code") if isinstance(raw, dict) else None
        status = motion_transfer_status(raw)
        urls = video_output_urls(raw)
        if code == 10000 and (status == "done" or urls):
            return raw
        if status in {"not_found", "expired"}:
            raise HTTPException(status_code=502, detail=f"Motion transfer task is unavailable: {status}")
        if code not in (None, 10000) and status == "done":
            raise HTTPException(status_code=502, detail=f"Motion transfer task failed: {raw.get('message') or raw}")
        delay = min(delay * 1.45, 15)
    raise HTTPException(status_code=504, detail=f"Motion transfer task timed out: {last_payload or task_id}")


async def generate_motion_transfer(payload, provider):
    req_key = (payload.req_key or VOLC_VISUAL_MOTION_MODEL).strip() or VOLC_VISUAL_MOTION_MODEL
    body = {
        "req_key": req_key,
        "cut_result_first_second_switch": bool(payload.cut_result_first_second_switch),
    }
    body.update(await motion_transfer_video_payload(payload.video_url))
    image_url = str(payload.image_url or "").strip()
    image_base64 = str(payload.image_base64 or "").strip()
    if image_base64.startswith("data:image/") and "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]
    if image_url:
        body["image_urls"] = [image_url]
    elif image_base64:
        body["binary_data_base64"] = [image_base64]
    else:
        raise HTTPException(status_code=400, detail="Provide an image URL or upload an image.")
    req_json = motion_transfer_req_json(payload)
    async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT, follow_redirects=True) as client:
        raw = await volc_visual_post(client, provider, "CVSync2AsyncSubmitTask", body)
        if raw.get("code") != 10000:
            message = str(raw.get("message") or raw)
            if "video" in message.lower() and "url" in message.lower() and "video_binary_data_base64" in body:
                message = f"{message}\n\nThe upstream API may not support local video base64 upload. Use a public video URL, or expose this app publicly and configure PUBLIC_BASE_URL."
            raise HTTPException(status_code=502, detail=f"Motion Transfer submit failed: {message}")
        task_id = extract_task_id(raw)
        if not task_id:
            raise HTTPException(status_code=502, detail=f"Motion Transfer submit succeeded but returned no task_id: {raw}")
        if not payload.poll:
            return {"task_id": task_id, "raw": raw, "videos": []}
        result = await wait_for_motion_transfer_task(client, provider, task_id, req_key, req_json)
        urls = video_output_urls(result)
        if not urls:
            raise HTTPException(status_code=502, detail=f"Motion Transfer completed but returned no video: {str(result)[:500]}")
        local_urls = [await save_remote_video_to_output(url, prefix="motion_transfer_") for url in urls]
        return {"videos": local_urls, "task_id": task_id, "raw": result}


def seedance_api_root(provider):
    base_url = str((provider or {}).get("base_url") or SEEDANCE_DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{(provider or {}).get('name') or 'Seedance'} Base URL is not configured.")
    if base_url.endswith("/contents/generations/tasks"):
        base_url = base_url[: -len("/contents/generations/tasks")]
    if not base_url.endswith("/api/v3"):
        base_url = base_url.rstrip("/")
    return base_url


def seedance_ratio(value):
    ratio = str(value or "adaptive").strip()
    if ratio == "keep_ratio":
        return "adaptive"
    allowed = {"adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    return ratio if ratio in allowed else "adaptive"


def seedance_media_url(value, max_size=1536):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("data:image/"):
        return compress_data_url_image(text, max_size=max_size)
    if text.startswith("data:"):
        return text
    if text.startswith("/output/") or text.startswith("/assets/"):
        return reference_to_data_url({"url": text}, max_size=max_size)
    return text


def build_seedance_content(payload, image_refs=None, video_urls=None, audio_urls=None):
    content = [{"type": "text", "text": str(payload.prompt or "").strip()}]
    for ref in (image_refs or [])[:16]:
        url = seedance_media_url(ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", ""))
        if not url:
            continue
        role = str(ref.get("role") if isinstance(ref, dict) else getattr(ref, "role", "") or "").strip()
        image_url = {"url": url}
        if role in {"first_frame", "last_frame", "reference_image"}:
            image_url["role"] = role
        content.append({"type": "image_url", "image_url": image_url})
    for url in (video_urls or [])[:4]:
        media_url = seedance_media_url(url)
        if media_url:
            content.append({"type": "video_url", "video_url": {"url": media_url}})
    for url in (audio_urls or [])[:2]:
        media_url = seedance_media_url(url)
        if media_url:
            content.append({"type": "audio_url", "audio_url": {"url": media_url}})
    if audio_urls and not any(item.get("type") in {"image_url", "video_url"} for item in content):
        raise HTTPException(status_code=400, detail="Seedance reference audio cannot be used alone. Provide a reference image or reference video as well.")
    return content


def seedance_task_status(raw):
    task = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
    if not isinstance(task, dict):
        return ""
    return str(task.get("status") or task.get("task_status") or "").strip().upper()


async def wait_for_seedance_task(client, provider, task_id):
    task_url = f"{seedance_api_root(provider)}/contents/generations/tasks/{task_id}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        raw = response.json() if response.text else {}
        last_payload = raw
        status = seedance_task_status(raw)
        if status in VIDEO_TASK_SUCCESS_STATUSES or video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            task_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            error = task_data.get("error") if isinstance(task_data, dict) and isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("fail_reason") or task_data.get("message") or error.get("message") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=f"Seedance video generation task failed: {reason}")
        delay = min(delay * 1.6, 12)
    raise HTTPException(status_code=504, detail=f"Seedance video generation task timed out: {last_payload or task_id}")


async def generate_seedance_video(payload, provider):
    model = selected_model(payload.model, SEEDANCE_DEFAULT_VIDEO_MODELS[0])
    body = {
        "model": model,
        "content": build_seedance_content(payload, [ref.dict() for ref in payload.images if ref.url], payload.videos, payload.audios),
        "ratio": seedance_ratio(payload.aspect_ratio or payload.size),
        "duration": max(1, int(payload.duration or 5)),
        "watermark": bool(payload.watermark),
    }
    if payload.generate_audio:
        body["generate_audio"] = True
    if payload.seed is not None:
        body["seed"] = payload.seed
    submit_url = f"{seedance_api_root(provider)}/contents/generations/tasks"
    async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT, follow_redirects=True) as client:
        response = await client.post(submit_url, headers=api_headers(provider=provider), json=body)
        response.raise_for_status()
        raw = response.json() if response.text else {}
        task_id = extract_task_id(raw) or raw.get("task_id") or raw.get("id")
        result = raw
        if task_id and not video_output_urls(raw):
            result = await wait_for_seedance_task(client, provider, task_id)
        urls = video_output_urls(result)
        if not urls:
            raise HTTPException(status_code=502, detail=f"Seedance video generation succeeded but returned no video: {str(result)[:500]}")
        local_urls = [await save_remote_video_to_output(url, prefix="seedance_video_") for url in urls]
        return {"videos": local_urls, "task_id": task_id, "raw": result}


async def wait_for_video_task(client, provider, task_id):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} Base URL is not configured.")
    if is_apimart_provider(provider):
        task_path = f"{base_url}/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/tasks/{task_id}"
        task_url = f"{task_path}?language=zh"
    else:
        task_url = f"{base_url}/v2/videos/generations/{task_id}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        raw = response.json()
        last_payload = raw
        task_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = str(task_data.get("status") or task_data.get("task_status") or raw.get("status") or raw.get("task_status") or "").upper()
        if status in VIDEO_TASK_SUCCESS_STATUSES:
            return raw
        # Some upstreams omit a status field but already return video URLs.
        if not status and video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("fail_reason") or task_data.get("message") or error.get("message") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=f"Video generation task failed: {reason}")
        delay = min(delay * 1.6, 12)
    raise HTTPException(status_code=504, detail=f"Video generation task timed out: {last_payload or task_id}")

def apimart_video_size(size):
    value = str(size or "16:9").strip()
    if value == "keep_ratio":
        return "adaptive"
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}
    return value if value in allowed else "16:9"

def holo_video_size(payload):
    size = str(payload.size or payload.resolution or "").strip()
    if re.fullmatch(r"\d{2,5}x\d{2,5}", size):
        return size
    aspect = str(payload.aspect_ratio or "16:9").strip()
    if aspect == "9:16":
        return "720x1280"
    if aspect == "1:1":
        return "1024x1024"
    return "1280x720"

async def generate_holo_video(payload, provider):
    model = selected_model(payload.model, "Sora-2-12")
    body = {
        "model": model,
        "messages": build_holo_messages(payload.prompt, [ref.dict() for ref in payload.images if ref.url], payload.videos),
        "size": holo_video_size(payload),
    }
    if payload.duration:
        body["duration"] = payload.duration
    if payload.aspect_ratio:
        body["aspect_ratio"] = payload.aspect_ratio
    if payload.resolution:
        body["resolution"] = payload.resolution
    if payload.seed is not None:
        body["seed"] = payload.seed
    if payload.generate_audio:
        body["generate_audio"] = True
    submit_url = holo_api_url(provider, "/v1/generate")
    async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT, follow_redirects=True) as client:
        response = await holo_request_with_retry(client, "POST", submit_url, headers=holo_headers(provider), json=body, max_attempts=3)
        raw = response.json() if response.text else {}
        task_id = extract_holo_task_id(raw)
        result = raw
        if task_id:
            result = await wait_for_holo_task(client, provider, task_id, timeout_seconds=VIDEO_POLL_TIMEOUT)
            local_url = await save_holo_file_to_output(client, provider, task_id, result, media_type="video")
            return {"videos": [local_url], "task_id": task_id, "raw": result}
        urls = video_output_urls(raw)
        if urls:
            local_urls = [await save_remote_video_to_output(url, prefix="holo_video_") for url in urls]
            return {"videos": local_urls, "task_id": None, "raw": raw}
        raise HTTPException(status_code=502, detail=f"HOLO video generation returned no task or video URL: {str(raw)[:500]}")

@router.post("/api/canvas-video")
async def canvas_video(payload: CanvasVideoRequest):
    provider = get_api_provider(payload.provider_id)
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} Base URL is not configured.")
    api_key = os.getenv(provider_key_env(provider["id"]), "")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} API key is not configured. Set it in API settings.")
    is_apimart = is_apimart_provider(provider)
    if is_seedance_provider(provider):
        try:
            return await generate_seedance_video(payload, provider)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text or ""
            if exc.response.status_code in {401, 403}:
                raise HTTPException(status_code=exc.response.status_code, detail="Seedance API key is invalid, expired, or lacks permission for this model. Check the key, model permissions, and account quota in API settings.") from exc
            if "data url" in text.lower() or "image" in text.lower() and "url" in text.lower():
                raise HTTPException(status_code=exc.response.status_code, detail=f"Seedance reference asset submit failed. Official ARK usually requires publicly accessible image/video/audio URLs. Upload local assets to an accessible URL first. Raw response: {text[:300]}") from exc
            raise HTTPException(status_code=exc.response.status_code, detail=f"Seedance video API error: {text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to request Seedance video API: {exc}") from exc
    if is_holo_provider(provider):
        try:
            return await generate_holo_video(payload, provider)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"HOLO video API error: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to request HOLO video API: {exc}") from exc
    submit_url = f"{base_url}/videos/generations" if is_apimart and base_url.endswith("/v1") else f"{base_url}/v1/videos/generations" if is_apimart else f"{base_url}/v2/videos/generations"
    requested_model = selected_model(payload.model, "veo3-fast")
    is_veo31 = is_apimart and is_apimart_veo31_model(requested_model)
    try:
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            # Build image payload.
            if is_apimart:
                # APIMart accepts http/https or asset:// URLs; upload local images first.
                image_with_roles = []
                invalid_images = []
                apimart_model = apimart_veo31_model(requested_model) if is_veo31 else ""
                if apimart_model == "veo3.1-lite" and payload.images:
                    raise HTTPException(status_code=400, detail="veo3.1-lite does not support image input. Use veo3.1-fast or veo3.1-quality.")
                image_limit = 0 if apimart_model == "veo3.1-lite" else (3 if is_veo31 else 9)
                for ref in payload.images[:image_limit]:
                    if not ref.url:
                        continue
                    role = str(ref.role or "").strip()
                    if not is_veo31 and role in {"first_frame", "last_frame", "reference_image"}:
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_with_roles.append({"url": up_url, "role": role})
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "unknown error"
                            invalid_images.append((ref.url, reason))
                image_payload = []
                if not image_with_roles:
                    for ref in payload.images[:image_limit]:
                        if not ref.url:
                            continue
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_payload.append(up_url)
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "unknown error"
                            invalid_images.append((ref.url, reason))
                if payload.images and not image_with_roles and not image_payload:
                    first_url, first_reason = invalid_images[0] if invalid_images else ("", "unknown error")
                    sample = invalid_video_image_preview(first_url)
                    raise HTTPException(status_code=400, detail=f"Input image cannot be converted to a format supported by the video API: {sample}\nReason: {first_reason}\nEnsure the local file exists and is under 10MB. VEO3.1 requires images to be APIMart-accessible http/https, asset://, or data URLs.")
                # Build APIMart request body.
                if is_veo31:
                    model = apimart_model
                    body = {
                        "prompt": payload.prompt,
                        "model": model,
                        "duration": 8,
                        "aspect_ratio": apimart_veo31_aspect(payload.aspect_ratio),
                        "resolution": apimart_veo31_resolution(payload.resolution),
                    }
                    if image_payload and model != "veo3.1-lite":
                        video_images = image_payload[:3]
                        if model == "veo3.1-quality" and len(video_images) > 2:
                            video_images = video_images[:2]
                        body["image_urls"] = video_images
                        if len(video_images) == 2:
                            body["generation_type"] = "frame"
                        elif len(video_images) >= 3 and model != "veo3.1-quality":
                            body["generation_type"] = "reference"
                    if model != "veo3.1-lite":
                        body["official_fallback"] = False
                else:
                    body = {
                        "prompt": payload.prompt,
                        "model": selected_model(payload.model, "doubao-seedance-2.0"),
                        "duration": payload.duration,
                        "size": apimart_video_size(payload.aspect_ratio or payload.size),
                        "resolution": payload.resolution or "480p",
                    }
                    if image_with_roles:
                        body["image_with_roles"] = image_with_roles
                    elif image_payload:
                        body["image_urls"] = image_payload[:9]
                    if payload.videos:
                        body["video_urls"] = [v for v in payload.videos if v][:3]
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                    if payload.return_last_frame:
                        body["return_last_frame"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
            else:
                # Non-APIMart providers use data URLs.
                image_payload = []
                for ref in payload.images[:4]:
                    if ref.url:
                        image_payload.append(reference_to_data_url(ref.dict(), max_size=1536))
                body = {
                    "prompt": payload.prompt,
                    "model": selected_model(payload.model, "veo3-fast"),
                    "duration": payload.duration,
                    "watermark": payload.watermark,
                }
                if payload.aspect_ratio:
                    body["aspect_ratio"] = payload.aspect_ratio
                    body["ratio"] = payload.aspect_ratio
                if payload.size:
                    body["size"] = payload.size
                if payload.resolution:
                    body["resolution"] = payload.resolution
                if image_payload:
                    body["images"] = image_payload
                if payload.videos:
                    body["videos"] = [v for v in payload.videos if v]
                if payload.enhance_prompt:
                    body["enhance_prompt"] = True
                if payload.enable_upsample:
                    body["enable_upsample"] = True
                if payload.seed is not None:
                    body["seed"] = payload.seed
                if payload.camerafixed:
                    body["camerafixed"] = True
                if payload.return_last_frame:
                    body["return_last_frame"] = True
                if payload.generate_audio:
                    body["generate_audio"] = True
            # Submit the video generation request.
            response = await client.post(submit_url, headers=api_headers(provider=provider), json=body)
            response.raise_for_status()
            try:
                raw = response.json()
            except Exception:
                # Upstream returned HTML or another non-JSON response.
                resp_text = response.text[:500]
                raise HTTPException(status_code=502, detail=f"Upstream video API returned a non-JSON response (status {response.status_code}): {resp_text}")
            task_id = extract_task_id(raw) or raw.get("task_id") or raw.get("id")
            result = raw
            if task_id and not video_output_urls(raw):
                result = await wait_for_video_task(client, provider, task_id)
            urls = video_output_urls(result)
            if not urls:
                raise HTTPException(status_code=502, detail=f"Video generation succeeded but returned no video: {result}")
            local_urls = [await save_remote_video_to_output(url) for url in urls]
            return {"videos": local_urls, "task_id": task_id, "raw": result}
    except httpx.HTTPStatusError as exc:
        text = exc.response.text
        try:
            requested_model = body.get("model", "") or payload.model or ""
        except NameError:
            requested_model = payload.model or ""
        provider_name = provider.get('name') or provider['id']
        # 1) The model name is outside the upstream supported list.
        valid_models_match = re.search(r"not in\s*\[([^\]]+)\]", text)
        if valid_models_match:
            valid_models = [m.strip() for m in valid_models_match.group(1).split(",") if m.strip()]
            sample = valid_models[:30]
            more = f" ({len(valid_models)} total, showing first {len(sample)})" if len(valid_models) > len(sample) else ""
            hint = (
                f"Upstream provider {provider_name} does not recognize model {requested_model}.\n\n"
                f"Supported upstream video models{more}:\n  {', '.join(sample)}\n\n"
                "Set the video model in API settings to one of the models above."
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        # 2) The model exists but this API key has no available channel.
        if "channel not found" in text or "model_not_found" in text:
            hint = (
                f"Upstream provider {provider_name} recognizes model {requested_model}, but this API key has no available route for it.\n\n"
                "Reason: the account does not have access to this model, possibly due to billing or subscription limits.\n\n"
                "Fix:\n"
                f"  1. Open the {provider.get('base_url') or 'upstream provider'} console and enable or fund this model;\n"
                "  2. Or set the video model in API settings to one already enabled for this account, such as veo3-fast / veo2-fast / sora-2."
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        raise HTTPException(status_code=exc.response.status_code, detail=f"Upstream video API error: {text}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to request upstream video API: {exc}") from exc


@router.post("/api/motion-transfer")
async def motion_transfer(payload: MotionTransferRequest):
    provider = get_api_provider(payload.provider_id)
    if not is_volc_visual_provider(provider):
        raise HTTPException(status_code=400, detail="Select the Motion Transfer 2.0 / Volcengine Visual API provider.")
    try:
        result = await generate_motion_transfer(payload, provider)
        if result.get("videos"):
            save_to_history({
                "type": "motion-transfer",
                "timestamp": time.time(),
                "videos": result.get("videos") or [],
                "images": [],
                "task_id": result.get("task_id") or "",
                "provider_id": payload.provider_id,
                "provider_name": provider.get("name") or payload.provider_id,
                "req_key": payload.req_key or VOLC_VISUAL_MOTION_MODEL,
                "image_url": payload.image_url or "",
                "video_url": payload.video_url or "",
                "cut_result_first_second_switch": bool(payload.cut_result_first_second_switch),
            })
        return result
    except httpx.HTTPStatusError as exc:
        text = exc.response.text or ""
        if exc.response.status_code in {401, 403}:
            raise HTTPException(status_code=exc.response.status_code, detail="Volcengine Visual API authentication failed. Check AccessKey/SecretKey, service permissions, and account balance.") from exc
        raise HTTPException(status_code=exc.response.status_code, detail=f"Motion Transfer upstream API error: {text[:500]}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to request Motion Transfer upstream API: {exc}") from exc

