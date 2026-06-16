import base64
import mimetypes
import os
import shutil
import urllib.parse
import uuid
from dataclasses import dataclass

import httpx

from app import canvas_store, media_store
from app.paths import ASSET_LIBRARY_DIR


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SUPPORTED_EXTS = IMAGE_EXTS | media_store.VIDEO_EXTS | media_store.AUDIO_EXTS
DEFAULT_IMPORT_CATEGORY_ID = "manga-assistant-imports"
DEFAULT_IMPORT_CATEGORY_NAME = "漫剧助手导入"
MAX_IMPORT_URLS = 30
MAX_IMPORT_BYTES = int(os.getenv("AI_SITE_IMPORT_MAX_BYTES", str(80 * 1024 * 1024)))

CONTENT_TYPE_EXTS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}


@dataclass
class ImportedRemoteMedia:
    path: str
    url: str
    name: str
    content_type: str
    source_url: str


def unique_urls(urls):
    seen = set()
    output = []
    for url in urls or []:
        clean = str(url or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


def _content_type_base(content_type: str) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def _extension_from_content_type(content_type: str) -> str:
    content_type = _content_type_base(content_type)
    if content_type in CONTENT_TYPE_EXTS:
        return CONTENT_TYPE_EXTS[content_type]
    guessed = mimetypes.guess_extension(content_type) if content_type else ""
    return guessed if guessed in SUPPORTED_EXTS else ""


def _filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = urllib.parse.unquote(os.path.basename(parsed.path or ""))
    return media_store.sanitize_asset_name(name, "remote_asset")


def _extension_from_url(url: str) -> str:
    return os.path.splitext(_filename_from_url(url))[1].lower()


def _media_prefix(ext: str, content_type: str) -> str:
    content_type = _content_type_base(content_type)
    if ext in media_store.VIDEO_EXTS or content_type.startswith("video/"):
        return "video_ref"
    if ext in media_store.AUDIO_EXTS or content_type.startswith("audio/"):
        return "audio_ref"
    return "ai_ref"


def _validate_media(ext: str, content_type: str) -> None:
    content_type = _content_type_base(content_type)
    if ext in SUPPORTED_EXTS:
        return
    if content_type.startswith(("image/", "video/", "audio/")):
        return
    raise ValueError("Unsupported media URL")


def _safe_import_name(url: str, ext: str) -> str:
    name = _filename_from_url(url)
    if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTS:
        name = f"{os.path.splitext(name)[0] or 'remote_asset'}{ext}"
    return name


def _decode_data_url(url: str):
    if not url.startswith("data:"):
        return None
    head, _, payload = url.partition(",")
    if not payload or ";base64" not in head:
        raise ValueError("Only base64 media data URLs are supported")
    content_type = head[5:].split(";", 1)[0].strip().lower()
    ext = _extension_from_content_type(content_type)
    _validate_media(ext, content_type)
    content = base64.b64decode(payload)
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Media file is too large")
    return content, content_type, f"data_import{ext or '.png'}"


async def download_remote_media(url: str):
    data_url = _decode_data_url(url)
    if data_url:
        return data_url

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) media URLs can be imported")

    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = _content_type_base(response.headers.get("content-type", ""))
            ext = _extension_from_url(str(response.url)) or _extension_from_content_type(content_type)
            _validate_media(ext, content_type)
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_IMPORT_BYTES:
                raise ValueError("Media file is too large")
            chunks = []
            total = 0
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_IMPORT_BYTES:
                    raise ValueError("Media file is too large")
                chunks.append(chunk)
            content = b"".join(chunks)
            if not content:
                raise ValueError("Media URL returned no data")
            return content, content_type, _safe_import_name(str(response.url), ext or ".png")


async def import_media_url(url: str) -> ImportedRemoteMedia:
    content, content_type, original_name = await download_remote_media(url)
    ext = os.path.splitext(original_name)[1].lower() or _extension_from_content_type(content_type)
    if ext not in SUPPORTED_EXTS:
        if content_type.startswith("video/"):
            ext = ".mp4"
        elif content_type.startswith("audio/"):
            ext = ".mp3"
        else:
            ext = ".png"
    prefix = _media_prefix(ext, content_type)
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
    path = media_store.output_path_for(filename, "input")
    with open(path, "wb") as fh:
        fh.write(content)
    return ImportedRemoteMedia(
        path=path,
        url=media_store.output_url_for(filename, "input"),
        name=original_name or filename,
        content_type=content_type or media_store.content_type_for_path(path),
        source_url=url,
    )


def ensure_import_category(lib: dict, category_id: str = "") -> dict:
    if category_id:
        cat = media_store.find_asset_category(lib, category_id)
        if cat and cat.get("type") == "image":
            return cat
    cat = media_store.find_asset_category(lib, DEFAULT_IMPORT_CATEGORY_ID)
    if cat:
        return cat
    cat = {
        "id": DEFAULT_IMPORT_CATEGORY_ID,
        "name": DEFAULT_IMPORT_CATEGORY_NAME,
        "type": "image",
        "items": [],
    }
    lib.setdefault("categories", []).append(cat)
    return cat


def add_image_to_import_library(lib: dict, src_path: str, name: str, category_id: str = ""):
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in IMAGE_EXTS:
        return None
    cat = ensure_import_category(lib, category_id)
    safe_name = media_store.sanitize_asset_name(name or os.path.basename(src_path), "asset")
    if os.path.splitext(safe_name)[1].lower() not in IMAGE_EXTS:
        safe_name = f"{os.path.splitext(safe_name)[0] or 'asset'}{ext}"
    dest_name = f"lib_{uuid.uuid4().hex[:12]}_{safe_name}"
    dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
    shutil.copy2(src_path, dest_path)
    item = {
        "id": f"asset_{uuid.uuid4().hex[:12]}",
        "name": os.path.splitext(safe_name)[0][:120],
        "url": f"/assets/library/{urllib.parse.quote(dest_name)}",
        "created_at": canvas_store.now_ms(),
    }
    cat.setdefault("items", []).append(item)
    return item
