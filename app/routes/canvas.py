import os
import re
import shutil
import urllib.parse
import uuid
import zipfile
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app import canvas_store, media_store
from app.paths import ASSET_LIBRARY_DIR
from app.schemas import (
    AssetLibraryAddRequest,
    AssetLibraryCategoryRequest,
    AssetLibraryRenameRequest,
    CanvasAssetCheckRequest,
    CanvasAssetDownloadRequest,
    CanvasCreateRequest,
    CanvasSaveRequest,
    CanvasViewportSaveRequest,
)


def create_router(manager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/canvases")
    async def canvases():
        return {"canvases": canvas_store.list_canvases()}

    @router.get("/api/canvases/trash")
    async def trashed_canvases():
        return {"canvases": canvas_store.list_deleted_canvases(), "retention_days": 30}

    @router.post("/api/canvases")
    async def create_canvas(payload: CanvasCreateRequest):
        return {"canvas": canvas_store.new_canvas(payload.title, payload.icon, payload.kind)}

    @router.get("/api/canvases/{canvas_id}/meta")
    async def get_canvas_meta(canvas_id: str):
        canvas = canvas_store.load_canvas(canvas_id)
        return {
            "id": canvas.get("id"),
            "updated_at": canvas.get("updated_at", 0),
            "title": canvas.get("title", "Untitled canvas"),
            "icon": canvas.get("icon", "layers"),
            "kind": canvas_store.normalize_canvas_kind(canvas.get("kind")),
        }

    @router.get("/api/canvases/{canvas_id}")
    async def get_canvas(canvas_id: str):
        return {"canvas": canvas_store.load_canvas(canvas_id)}

    @router.post("/api/canvas-assets/check")
    async def check_canvas_assets(payload: CanvasAssetCheckRequest):
        result = {}
        for url in payload.urls[:3000]:
            text = str(url or "").strip()
            if not text:
                continue
            if text.startswith("/output/") or text.startswith("/assets/"):
                result[text] = bool(media_store.output_file_from_url(text))
            else:
                result[text] = True
        return {"exists": result}

    @router.post("/api/canvas-assets/download")
    async def download_canvas_assets(payload: CanvasAssetDownloadRequest):
        buffer = BytesIO()
        used_names = set()
        count = 0
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for url in payload.urls[:1000]:
                text = str(url or "").strip()
                if not text or not (text.startswith("/output/") or text.startswith("/assets/")):
                    continue
                path = media_store.output_file_from_url(text)
                if not path or not os.path.isfile(path):
                    continue
                base = os.path.basename(path) or f"image-{count + 1}.png"
                name, ext = os.path.splitext(base)
                archive_name = base
                suffix = 2
                while archive_name in used_names:
                    archive_name = f"{name}-{suffix}{ext}"
                    suffix += 1
                used_names.add(archive_name)
                zf.write(path, archive_name)
                count += 1
        if count <= 0:
            raise HTTPException(status_code=404, detail="No downloadable local images were found.")
        buffer.seek(0)
        filename = re.sub(r'[\\/:*?"<>|]+', "_", payload.filename or "canvas-output-images.zip")
        if not filename.lower().endswith(".zip"):
            filename += ".zip"
        encoded = urllib.parse.quote(filename)
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
        return Response(buffer.getvalue(), media_type="application/zip", headers=headers)

    @router.get("/api/asset-library")
    async def get_asset_library():
        return {"library": media_store.load_asset_library()}

    @router.post("/api/asset-library/categories")
    async def create_asset_library_category(payload: AssetLibraryCategoryRequest):
        lib = media_store.load_asset_library()
        cat_type = "workflow" if str(payload.type or "").lower() == "workflow" else "image"
        category = {
            "id": f"cat_{uuid.uuid4().hex[:12]}",
            "name": media_store.sanitize_asset_name(payload.name, "New folder"),
            "type": cat_type,
            "items": [],
        }
        lib.setdefault("categories", []).append(category)
        media_store.save_asset_library(lib)
        return {"library": lib, "category": category}

    @router.patch("/api/asset-library/categories/{category_id}")
    async def rename_asset_library_category(category_id: str, payload: AssetLibraryRenameRequest):
        lib = media_store.load_asset_library()
        cat = media_store.find_asset_category(lib, category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found.")
        cat["name"] = media_store.sanitize_asset_name(payload.name, cat.get("name") or "New folder")
        media_store.save_asset_library(lib)
        return {"library": lib, "category": cat}

    @router.delete("/api/asset-library/categories/{category_id}")
    async def delete_asset_library_category(category_id: str):
        lib = media_store.load_asset_library()
        cat = media_store.find_asset_category(lib, category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found.")
        if cat.get("type") == "workflow" and category_id == "workflows":
            raise HTTPException(status_code=400, detail="The default workflow category cannot be deleted.")
        lib["categories"] = [c for c in lib.get("categories", []) if c.get("id") != category_id]
        media_store.save_asset_library(lib)
        return {"library": lib}

    @router.post("/api/asset-library/items")
    async def add_asset_library_item(payload: AssetLibraryAddRequest):
        lib = media_store.load_asset_library()
        cat = media_store.find_asset_category(lib, payload.category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found.")
        if cat.get("type") != "image":
            raise HTTPException(status_code=400, detail="This category does not support image items.")
        src = media_store.output_file_from_url(payload.url)
        if not src:
            raise HTTPException(status_code=400, detail="Only local /assets or /output images can be saved.")
        ext = os.path.splitext(src)[1].lower() or ".png"
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
            ext = ".png"
        safe_name = media_store.sanitize_asset_name(payload.name or os.path.basename(src), "asset")
        if not os.path.splitext(safe_name)[1]:
            safe_name += ext
        dest_name = f"lib_{uuid.uuid4().hex[:12]}_{safe_name}"
        dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
        shutil.copy2(src, dest_path)
        item = {
            "id": f"asset_{uuid.uuid4().hex[:12]}",
            "name": os.path.splitext(safe_name)[0][:120],
            "url": f"/assets/library/{dest_name}",
            "created_at": canvas_store.now_ms(),
        }
        cat.setdefault("items", []).append(item)
        media_store.save_asset_library(lib)
        return {"library": lib, "item": item}

    @router.patch("/api/asset-library/items/{item_id}")
    async def rename_asset_library_item(item_id: str, payload: AssetLibraryRenameRequest):
        lib = media_store.load_asset_library()
        for cat in lib.get("categories", []):
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    item["name"] = media_store.sanitize_asset_name(payload.name, item.get("name") or "asset")
                    media_store.save_asset_library(lib)
                    return {"library": lib, "item": item}
        raise HTTPException(status_code=404, detail="Asset not found.")

    @router.delete("/api/asset-library/items/{item_id}")
    async def delete_asset_library_item(item_id: str):
        lib = media_store.load_asset_library()
        removed = None
        for cat in lib.get("categories", []):
            keep = []
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    removed = item
                else:
                    keep.append(item)
            cat["items"] = keep
        if not removed:
            raise HTTPException(status_code=404, detail="Asset not found.")
        media_store.save_asset_library(lib)
        return {"library": lib}

    @router.put("/api/canvases/{canvas_id}")
    async def update_canvas(canvas_id: str, payload: CanvasSaveRequest):
        canvas = canvas_store.load_canvas(canvas_id)
        current_updated_at = int(canvas.get("updated_at") or 0)
        if payload.base_updated_at and current_updated_at and int(payload.base_updated_at) < current_updated_at:
            raise HTTPException(status_code=409, detail={
                "message": "Canvas was updated by another page; the stale save was rejected.",
                "canvas": canvas,
                "updated_at": current_updated_at,
            })
        canvas["title"] = (payload.title or canvas.get("title") or "Untitled canvas")[:80]
        canvas["icon"] = (payload.icon or canvas.get("icon") or "layers")[:32]
        canvas["kind"] = canvas_store.normalize_canvas_kind(canvas.get("kind"))
        canvas["nodes"] = payload.nodes
        canvas["connections"] = payload.connections
        canvas["viewport"] = payload.viewport
        canvas["logs"] = payload.logs[-500:]
        canvas["settings"] = payload.settings or {}
        canvas_store.prune_unresumable_runninghub_pending(canvas)
        canvas_store.save_canvas(canvas)
        await manager.broadcast_canvas_updated(canvas_id, int(canvas.get("updated_at") or canvas_store.now_ms()), payload.client_id)
        return {"canvas": canvas}

    @router.patch("/api/canvases/{canvas_id}/viewport")
    async def update_canvas_viewport(canvas_id: str, payload: CanvasViewportSaveRequest):
        canvas = canvas_store.load_canvas(canvas_id)
        current_updated_at = int(canvas.get("updated_at") or 0)
        if payload.base_updated_at and current_updated_at and int(payload.base_updated_at) < current_updated_at:
            raise HTTPException(status_code=409, detail={
                "message": "Canvas was updated by another page; the stale viewport save was rejected.",
                "canvas": canvas,
                "updated_at": current_updated_at,
            })
        canvas["viewport"] = payload.viewport or {}
        settings = canvas.get("settings") if isinstance(canvas.get("settings"), dict) else {}
        if isinstance(payload.settings, dict):
            settings = {**settings, **payload.settings}
        canvas["settings"] = settings
        canvas_store.save_canvas(canvas)
        updated_at = int(canvas.get("updated_at") or canvas_store.now_ms())
        await manager.broadcast_canvas_updated(canvas_id, updated_at, payload.client_id)
        return {
            "id": canvas.get("id"),
            "updated_at": updated_at,
            "viewport": canvas.get("viewport") or {},
            "settings": canvas.get("settings") or {},
        }

    @router.delete("/api/canvases/{canvas_id}")
    async def delete_canvas(canvas_id: str):
        canvas = canvas_store.load_canvas_any(canvas_id)
        if not canvas.get("deleted_at"):
            canvas["deleted_at"] = canvas_store.now_ms()
            canvas_store.save_canvas(canvas)
        return {"ok": True}

    @router.post("/api/canvases/{canvas_id}/restore")
    async def restore_canvas(canvas_id: str):
        canvas = canvas_store.load_canvas_any(canvas_id)
        if canvas.get("deleted_at"):
            canvas.pop("deleted_at", None)
            canvas_store.save_canvas(canvas)
        return {"canvas": canvas}

    @router.delete("/api/canvases/{canvas_id}/purge")
    async def purge_canvas(canvas_id: str):
        path = canvas_store.canvas_path(canvas_id)
        if os.path.exists(path):
            os.remove(path)
        return {"ok": True}

    return router
