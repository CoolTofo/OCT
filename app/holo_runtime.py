"""HOLO provider request, polling, and output download helpers."""

import asyncio
import json
import random
import time
import uuid
from typing import Any, Dict

import httpx
from fastapi import HTTPException

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

def holo_api_url(provider, path):
    base_url = str((provider or {}).get("base_url") or "https://api.dealonhorizon.us").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{(provider or {}).get('name') or 'HOLO'} Base URL is not configured.")
    path = str(path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url}{path}"

def holo_headers(provider, json_body=True):
    headers = api_headers(json_body=json_body, provider=provider)
    headers.pop("x-goog-api-key", None)
    return headers

def holo_reference_url(value, max_size=1536):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("/output/") or value.startswith("/assets/"):
        return reference_to_data_url({"url": value}, max_size=max_size)
    if value.startswith("data:image/"):
        return compress_data_url_image(value, max_size=max_size)
    return value

def build_holo_messages(prompt, reference_images=None, videos=None):
    content = []
    for ref in (reference_images or [])[:16]:
        url = ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", "")
        url = holo_reference_url(url)
        if url:
            role = str(ref.get("role") if isinstance(ref, dict) else getattr(ref, "role", "") or "").strip()
            item = {"type": "image_url", "image_url": {"url": url}}
            if role:
                item["role"] = role
            content.append(item)
    for url in (videos or [])[:4]:
        text = str(url or "").strip()
        if text:
            content.append({"type": "video_url", "video_url": {"url": text}})
    text_item = {"type": "text", "text": str(prompt or "").strip()}
    if content:
        content.append(text_item)
        return [{"role": "user", "content": content}]
    return [{"role": "user", "content": text_item["text"]}]

def extract_holo_task_id(data):
    return extract_task_id(data)

def holo_task_payload(data):
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and (data.get("data", {}).get("task_id") or data.get("data", {}).get("status")):
        return data["data"]
    return data if isinstance(data, dict) else {}

def holo_task_status(data):
    task = holo_task_payload(data)
    return str(task.get("status") or task.get("task_status") or "").strip().lower()

def is_holo_task_done(data):
    return holo_task_status(data) in {"completed", "complete", "success", "succeeded", "done", "finished", "ok", "ready"}

def is_holo_task_failed(data):
    return holo_task_status(data) in {"failed", "failure", "error", "cancelled", "canceled", "timeout", "expired", "rejected"}

def holo_file_url_from_task(provider, task):
    node = holo_task_payload(task)
    result = node.get("result") if isinstance(node.get("result"), dict) else {}
    for key in ("file_url", "url", "download_url", "output_url", "video_url", "image_url"):
        value = str(result.get(key) or node.get(key) or "").strip()
        if value:
            if value.startswith("http://") or value.startswith("https://"):
                return value
            if value.startswith("/"):
                return holo_api_url(provider, value)
            return holo_api_url(provider, value)
    task_id = node.get("task_id") or node.get("id") or extract_holo_task_id(task)
    return holo_api_url(provider, f"/v1/tasks/{task_id}/file") if task_id else ""

def holo_result_ext(task, fallback="png"):
    node = holo_task_payload(task)
    result = node.get("result") if isinstance(node.get("result"), dict) else {}
    ext = str(result.get("file_ext") or node.get("file_ext") or fallback or "").strip().lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "webp", "gif", "mp4", "webm", "mov"}:
        return "jpg" if ext == "jpeg" else ext
    return fallback

def parse_json_response_text(text):
    try:
        return json.loads(text or "{}")
    except Exception:
        return None

def holo_upstream_error_detail(response):
    status = getattr(response, "status_code", None)
    text = getattr(response, "text", "") or ""
    data = parse_json_response_text(text)
    title = ""
    detail = ""
    if isinstance(data, dict):
        title = str(data.get("title") or data.get("error") or data.get("message") or "").strip()
        detail = str(data.get("detail") or data.get("message") or data.get("error") or "").strip()
    lower = f"{title} {detail} {text}".lower()
    if status in {522, 523, 524} or "cloudflare" in lower or "tcp handshake timed out" in lower or "connection timed out" in lower:
        return f"HOLO upstream connection timed out (Cloudflare {status}). The origin service may be temporarily unavailable; please retry later."
    if status == 529 or "overloaded" in lower:
        return "HOLO upstream service is busy or overloaded; please retry later."
    if status == 429 or "rate limit" in lower:
        return "HOLO upstream rate limit reached; please retry later or check account quota and concurrency limits."
    if status in {401, 403}:
        return "HOLO API key is invalid, expired, or does not have permission for this model."
    msg = detail or title or text[:300]
    return f"HOLO upstream API error (HTTP {status}): {msg}"

def is_retryable_holo_response(response):
    status = getattr(response, "status_code", 0) or 0
    return status in {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 529}

async def holo_request_with_retry(client, method, url, *, headers=None, max_attempts=3, **kwargs):
    last_response = None
    last_error = None
    for attempt in range(max(1, int(max_attempts or 1))):
        try:
            response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code < 400:
                return response
            last_response = response
            if not is_retryable_holo_response(response) or attempt >= max_attempts - 1:
                raise HTTPException(status_code=response.status_code, detail=holo_upstream_error_detail(response))
        except HTTPException:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.PoolTimeout) as exc:
            last_error = exc
            if attempt >= max_attempts - 1:
                raise HTTPException(status_code=502, detail=f"HOLO upstream connection timed out or is unstable: {exc}") from exc
        await asyncio.sleep(min(2 ** attempt, 8) + random.random() * 0.5)
    if last_response is not None:
        raise HTTPException(status_code=last_response.status_code, detail=holo_upstream_error_detail(last_response))
    raise HTTPException(status_code=502, detail=f"HOLO upstream request failed: {last_error}")

async def wait_for_holo_task(client, provider, task_id, timeout_seconds=None):
    timeout = timeout_seconds or VIDEO_POLL_TIMEOUT
    task_url = holo_api_url(provider, f"/v1/tasks/{task_id}")
    deadline = time.monotonic() + timeout
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        response = await holo_request_with_retry(client, "GET", task_url, headers=holo_headers(provider, json_body=False), max_attempts=3)
        raw = response.json() if response.text else {}
        last_payload = raw
        if is_holo_task_done(raw):
            return raw
        if is_holo_task_failed(raw):
            task = holo_task_payload(raw)
            reason = task.get("fail_reason") or task.get("error") or task.get("message") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=f"HOLO task failed: {reason}")
        if not holo_task_status(raw) and video_output_urls(raw):
            return raw
        delay = min(delay * 1.5, 12)
    raise HTTPException(status_code=504, detail=f"HOLO task timed out after {int(timeout)} seconds: task_id={task_id}")

async def save_holo_file_to_output(client, provider, task_id, task_payload, media_type="image"):
    fallback_ext = "mp4" if media_type == "video" else "png"
    ext = holo_result_ext(task_payload, fallback=fallback_ext)
    file_url = holo_file_url_from_task(provider, task_payload) or holo_api_url(provider, f"/v1/tasks/{task_id}/file")
    if file_url.startswith("/output/") or file_url.startswith("/assets/"):
        return file_url
    filename = f"holo_{media_type}_{uuid.uuid4().hex[:10]}.{ext}"
    path = output_path_for(filename, "output")
    response = await holo_request_with_retry(client, "GET", file_url, headers=holo_headers(provider, json_body=False), follow_redirects=True, max_attempts=3)
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        data = response.json()
        urls = video_output_urls(data) if media_type == "video" else []
        if urls:
            return await save_remote_video_to_output(urls[0], prefix="holo_video_")
        try:
            image = extract_image(data)
            return await save_ai_image_to_output(image, prefix="holo_image_")
        except Exception:
            raise HTTPException(status_code=502, detail=f"HOLO file endpoint returned JSON but no downloadable output was found: {str(data)[:300]}")
    if media_type == "video":
        if "webm" in content_type:
            filename = filename.rsplit(".", 1)[0] + ".webm"
            path = output_path_for(filename, "output")
        elif "quicktime" in content_type or "mov" in content_type:
            filename = filename.rsplit(".", 1)[0] + ".mov"
            path = output_path_for(filename, "output")
    else:
        if "jpeg" in content_type or "jpg" in content_type:
            filename = filename.rsplit(".", 1)[0] + ".jpg"
            path = output_path_for(filename, "output")
        elif "webp" in content_type:
            filename = filename.rsplit(".", 1)[0] + ".webp"
            path = output_path_for(filename, "output")
    with open(path, "wb") as f:
        f.write(response.content)
    return output_url_for(filename, "output")

