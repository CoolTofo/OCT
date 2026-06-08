"""Media conversion and upstream asset persistence helpers."""

import base64
import mimetypes
import os
import urllib.parse
import uuid
from io import BytesIO
from typing import Any, Dict

import httpx
from PIL import Image

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

def convert_output_to_jpg(url, quality=88):
    path = output_file_from_url(url)
    if not path:
        return url
    root, ext = os.path.splitext(path)
    if ext.lower() in [".jpg", ".jpeg"]:
        return url
    jpg_path = f"{root}.jpg"
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(jpg_path, "JPEG", quality=quality, optimize=True)
        try:
            root = ASSETS_DIR if os.path.commonpath([os.path.abspath(ASSETS_DIR), os.path.abspath(jpg_path)]) == os.path.abspath(ASSETS_DIR) else OUTPUT_DIR
        except ValueError:
            root = OUTPUT_DIR
        rel = os.path.relpath(jpg_path, root).replace("\\", "/")
        prefix = "/assets" if root == ASSETS_DIR else "/output"
        return f"{prefix}/{rel}"
    except Exception as e:
        print(f"Failed to convert image to JPG: {e}")
        return url

def reference_to_data_url(ref, max_size=None):
    """Convert a local image output to a bounded data URL."""
    path = output_file_from_url(ref.get("url", ""))
    if not path:
        return ref.get("url", "")
    if max_size:
        try:
            with Image.open(path) as img:
                img.load()
                w, h = img.size
                if max(w, h) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = BytesIO()
                fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                img.save(buf, format=fmt, quality=88 if fmt == "JPEG" else None)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            print(f"reference resize failed, fallback to raw: {e}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{content_type_for_path(path)};base64,{encoded}"

def compress_data_url_image(value, max_size=1536, jpeg_quality=88):
    if not isinstance(value, str) or not value.startswith("data:image/") or ";base64," not in value:
        return value
    header, encoded = value.split(";base64,", 1)
    try:
        raw = base64.b64decode(encoded)
        with Image.open(BytesIO(raw)) as img:
            img.load()
            if max_size and max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            if has_alpha:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                fmt, mime = "PNG", "image/png"
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                fmt, mime = "JPEG", "image/jpeg"
            buf = BytesIO()
            if fmt == "JPEG":
                img.save(buf, format=fmt, quality=jpeg_quality, optimize=True)
            else:
                img.save(buf, format=fmt, optimize=True)
            return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception as e:
        print(f"data url image compress failed, fallback to raw: {e}")
        return value

def modelscope_image_url(value, max_size=1536):
    if not value:
        return value
    if isinstance(value, str) and (value.startswith("/output/") or value.startswith("/assets/")):
        return reference_to_data_url({"url": value}, max_size=max_size)
    if isinstance(value, str) and value.startswith("data:image/"):
        return compress_data_url_image(value, max_size=max_size)
    return value

def valid_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return (
        value.startswith("http://") or
        value.startswith("https://") or
        value.startswith("asset://") or
        (value.startswith("data:image/") and ";base64," in value)
    )

def valid_apimart_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return value.startswith("http://") or value.startswith("https://") or value.startswith("asset://")

def is_apimart_veo31_model(model: str) -> bool:
    return str(model or "").strip().lower().startswith("veo3.1")

def apimart_veo31_model(model: str) -> str:
    value = str(model or "").strip().lower()
    aliases = {
        "veo3.1": "veo3.1-fast",
        "veo3.1-pro": "veo3.1-quality",
        "veo3.1-preview": "veo3.1-fast",
    }
    value = aliases.get(value, value or "veo3.1-fast")
    allowed = {"veo3.1-fast", "veo3.1-quality", "veo3.1-lite"}
    return value if value in allowed else "veo3.1-fast"

def apimart_veo31_aspect(aspect: str) -> str:
    value = str(aspect or "16:9").strip()
    return value if value in {"16:9", "9:16"} else "16:9"

def apimart_veo31_resolution(resolution: str) -> str:
    value = str(resolution or "").strip().lower()
    aliases = {"": "720p", "auto": "720p", "480p": "720p", "780p": "720p", "1080": "1080p", "4k": "4k"}
    value = aliases.get(value, value)
    return value if value in {"720p", "1080p", "4k"} else "720p"

def apimart_upload_file_payload(path: str):
    """Return (filename, bytes, content_type), keeping APIMart VEO images under the documented 10MB limit."""
    max_bytes = 9_500_000
    size = os.path.getsize(path)
    if size <= max_bytes:
        with open(path, "rb") as fh:
            return os.path.basename(path), fh.read(), content_type_for_path(path)
    with Image.open(path) as img:
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            bg.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
                return name, data, "image/jpeg"
            quality -= 8
    raise ValueError("Image exceeds 10MB and still cannot meet the VEO3.1 image limit after compression.")

def invalid_video_image_preview(value: str) -> str:
    text = str(value or "")
    if text.startswith("data:"):
        return text.split(";base64,", 1)[0] + ";base64,..."
    return text[:120]

def extract_apimart_asset_url(payload):
    if isinstance(payload, list):
        for item in payload:
            found = extract_apimart_asset_url(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    url_keys = ("url", "asset_url", "assetUrl", "uri", "file_url", "fileUrl")
    for key in url_keys:
        value = str(payload.get(key) or "").strip()
        if valid_apimart_video_image_input(value):
            return value
    id_keys = ("asset_id", "assetId", "file_id", "fileId", "id")
    for key in id_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value if value.startswith("asset://") else f"asset://{value}"
    for key in ("data", "file", "asset", "result"):
        found = extract_apimart_asset_url(payload.get(key))
        if found:
            return found
    return ""

def apimart_upload_payload_from_bytes(data: bytes, mime: str, name_hint: str = "image"):
    """Compress image bytes to fit APIMart upload limits."""
    max_bytes = 9_500_000
    ext = mimetypes.guess_extension(mime or "image/png") or ".png"
    if len(data) <= max_bytes and (mime or "").lower() in ("image/png", "image/jpeg", "image/webp"):
        return f"{name_hint}{ext}", data, (mime or "image/png")
    with Image.open(BytesIO(data)) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        if has_alpha:
            base = img.convert("RGBA")
            bg = Image.new("RGB", base.size, (255, 255, 255))
            bg.paste(base, mask=base.split()[-1])
            target = bg
        else:
            target = img.convert("RGB")
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            target.save(buf, format="JPEG", quality=quality, optimize=True)
            payload = buf.getvalue()
            if len(payload) <= max_bytes:
                return f"{name_hint}.jpg", payload, "image/jpeg"
            quality -= 8
    raise ValueError("Data URL image exceeds 10MB and still cannot meet the APIMart limit after compression.")

async def upload_image_for_apimart(client, provider, ref_url: str) -> str:
    """Prepare a local or remote image URL for APIMart inputs."""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:empty URL"
    # Already a network URL or asset:// URL.
    if ref_url.startswith("http://") or ref_url.startswith("https://") or ref_url.startswith("asset://"):
        return ref_url
    base_url = video_api_root(provider)
    upload_url = f"{base_url}/v1/uploads/images"
    # Decode data URLs and upload them to APIMart.
    if ref_url.startswith("data:"):
        try:
            if ";base64," not in ref_url:
                return "ERR:unsupported data URL; missing base64 payload"
            header, encoded = ref_url.split(";base64,", 1)
            mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "image/png"
            raw = base64.b64decode(encoded)
            filename, content, ct = apimart_upload_payload_from_bytes(raw, mime, name_hint="canvas_image")
            files = {"file": (filename, content, ct)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                print(f"APIMart data URL upload response did not contain a usable asset/url: {str(rj)[:300]}")
                return "ERR:APIMart upload response did not contain a usable URL"
            print(f"APIMart data URL upload failed ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart upload failed ({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            print(f"APIMart data URL upload exception: {e}")
            return f"ERR:upload exception {e}"
    # Local /output/ or /assets/ path: verify the file exists before uploading.
    if ref_url.startswith("/output/") or ref_url.startswith("/assets/"):
        path = output_file_from_url(ref_url)
        if not path:
            print(f"APIMart upload skipped; local file does not exist: {ref_url}")
            return "ERR:local file does not exist or was deleted"
        try:
            filename, content, ct = apimart_upload_file_payload(path)
            files = {"file": (filename, content, ct)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                print(f"APIMart file upload response did not contain a usable asset/url: {str(rj)[:300]}")
                return "ERR:APIMart upload response did not contain a usable URL"
            print(f"APIMart file upload failed ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart upload failed ({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            print(f"APIMart file upload exception: {e}")
            return f"ERR:upload exception {e}"
    return "ERR:unsupported image source; expected http/https/asset/data or local /output/ /assets/ path"

async def save_ai_image_to_output(image_data, prefix="online_", category="output"):
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    path = output_path_for(filename, category)
    if image_data["type"] == "b64":
        mime_type = str(image_data.get("mime_type") or "").lower()
        if "jpeg" in mime_type or "jpg" in mime_type:
            filename = filename[:-4] + ".jpg"
            path = output_path_for(filename, category)
        elif "webp" in mime_type:
            filename = filename[:-4] + ".webp"
            path = output_path_for(filename, category)
        with open(path, "wb") as f:
            f.write(base64.b64decode(image_data["value"]))
        return output_url_for(filename, category)
    value = image_data["value"]
    if value.startswith("/output/") or value.startswith("/assets/"):
        return value
    try:
        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(value)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                filename = filename[:-4] + ".jpg"
                path = output_path_for(filename, category)
            elif "webp" in content_type:
                filename = filename[:-4] + ".webp"
                path = output_path_for(filename, category)
            with open(path, "wb") as f:
                f.write(response.content)
            return output_url_for(filename, category)
    except Exception as e:
        print(f"Failed to save upstream image: {e}")
        return value

async def save_remote_video_to_output(url, prefix="video_", category="output"):
    if not url:
        return ""
    if url.startswith("/output/") or url.startswith("/assets/"):
        return url
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.mp4"
    path = output_path_for(filename, category)
    try:
        async with httpx.AsyncClient(timeout=VIDEO_POLL_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").lower()
            clean_path = urllib.parse.urlparse(url).path
            ext = os.path.splitext(clean_path)[1].lower()
            if ext in {".mp4", ".webm", ".mov"}:
                filename = filename[:-4] + ext
                path = output_path_for(filename, category)
            elif "webm" in content_type:
                filename = filename[:-4] + ".webm"
                path = output_path_for(filename, category)
            elif "quicktime" in content_type or "mov" in content_type:
                filename = filename[:-4] + ".mov"
                path = output_path_for(filename, category)
            with open(path, "wb") as f:
                f.write(response.content)
            return output_url_for(filename, category)
    except Exception as e:
        print(f"Failed to save upstream video: {e}")
        return url

