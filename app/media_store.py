import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import urllib.parse
import uuid
from threading import Lock
from typing import Any

import httpx
from fastapi import HTTPException

from app.canvas_store import now_ms
from app.paths import (
    ASSET_LIBRARY_PATH,
    ASSETS_DIR,
    BASE_DIR,
    DATA_DIR,
    OUTPUT_DIR,
    OUTPUT_INPUT_DIR,
    OUTPUT_OUTPUT_DIR,
)


MEDIA_PREVIEW_DIR = os.path.join(ASSETS_DIR, "preview")
os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)
MEDIA_TRANSCODE_LOCK = Lock()

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".mts", ".m2ts", ".3gp", ".3g2", ".ogv",
    ".vob", ".f4v", ".rm", ".rmvb",
}
AUDIO_EXTS = {
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma", ".opus",
    ".aiff", ".aif", ".amr",
}
_FFMPEG_CACHE = {"looked": False, "path": ""}


def public_upload_endpoint() -> str:
    return os.getenv(
        "PUBLIC_UPLOAD_ENDPOINT",
        os.getenv("CLOUD_UPLOAD_ENDPOINT", "https://cloudspace-245757829522.us-west1.run.app/api/upload"),
    ).strip()


def output_storage(category: str = "output"):
    return (OUTPUT_INPUT_DIR, "input") if category == "input" else (OUTPUT_OUTPUT_DIR, "output")


def output_url_for(filename: str, category: str = "output") -> str:
    _, subdir = output_storage(category)
    return f"/assets/{subdir}/{filename}"


def output_path_for(filename: str, category: str = "output") -> str:
    folder, _ = output_storage(category)
    return os.path.join(folder, filename)


def output_file_from_url(url: Any):
    if isinstance(url, dict):
        url = url.get("url", "")
    if not url or not (url.startswith("/output/") or url.startswith("/assets/")):
        return None
    clean = urllib.parse.unquote(url.split("?", 1)[0]).replace("\\", "/")
    if clean.startswith("/assets/"):
        root = ASSETS_DIR
        rel = clean[len("/assets/"):]
    else:
        root = OUTPUT_DIR
        rel = clean[len("/output/"):]
    rel = rel.lstrip("/")
    if not rel:
        return None
    path = os.path.abspath(os.path.join(root, rel))
    output_root = os.path.abspath(root)
    if os.path.commonpath([output_root, path]) != output_root or not os.path.exists(path):
        return None
    return path


def default_asset_library():
    return {
        "categories": [
            {"id": "characters", "name": "\u89d2\u8272", "type": "image", "items": []},
            {"id": "scenes", "name": "\u573a\u666f", "type": "image", "items": []},
            {"id": "workflows", "name": "\u5de5\u4f5c\u6d41", "type": "workflow", "items": []},
        ],
        "updated_at": now_ms(),
    }


def load_asset_library():
    if not os.path.exists(ASSET_LIBRARY_PATH):
        lib = default_asset_library()
        save_asset_library(lib)
        return lib
    try:
        with open(ASSET_LIBRARY_PATH, "r", encoding="utf-8") as f:
            lib = json.load(f)
    except Exception:
        lib = default_asset_library()
    cats = lib.get("categories") if isinstance(lib.get("categories"), list) else []
    if not any(c.get("type") == "workflow" for c in cats):
        cats.append({"id": "workflows", "name": "\u5de5\u4f5c\u6d41", "type": "workflow", "items": []})
    lib["categories"] = cats
    lib["updated_at"] = int(lib.get("updated_at") or now_ms())
    return lib


def save_asset_library(lib) -> None:
    lib["updated_at"] = now_ms()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ASSET_LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)


def find_asset_category(lib, category_id):
    for cat in lib.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None


def sanitize_asset_name(name, fallback: str = "asset") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or fallback)).strip()
    return name[:120] or fallback


def content_type_for_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".mp4", ".m4v"]:
        return "video/mp4"
    if ext in [".mkv"]:
        return "video/x-matroska"
    if ext in [".avi"]:
        return "video/x-msvideo"
    if ext in [".wmv"]:
        return "video/x-ms-wmv"
    if ext in [".flv", ".f4v"]:
        return "video/x-flv"
    if ext in [".mpg", ".mpeg", ".vob"]:
        return "video/mpeg"
    if ext in [".ts", ".mts", ".m2ts"]:
        return "video/mp2t"
    if ext in [".3gp", ".3g2"]:
        return "video/3gpp"
    if ext == ".ogv":
        return "video/ogg"
    if ext == ".webm":
        return "video/webm"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".wav":
        return "audio/wav"
    if ext == ".ogg":
        return "audio/ogg"
    if ext in [".m4a", ".aac"]:
        return "audio/aac"
    if ext == ".flac":
        return "audio/flac"
    if ext == ".opus":
        return "audio/opus"
    if ext == ".wma":
        return "audio/x-ms-wma"
    if ext in [".aiff", ".aif"]:
        return "audio/aiff"
    if ext == ".amr":
        return "audio/amr"
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    return "image/png"


def media_kind_for_path(path: str) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    mime = mimetypes.guess_type(path or "")[0] or ""
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return ""


def asset_url_from_path(path: str) -> str:
    if not path:
        return ""
    abs_path = os.path.abspath(path)
    for root, prefix in ((ASSETS_DIR, "/assets"), (OUTPUT_DIR, "/output")):
        abs_root = os.path.abspath(root)
        try:
            if os.path.commonpath([abs_root, abs_path]) == abs_root:
                rel = os.path.relpath(abs_path, abs_root).replace("\\", "/")
                return f"{prefix}/{urllib.parse.quote(rel, safe='/')}"
        except ValueError:
            continue
    return ""


def ffmpeg_executable() -> str:
    if _FFMPEG_CACHE["looked"]:
        return _FFMPEG_CACHE["path"]
    candidates = []
    env_path = os.getenv("OCT_FFMPEG_PATH", "").strip().strip('"')
    if env_path:
        candidates.append(env_path)
    candidates.extend([
        os.path.join(BASE_DIR, "tools", "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(BASE_DIR, "tools", "ffmpeg.exe"),
        shutil.which("ffmpeg") or "",
    ])
    try:
        import imageio_ffmpeg  # type: ignore
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    found = ""
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            found = candidate
            break
    _FFMPEG_CACHE.update({"looked": True, "path": found})
    return found


def media_preview_filename(path: str, target_ext: str) -> str:
    stat = os.stat(path)
    key = f"{os.path.abspath(path)}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8", "ignore")
    digest = hashlib.sha1(key).hexdigest()[:16]
    stem = sanitize_asset_name(os.path.splitext(os.path.basename(path))[0], "media")[:72]
    return f"{stem}_{digest}{target_ext}"


def ensure_browser_media(path: str) -> str:
    kind = media_kind_for_path(path)
    if kind not in {"video", "audio"}:
        return path
    try:
        if os.path.commonpath([os.path.abspath(MEDIA_PREVIEW_DIR), os.path.abspath(path)]) == os.path.abspath(MEDIA_PREVIEW_DIR) and os.path.splitext(path)[1].lower() in {".mp4", ".mp3"}:
            return path
    except ValueError:
        pass
    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is not available")
    target_ext = ".mp4" if kind == "video" else ".mp3"
    out_path = os.path.join(MEDIA_PREVIEW_DIR, media_preview_filename(path, target_ext))
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    with MEDIA_TRANSCODE_LOCK:
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        temp_path = os.path.join(MEDIA_PREVIEW_DIR, f".transcode_{uuid.uuid4().hex}{target_ext}")
        if kind == "video":
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", path,
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", os.getenv("OCT_VIDEO_PREVIEW_PRESET", "veryfast"),
                "-crf", os.getenv("OCT_VIDEO_PREVIEW_CRF", "22"),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                temp_path,
            ]
        else:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", path,
                "-vn", "-c:a", "libmp3lame", "-q:a", "4",
                temp_path,
            ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.getenv("OCT_MEDIA_TRANSCODE_TIMEOUT", "900")))
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or "media transcode failed").strip()[:500])
            os.replace(temp_path, out_path)
            return out_path
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass


def extract_public_upload_url(payload, endpoint: str = "") -> str:
    if isinstance(payload, str):
        text = payload.strip()
        return text if text.startswith(("http://", "https://")) else ""
    if isinstance(payload, list):
        for item in payload:
            found = extract_public_upload_url(item, endpoint)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("url", "public_url", "publicUrl", "file_url", "fileUrl", "download_url", "downloadUrl", "src", "href"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.startswith(("http://", "https://")):
                return text
            if text.startswith("/") and endpoint:
                parsed = urllib.parse.urlsplit(endpoint)
                if parsed.scheme and parsed.netloc:
                    return f"{parsed.scheme}://{parsed.netloc}{text}"
    for key in ("data", "file", "result", "asset", "files"):
        found = extract_public_upload_url(payload.get(key), endpoint)
        if found:
            return found
    return ""


async def upload_bytes_to_public_storage(content: bytes, filename: str, content_type: str = "") -> str:
    endpoint = public_upload_endpoint()
    if not endpoint:
        return ""
    safe_name = os.path.basename(filename or f"upload_{uuid.uuid4().hex[:12]}")
    media_type = content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    files = {"file": (safe_name, content, media_type)}
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            resp = await client.post(endpoint, files=files)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cloud upload failed: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Cloud upload failed: HTTP {resp.status_code} {resp.text[:300]}")
    text = resp.text.strip()
    try:
        payload = resp.json()
    except Exception:
        payload = text
    public_url = extract_public_upload_url(payload, endpoint)
    if not public_url:
        raise HTTPException(status_code=502, detail=f"Cloud upload succeeded, but no public URL was found in the response: {text[:300]}")
    return public_url


async def upload_path_to_public_storage(path: str, filename: str = "") -> str:
    with open(path, "rb") as f:
        content = f.read()
    return await upload_bytes_to_public_storage(content, filename or os.path.basename(path), content_type_for_path(path))
