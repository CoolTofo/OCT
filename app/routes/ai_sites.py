"""AI website library API."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.ai_sites import delete_site, grouped_sites, list_sites, upsert_site
from app.schemas import AiSitePayload


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    data_dir = deps["DATA_DIR"]

    @router.get("/api/ai-sites")
    async def ai_sites():
        return {
            "groups": grouped_sites(data_dir),
            "sites": list_sites(data_dir),
        }

    @router.post("/api/ai-sites")
    async def save_ai_site(payload: AiSitePayload):
        try:
            item = upsert_site(data_dir, payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"site": item}

    @router.delete("/api/ai-sites/{site_id}")
    async def remove_ai_site(site_id: str):
        if not delete_site(data_dir, site_id):
            raise HTTPException(status_code=404, detail="网站不存在，或内置网站不能删除")
        return {"success": True}

    return router
