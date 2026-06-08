from typing import Any, Dict

from fastapi import APIRouter

from app.schemas import OnlineImageRequest


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    build_online_image_result = deps["build_online_image_result"]

    @router.post("/api/online-image")
    async def online_image(payload: OnlineImageRequest):
        return await build_online_image_result(payload)

    return router
