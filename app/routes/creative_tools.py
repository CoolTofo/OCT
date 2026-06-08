"""Canvas creative tool APIs such as outpainting and 360 panorama generation."""

from typing import Any, Dict

from fastapi import APIRouter

from app.creative_tools import (
    build_extend_prompt,
    build_panorama_prompt,
    creative_recipes,
    image_extend_online_payload,
    panorama_online_payload,
)
from app.schemas import ImageExtendRequest, PanoramaGenerateRequest


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    build_online_image_result = deps["build_online_image_result"]
    save_to_history = deps["save_to_history"]

    @router.get("/api/creative/recipes")
    async def recipes():
        return {"recipes": creative_recipes()}

    @router.post("/api/creative/image-extend/preview")
    async def image_extend_preview(payload: ImageExtendRequest):
        return {"prompt": build_extend_prompt(payload)}

    @router.post("/api/creative/image-extend")
    async def image_extend(payload: ImageExtendRequest):
        online_payload = image_extend_online_payload(payload)
        result = await build_online_image_result(online_payload)
        save_to_history({
            "type": "image-extend",
            "prompt": online_payload.prompt,
            "images": result.get("images") or [],
            "reference_images": [payload.image.dict()],
            "model": payload.model,
        })
        return {**result, "prompt": online_payload.prompt, "tool": "image_extend"}

    @router.post("/api/creative/panorama/preview")
    async def panorama_preview(payload: PanoramaGenerateRequest):
        return {"prompt": build_panorama_prompt(payload)}

    @router.post("/api/creative/panorama")
    async def panorama(payload: PanoramaGenerateRequest):
        online_payload = panorama_online_payload(payload)
        result = await build_online_image_result(online_payload)
        save_to_history({
            "type": "panorama-360",
            "prompt": online_payload.prompt,
            "images": result.get("images") or [],
            "reference_images": [ref.dict() for ref in payload.reference_images],
            "model": payload.model,
        })
        return {**result, "prompt": online_payload.prompt, "tool": "panorama_360"}

    return router
