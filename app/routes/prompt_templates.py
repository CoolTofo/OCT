"""Prompt template library API."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.prompt_templates import delete_template, list_templates, upsert_template
from app.schemas import PromptTemplatePayload


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    data_dir = deps["DATA_DIR"]

    @router.get("/api/prompt-templates")
    async def prompt_templates():
        return {"templates": list_templates(data_dir)}

    @router.post("/api/prompt-templates")
    async def save_prompt_template(payload: PromptTemplatePayload):
        try:
            item = upsert_template(data_dir, payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"template": item}

    @router.delete("/api/prompt-templates/{template_id}")
    async def remove_prompt_template(template_id: str):
        if not delete_template(data_dir, template_id):
            raise HTTPException(status_code=404, detail="模板不存在，或内置模板不能删除")
        return {"success": True}

    return router
