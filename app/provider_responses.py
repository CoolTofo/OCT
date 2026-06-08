"""Shared upstream response parsing helpers."""

import json
from typing import Any

from fastapi import HTTPException

def unwrap_apimart_response(raw):
    """Unwrap APIMart responses that wrap OpenAI-compatible payloads."""
    if isinstance(raw, dict) and "data" in raw and isinstance(raw.get("data"), dict) and "choices" not in raw:
        return raw["data"]
    return raw

def text_from_chat_response(data):
    data = unwrap_apimart_response(data)
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "\n".join(part for part in parts if part)
    return str(content)

def text_delta_from_chat_chunk(data):
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "".join(parts)
    return str(content) if content else ""

def sse_event(data):
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

def image_record_from_item(item):
    if isinstance(item, str) and item:
        return {"type": "url", "value": item} if item.startswith(("http://", "https://", "/output/", "/assets/")) else {"type": "b64", "value": item}
    if not isinstance(item, dict):
        return None
    url = item.get("url") or item.get("image_url") or item.get("imageUrl")
    if isinstance(url, list):
        url = next((u for u in url if isinstance(u, str) and u), "")
    if isinstance(url, str) and url:
        return {"type": "url", "value": url}
    b64 = item.get("b64_json") or item.get("b64") or item.get("base64")
    if isinstance(b64, str) and b64:
        return {"type": "b64", "value": b64, "mime_type": item.get("mime_type") or item.get("mimeType") or "image/png"}
    return None

def extract_images(data):
    images = []
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Image API returned no image data.")

    candidates = data.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    continue
                value = inline.get("data")
                if value:
                    images.append({
                        "type": "b64",
                        "value": value,
                        "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    })
        if images:
            return images

    containers = [data]
    cursor = data
    while isinstance(cursor, dict):
        nested = cursor.get("data")
        if isinstance(nested, dict):
            containers.append(nested)
            cursor = nested
            continue
        break

    for container in list(containers):
        result = container.get("result") if isinstance(container, dict) else None
        if isinstance(result, dict):
            containers.append(result)

    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("data", "images", "output_images"):
            value = container.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                record = image_record_from_item(item)
                if record:
                    images.append(record)
        result_images = container.get("images") or []
        if isinstance(result_images, list):
            for item in result_images:
                record = image_record_from_item(item)
                if record:
                    images.append(record)

    deduped = []
    seen = set()
    for image in images:
        key = (image.get("type"), image.get("value"))
        if not image.get("value") or key in seen:
            continue
        seen.add(key)
        deduped.append(image)
    if deduped:
        return deduped
    raise HTTPException(status_code=502, detail="Image API returned no image data.")

def extract_image(data):
    return extract_images(data)[0]

def extract_task_id(data):
    if isinstance(data, str) and data.strip():
        return data.strip()
    if not isinstance(data, dict):
        return None
    if data.get("task_id"):
        return str(data["task_id"])
    if data.get("id") and str(data.get("id", "")).startswith("task"):
        return str(data["id"])
    nested = data.get("data")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, (dict, str)):
            return extract_task_id(first)
    if isinstance(nested, dict):
        return extract_task_id(nested)
    return None

def images_api_unsupported(response):
    text = str(getattr(response, "text", "") or "").lower()
    return "images api is not supported" in text or "not supported for this platform" in text


VIDEO_URL_KEYS = (
    "url", "video_url", "videoUrl", "mp4_url", "mp4Url",
    "output", "output_url", "outputUrl", "download_url", "downloadUrl",
    "video", "src", "uri", "preview_url", "previewUrl",
)

def _collect_video_url(value, urls):
    if not value:
        return
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://") or value.startswith("/output/") or value.startswith("/assets/"):
            urls.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_video_url(item, urls)
        return
    if isinstance(value, dict):
        for key in VIDEO_URL_KEYS:
            if key in value:
                _collect_video_url(value.get(key), urls)

def video_output_urls(raw):
    urls = []
    if not isinstance(raw, dict):
        return urls
    candidates = [raw]
    data = raw.get("data")
    if isinstance(data, dict):
        candidates.append(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                candidates.append(item)
    for node in list(candidates):
        result = node.get("result") if isinstance(node, dict) else None
        if isinstance(result, dict):
            candidates.append(result)
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    candidates.append(item)
        content = node.get("content") if isinstance(node, dict) else None
        if isinstance(content, dict):
            candidates.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    candidates.append(item)
    for node in candidates:
        if not isinstance(node, dict):
            continue
        for key in ("videos", "outputs"):
            value = node.get(key)
            if value:
                _collect_video_url(value, urls)
        for key in VIDEO_URL_KEYS:
            if key in node:
                _collect_video_url(node.get(key), urls)
    deduped = []
    for url in urls:
        if isinstance(url, str) and url and url not in deduped:
            deduped.append(url)
    return deduped


