"""Prompt template library API."""

from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.prompt_template_import import parse_docx_prompt_templates
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

    @router.post("/api/prompt-templates/import-docx")
    async def import_prompt_templates_from_docx(file: UploadFile = File(...)):
        filename = str(file.filename or "")
        if not filename.lower().endswith(".docx"):
            raise HTTPException(status_code=400, detail="请上传 .docx Word 文档")
        try:
            payloads = parse_docx_prompt_templates(await file.read())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not payloads:
            raise HTTPException(status_code=400, detail="没有识别到可导入的提示词模板")
        imported = [upsert_template(data_dir, payload) for payload in payloads]
        return {"templates": imported, "count": len(imported)}

    @router.delete("/api/prompt-templates/{template_id}")
    async def remove_prompt_template(template_id: str):
        if not delete_template(data_dir, template_id):
            raise HTTPException(status_code=404, detail="模板不存在，或内置模板不能删除")
        return {"success": True}

    return router
