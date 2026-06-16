import asyncio
import base64
import mimetypes
import os
import uuid
from io import BytesIO
from typing import Callable, List, Sequence

import httpx
import requests
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps

from app import media_store, media_url_import
from app.paths import STATIC_DIR
from app.schemas import AiUrlImportRequest, PngComposeRequest


def create_router(
    get_comfyui_instances: Callable[[], Sequence[str]],
    get_active_comfyui_instances: Callable[[], Sequence[str]],
    get_public_context: Callable[[], dict],
) -> APIRouter:
    router = APIRouter()

    def media_file_payload(url: str, display_name: str, path: str, extra: dict | None = None):
        payload = {
            "url": url,
            "source_url": url,
            "preview_url": url,
            "name": display_name,
            "type": media_store.content_type_for_path(path),
            "source_type": media_store.content_type_for_path(path),
            "media_kind": "image",
            "size_bytes": os.path.getsize(path) if path and os.path.exists(path) else 0,
            "width": 0,
            "height": 0,
            "format": os.path.splitext(path or "")[1].lower().lstrip("."),
        }
        try:
            kind = media_store.media_kind_for_path(path)
            if kind:
                payload["media_kind"] = kind
            elif payload["type"].startswith("image/"):
                with Image.open(path) as img:
                    payload["width"], payload["height"] = img.size
        except Exception:
            pass
        if payload["type"].startswith("image/"):
            payload["auto_compress_jpg"] = payload["size_bytes"] > 5 * 1024 * 1024
        if extra:
            payload.update(extra)
        return payload

    @router.get("/")
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @router.get("/api/view")
    def view_image(filename: str, type: str = "input", subfolder: str = ""):
        for addr in get_comfyui_instances():
            try:
                url = f"http://{addr}/view"
                params = {"filename": filename, "type": type, "subfolder": subfolder}
                response = requests.get(url, params=params, timeout=1)
                if response.status_code == 200:
                    return Response(content=response.content, media_type=response.headers.get("Content-Type"))
            except Exception:
                continue

        if not subfolder and type in ("input", "output"):
            safe_name = os.path.basename(filename or "")
            if safe_name:
                category = "input" if type == "input" else "output"
                local_path = media_store.output_path_for(safe_name, category)
                if os.path.isfile(local_path):
                    return FileResponse(local_path, media_type=media_store.content_type_for_path(local_path))
        raise HTTPException(status_code=404, detail="Image not found on any available backend")

    @router.get("/api/media-preview")
    def media_preview(url: str):
        path = media_store.output_file_from_url(url)
        if not path:
            raise HTTPException(status_code=404, detail="Media file not found.")
        kind = media_store.media_kind_for_path(path)
        if kind not in {"video", "audio"}:
            return FileResponse(path, media_type=media_store.content_type_for_path(path))
        try:
            preview_path = media_store.ensure_browser_media(path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Media transcoding failed: {exc}") from exc
        return FileResponse(preview_path, media_type=media_store.content_type_for_path(preview_path))

    @router.get("/api/download-output")
    def download_output(url: str, name: str = ""):
        path = media_store.output_file_from_url(url)
        if not path:
            raise HTTPException(status_code=404, detail="File not found.")
        filename = os.path.basename(name) if name else os.path.basename(path)
        return FileResponse(path, media_type=media_store.content_type_for_path(path), filename=filename)

    @router.post("/api/upload")
    async def upload_image(files: List[UploadFile] = File(...)):
        uploaded_files = []
        files_content = []
        active_instances = list(get_active_comfyui_instances())
        for file in files:
            content = await file.read()
            files_content.append((file, content))

        for file, content in files_content:
            success_count = 0
            last_result = None
            for addr in active_instances:
                try:
                    files_data = {"image": (file.filename, content, file.content_type)}
                    response = requests.post(f"http://{addr}/upload/image", files=files_data, timeout=5)
                    if response.status_code == 200:
                        last_result = response.json()
                        success_count += 1
                except Exception as exc:
                    print(f"Upload error for {addr}: {exc}")

            if success_count > 0 and last_result:
                uploaded_files.append({"comfy_name": last_result.get("name", file.filename)})
            else:
                raise HTTPException(status_code=500, detail="Failed to upload to any backend")

        return {"files": uploaded_files}

    @router.post("/api/ai/upload")
    async def upload_ai_reference(files: List[UploadFile] = File(...)):
        uploaded = []
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        allowed_exts = image_exts | media_store.VIDEO_EXTS | media_store.AUDIO_EXTS
        for file in files:
            content = await file.read()
            if not content:
                continue
            ext = os.path.splitext(file.filename or "")[1].lower()
            content_type = (file.content_type or "").lower()
            known_ext = ext in allowed_exts
            known_media_type = (
                content_type.startswith("image/")
                or content_type.startswith("video/")
                or content_type.startswith("audio/")
            )
            if not known_ext and not known_media_type:
                raise HTTPException(status_code=400, detail="Unsupported media file")
            if ext not in allowed_exts:
                guessed = mimetypes.guess_extension(content_type.split(";", 1)[0]) if content_type else ""
                ext = guessed if guessed in allowed_exts else ""
            if ext not in allowed_exts:
                if content_type.startswith("video/"):
                    ext = ".mp4"
                elif content_type.startswith("audio/"):
                    ext = ".mp3"
                else:
                    ext = ".jpg" if "jpeg" in content_type else ".webp" if "webp" in content_type else ".png"
            if content_type.startswith("video/") or ext in media_store.VIDEO_EXTS:
                prefix = "video_ref"
            elif content_type.startswith("audio/") or ext in media_store.AUDIO_EXTS:
                prefix = "audio_ref"
            else:
                prefix = "ai_ref"
            filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
            path = media_store.output_path_for(filename, "input")
            with open(path, "wb") as fh:
                fh.write(content)
            original_url = media_store.output_url_for(filename, "input")
            media_kind = media_store.media_kind_for_path(path)
            final_url = original_url
            preview_url = ""
            transcode_error = ""
            if media_kind in {"video", "audio"}:
                try:
                    preview_path = media_store.ensure_browser_media(path)
                    preview_url = media_store.asset_url_from_path(preview_path)
                    final_url = preview_url or original_url
                except Exception as exc:
                    transcode_error = str(exc)
            payload = media_file_payload(final_url, file.filename or filename, path, {
                "url": final_url,
                "source_url": original_url,
                "preview_url": preview_url or final_url,
                "name": file.filename or filename,
                "type": content_type or media_store.content_type_for_path(final_url or filename),
                "source_type": content_type or media_store.content_type_for_path(filename),
                "media_kind": media_kind or "image",
                "transcoded": bool(preview_url and preview_url != original_url),
                "transcode_error": transcode_error,
            })
            uploaded.append(payload)
        return {"files": uploaded}

    @router.get("/api/ai/media-info")
    async def media_info(url: str):
        path = media_store.output_file_from_url(url)
        if not path:
            raise HTTPException(status_code=404, detail="Local media file not found")
        return {"file": media_file_payload(url, os.path.basename(path), path)}

    @router.post("/api/ai/import-urls")
    async def import_ai_reference_urls(payload: AiUrlImportRequest):
        urls = media_url_import.unique_urls(payload.urls)[:media_url_import.MAX_IMPORT_URLS]
        if not urls:
            raise HTTPException(status_code=400, detail="No media URLs provided.")

        files = []
        errors = []
        library = media_store.load_asset_library() if payload.add_to_library else None
        library_items = []
        for url in urls:
            try:
                imported = await media_url_import.import_media_url(url)
                final_url = imported.url
                preview_url = final_url
                transcode_error = ""
                media_kind = media_store.media_kind_for_path(imported.path) or "image"
                if media_kind in {"video", "audio"}:
                    try:
                        preview_path = media_store.ensure_browser_media(imported.path)
                        preview_url = media_store.asset_url_from_path(preview_path) or final_url
                    except Exception as exc:
                        transcode_error = str(exc)
                file_payload = media_file_payload(final_url, imported.name, imported.path, {
                    "url": final_url,
                    "source_url": final_url,
                    "preview_url": preview_url,
                    "name": imported.name,
                    "type": imported.content_type or media_store.content_type_for_path(imported.path),
                    "source_type": imported.content_type or media_store.content_type_for_path(imported.path),
                    "media_kind": media_kind,
                    "remote_url": imported.source_url,
                    "original_url": imported.source_url,
                    "transcoded": bool(preview_url and preview_url != final_url),
                    "transcode_error": transcode_error,
                })
                files.append(file_payload)
                if library is not None:
                    item = media_url_import.add_image_to_import_library(
                        library,
                        imported.path,
                        imported.name,
                        payload.category_id,
                    )
                    if item:
                        library_items.append(item)
            except Exception as exc:
                errors.append({"url": url, "error": str(exc)})

        if library is not None and library_items:
            media_store.save_asset_library(library)

        return {
            "files": files,
            "errors": errors,
            "library_items": library_items,
            "library": library if library_items else None,
        }

    @router.post("/api/ai/convert-jpg")
    async def convert_ai_reference_to_jpg(payload: dict):
        url = str((payload or {}).get("url") or "").strip()
        quality = int((payload or {}).get("quality") or 88)
        quality = max(50, min(95, quality))
        path = media_store.output_file_from_url(url)
        if not path:
            raise HTTPException(status_code=404, detail="Local image file not found")
        if media_store.media_kind_for_path(path) in {"video", "audio"}:
            raise HTTPException(status_code=400, detail="Only images can be converted to JPG")
        root, _ = os.path.splitext(path)
        jpg_path = f"{root}_jpg_{uuid.uuid4().hex[:8]}.jpg"
        try:
            with Image.open(path) as img:
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    rgba = img.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (255, 255, 255))
                    bg.paste(rgba, mask=rgba.split()[-1])
                    out = bg
                else:
                    out = img.convert("RGB")
                out.save(jpg_path, "JPEG", quality=quality, optimize=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to convert image to JPG: {exc}") from exc
        jpg_url = media_store.asset_url_from_path(jpg_path)
        return {
            "file": media_file_payload(jpg_url, os.path.basename(jpg_path), jpg_path, {
                "original_url": url,
                "compressed_jpg": True,
                "quality": quality,
            })
        }

    async def load_source_image_bytes(source_url: str) -> bytes:
        source_url = str(source_url or "").strip()
        if not source_url:
            raise HTTPException(status_code=400, detail="Missing source image")
        if source_url.startswith("data:image/"):
            try:
                _, b64 = source_url.split(",", 1)
                return base64.b64decode(b64)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid source image data URL") from exc
        local_path = media_store.output_file_from_url(source_url)
        if local_path:
            with open(local_path, "rb") as fh:
                return fh.read()
        if source_url.startswith(("http://", "https://")):
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    response = await client.get(source_url)
                    response.raise_for_status()
                    return response.content
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Unable to read source image: {exc}") from exc
        raise HTTPException(status_code=400, detail="Unsupported source image URL")

    def alpha_channel_from_mask(mask_img: Image.Image, size, mode: str = "auto", invert: bool = False):
        mode = (mode or "auto").strip().lower()
        if mode not in {"auto", "alpha", "luma"}:
            mode = "auto"
        mask_rgba = mask_img.convert("RGBA")
        if mask_rgba.size != size:
            mask_rgba = mask_rgba.resize(size, Image.Resampling.LANCZOS)
        alpha = mask_rgba.getchannel("A")
        alpha_extrema = alpha.getextrema()
        use_alpha = mode == "alpha" or (mode == "auto" and alpha_extrema != (255, 255))
        if use_alpha:
            channel = alpha
            source = "alpha"
        else:
            channel = ImageOps.grayscale(mask_rgba.convert("RGB"))
            source = "luma"
        if invert:
            channel = ImageOps.invert(channel)
        return channel, source

    def png_file_payload(url: str, display_name: str):
        return {
            "url": url,
            "source_url": url,
            "preview_url": url,
            "name": display_name,
            "type": "image/png",
            "source_type": "image/png",
            "media_kind": "image",
            "transcoded": False,
            "transcode_error": "",
        }

    def alpha_channel_from_raw(raw: bytes, width: int, height: int, size, invert: bool = False) -> Image.Image:
        width = int(width or 0)
        height = int(height or 0)
        if width <= 0 or height <= 0:
            raise HTTPException(status_code=400, detail="Invalid alpha mask size")
        expected = width * height
        if len(raw) != expected:
            raise HTTPException(status_code=400, detail=f"Invalid alpha mask bytes: expected {expected}, got {len(raw)}")
        alpha = Image.frombytes("L", (width, height), raw)
        if invert:
            alpha = ImageOps.invert(alpha)
        if alpha.size != size:
            alpha = alpha.resize(size, Image.Resampling.LANCZOS)
        return alpha

    def save_unassociated_rgba_png(source_img: Image.Image, alpha: Image.Image) -> bytes:
        source_rgba = source_img.convert("RGBA")
        if alpha.size != source_rgba.size:
            alpha = alpha.resize(source_rgba.size, Image.Resampling.LANCZOS)
        source_rgba.putalpha(alpha)
        out = BytesIO()
        source_rgba.save(out, format="PNG", optimize=False)
        return out.getvalue()

    @router.post("/api/ai/mask-upload")
    async def upload_alpha_mask(
        source_url: str = Form(...),
        filename: str = Form("mask.png"),
        mask: UploadFile = File(...),
    ):
        mask_bytes = await mask.read()
        if not mask_bytes:
            raise HTTPException(status_code=400, detail="Missing mask image")

        source_bytes = await load_source_image_bytes(source_url)
        try:
            with Image.open(BytesIO(source_bytes)) as source_img, Image.open(BytesIO(mask_bytes)) as mask_img:
                alpha_source = mask_img.convert("RGBA")
                content = save_unassociated_rgba_png(source_img, alpha_source.getchannel("A"))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to compose mask PNG: {exc}") from exc

        display_name = media_store.sanitize_asset_name(os.path.basename(filename or "mask.png"), "mask.png")
        if not display_name.lower().endswith(".png"):
            display_name = f"{os.path.splitext(display_name)[0] or 'mask'}.png"
        stored_name = f"ai_ref_{uuid.uuid4().hex[:12]}.png"
        path = media_store.output_path_for(stored_name, "input")
        with open(path, "wb") as fh:
            fh.write(content)

        url = media_store.output_url_for(stored_name, "input")
        return {"files": [png_file_payload(url, display_name)]}

    @router.post("/api/ai/alpha-mask-upload")
    async def upload_raw_alpha_mask(
        source_url: str = Form(...),
        filename: str = Form("mask.png"),
        alpha_width: int = Form(...),
        alpha_height: int = Form(...),
        invert_mask: bool = Form(False),
        alpha: UploadFile = File(...),
    ):
        alpha_bytes = await alpha.read()
        if not alpha_bytes:
            raise HTTPException(status_code=400, detail="Missing alpha mask")
        source_bytes = await load_source_image_bytes(source_url)
        try:
            with Image.open(BytesIO(source_bytes)) as source_img:
                source_rgba = source_img.convert("RGBA")
                alpha_channel = alpha_channel_from_raw(
                    alpha_bytes,
                    alpha_width,
                    alpha_height,
                    source_rgba.size,
                    invert_mask,
                )
                content = save_unassociated_rgba_png(source_rgba, alpha_channel)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to compose raw alpha PNG: {exc}") from exc

        display_name = media_store.sanitize_asset_name(os.path.basename(filename or "mask.png"), "mask.png")
        if not display_name.lower().endswith(".png"):
            display_name = f"{os.path.splitext(display_name)[0] or 'mask'}.png"
        stored_name = f"ai_ref_{uuid.uuid4().hex[:12]}.png"
        path = media_store.output_path_for(stored_name, "input")
        with open(path, "wb") as fh:
            fh.write(content)

        url = media_store.output_url_for(stored_name, "input")
        return {
            "files": [png_file_payload(url, display_name)],
            "alpha_source": "raw",
            "preserves_rgb": True,
            "premultiplied": False,
        }

    @router.post("/api/ai/png-compose")
    async def compose_rgba_png(payload: PngComposeRequest):
        rgb_bytes, mask_bytes = await asyncio.gather(
            load_source_image_bytes(payload.rgb_url),
            load_source_image_bytes(payload.mask_url),
        )
        try:
            with Image.open(BytesIO(rgb_bytes)) as rgb_img, Image.open(BytesIO(mask_bytes)) as mask_img:
                source_rgba = rgb_img.convert("RGBA")
                alpha, alpha_source = alpha_channel_from_mask(
                    mask_img,
                    source_rgba.size,
                    payload.mask_mode,
                    payload.invert_mask,
                )
                rgb_preview = source_rgba.copy()
                rgb_preview.putalpha(255)
                source_rgba = source_rgba.copy()
                source_rgba.putalpha(alpha)
                alpha_preview = Image.merge("RGBA", (alpha, alpha, alpha, Image.new("L", alpha.size, 255)))

                composed_out = BytesIO()
                source_rgba.save(composed_out, format="PNG", optimize=False)
                rgb_out = BytesIO()
                rgb_preview.save(rgb_out, format="PNG")
                alpha_out = BytesIO()
                alpha_preview.save(alpha_out, format="PNG")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to compose RGBA PNG: {exc}") from exc

        display_name = media_store.sanitize_asset_name(
            os.path.basename(payload.filename or "composed_rgba.png"),
            "composed_rgba.png",
        )
        if not display_name.lower().endswith(".png"):
            display_name = f"{os.path.splitext(display_name)[0] or 'composed_rgba'}.png"
        stem = os.path.splitext(display_name)[0] or "composed_rgba"
        stored_name = f"png_comp_{uuid.uuid4().hex[:12]}.png"
        rgb_preview_name = f"png_comp_{uuid.uuid4().hex[:12]}_rgb.png"
        alpha_preview_name = f"png_comp_{uuid.uuid4().hex[:12]}_alpha.png"
        for filename, content in (
            (stored_name, composed_out.getvalue()),
            (rgb_preview_name, rgb_out.getvalue()),
            (alpha_preview_name, alpha_out.getvalue()),
        ):
            with open(media_store.output_path_for(filename, "output"), "wb") as fh:
                fh.write(content)

        url = media_store.output_url_for(stored_name, "output")
        rgb_preview_url = media_store.output_url_for(rgb_preview_name, "output")
        alpha_preview_url = media_store.output_url_for(alpha_preview_name, "output")
        return {
            "files": [png_file_payload(url, display_name)],
            "rgb_preview_url": rgb_preview_url,
            "alpha_preview_url": alpha_preview_url,
            "previews": {
                "composite": url,
                "rgb": rgb_preview_url,
                "alpha": alpha_preview_url,
            },
            "alpha_source": alpha_source,
            "size": {"width": source_rgba.size[0], "height": source_rgba.size[1]},
            "name": display_name,
            "preview_names": {
                "rgb": f"{stem}_rgb.png",
                "alpha": f"{stem}_alpha.png",
            },
        }

    @router.post("/api/public-upload")
    async def upload_public_files(files: List[UploadFile] = File(...)):
        uploaded = []
        for file in files:
            content = await file.read()
            if not content:
                continue
            public_url = await media_store.upload_bytes_to_public_storage(
                content,
                file.filename or f"upload_{uuid.uuid4().hex[:12]}",
                file.content_type or "",
            )
            uploaded.append({"url": public_url, "public_url": public_url, "name": file.filename or os.path.basename(public_url)})
        return {"files": uploaded}

    @router.post("/api/motion-transfer/upload-video")
    async def upload_motion_transfer_video(files: List[UploadFile] = File(...)):
        uploaded = []
        allowed_exts = {".mp4", ".mov", ".webm"}
        allowed_types = {"video/mp4", "video/quicktime", "video/webm"}
        public_context = get_public_context()
        public_upload_endpoint = str(public_context.get("PUBLIC_UPLOAD_ENDPOINT") or "").strip()
        motion_public_base_url = str(public_context.get("MOTION_TRANSFER_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        for file in files:
            content = await file.read()
            if not content:
                continue
            ext = os.path.splitext(file.filename or "")[1].lower()
            content_type = (file.content_type or "").lower()
            if ext not in allowed_exts:
                if content_type == "video/mp4":
                    ext = ".mp4"
                elif content_type == "video/quicktime":
                    ext = ".mov"
                elif content_type == "video/webm":
                    ext = ".webm"
            if ext not in allowed_exts and content_type not in allowed_types:
                raise HTTPException(status_code=400, detail="Template videos only support mp4, mov, or webm.")
            filename = f"motion_ref_{uuid.uuid4().hex[:12]}{ext if ext in allowed_exts else '.mp4'}"
            path = media_store.output_path_for(filename, "input")
            with open(path, "wb") as fh:
                fh.write(content)
            local_url = media_store.output_url_for(filename, "input")
            public_url = ""
            if public_upload_endpoint:
                public_url = await media_store.upload_bytes_to_public_storage(
                    content,
                    filename,
                    content_type or media_store.content_type_for_path(path),
                )
            elif motion_public_base_url:
                public_url = f"{motion_public_base_url}{local_url}"
            uploaded.append({
                "url": local_url,
                "public_url": public_url,
                "name": file.filename or filename,
                "local_only": not bool(public_url),
            })
        return {"files": uploaded}

    return router
