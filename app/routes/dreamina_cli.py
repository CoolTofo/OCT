import time
from typing import Any, Dict

from fastapi import APIRouter

from app.dreamina_cli import query_dreamina_media, run_dreamina_cli
from app.schemas import DreaminaQueryMediaRequest, DreaminaRunRequest


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    save_to_history = deps["save_to_history"]

    @router.post("/api/dreamina/run")
    async def run_dreamina(payload: DreaminaRunRequest):
        started = time.time()
        result = await run_dreamina_cli(payload)
        outputs = [*(result.get("images") or []), *(result.get("videos") or [])]
        if outputs:
            save_to_history({
                "type": "dreamina-cli",
                "prompt": payload.prompt,
                "images": result.get("images") or [],
                "videos": result.get("videos") or [],
                "model": result.get("mode") or payload.mode,
                "request": result.get("request") or {},
                "run_ms": int((time.time() - started) * 1000),
            })
        return result

    @router.post("/api/dreamina/query-media")
    async def query_media(payload: DreaminaQueryMediaRequest):
        return await query_dreamina_media(
            payload.submit_id,
            kind=payload.kind,
            cli_path=payload.cli_path,
            timeout=payload.timeout,
        )

    return router
