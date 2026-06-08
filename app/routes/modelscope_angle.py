import asyncio
import time
from typing import Any, Callable, Dict

import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import CloudGenRequest, CloudPollRequest


MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/"
ANGLE_DEFAULT_MODEL = "Qwen/Qwen-Image-Edit-2511"


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    get_modelscope_api_key: Callable[[], str] = deps["get_modelscope_api_key"]
    modelscope_image_url: Callable[..., str] = deps["modelscope_image_url"]
    modelscope_size: Callable[[str], str] = deps["modelscope_size"]
    selected_model: Callable[[str, str], str] = deps["selected_model"]
    output_path_for: Callable[[str, str], str] = deps["output_path_for"]
    output_url_for: Callable[[str, str], str] = deps["output_url_for"]
    save_to_history: Callable[[dict], None] = deps["save_to_history"]
    manager = deps["manager"]
    get_global_loop = deps["get_global_loop"]

    def angle_headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-ModelScope-Async-Mode": "true",
        }

    def clean_token(req_key: str = "") -> str:
        token = (req_key or get_modelscope_api_key()).strip()
        if not token:
            raise HTTPException(status_code=400, detail="ModelScope API key is required.")
        return token

    async def save_angle_image(img_url: str, prompt: str, record_type: str = "angle") -> dict:
        local_path = ""
        try:
            async with httpx.AsyncClient() as dl_client:
                img_res = await dl_client.get(img_url)
                if img_res.status_code == 200:
                    filename = f"cloud_angle_{int(time.time())}.png"
                    file_path = output_path_for(filename, "output")
                    with open(file_path, "wb") as handle:
                        handle.write(img_res.content)
                    local_path = output_url_for(filename, "output")
                else:
                    local_path = img_url
        except Exception:
            local_path = img_url

        record = {"timestamp": time.time(), "prompt": prompt, "images": [local_path], "type": record_type}
        save_to_history(record)
        return {"url": local_path, "record": record}

    async def send_status(client_id: str, payload: dict) -> None:
        if client_id:
            await manager.send_personal_message(payload, client_id)

    async def poll_angle_task(client, token: str, task_id: str, client_id: str, prompt: str, broadcast: bool = False):
        for i in range(300):
            await asyncio.sleep(2)
            try:
                result = await client.get(
                    f"{MODELSCOPE_BASE_URL}v1/tasks/{task_id}",
                    headers={**angle_headers(token), "X-ModelScope-Task-Type": "image_generation"},
                )
                data = result.json()
                status = data.get("task_status")

                if status == "SUCCEED":
                    img_url = data["output_images"][0]
                    saved = await save_angle_image(img_url, prompt)
                    await send_status(client_id, {"type": "cloud_status", "status": "SUCCEED", "task_id": task_id})
                    if broadcast:
                        loop = get_global_loop()
                        if loop:
                            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(saved["record"]), loop)
                    return {"url": saved["url"], "task_id": task_id}

                if status == "FAILED":
                    await send_status(client_id, {"type": "cloud_status", "status": "FAILED", "task_id": task_id})
                    raise Exception(f"ModelScope task failed: {data}")

                if i % 5 == 0 and client_id:
                    await send_status(client_id, {
                        "type": "cloud_status",
                        "status": f"{status} ({i}/300)",
                        "task_id": task_id,
                        "progress": i,
                        "total": 300,
                    })

            except Exception as exc:
                print(f"Angle polling error: {exc}")
                continue

        await send_status(client_id, {"type": "cloud_status", "status": "TIMEOUT", "task_id": task_id})
        return {"status": "timeout", "task_id": task_id, "message": "Task still pending"}

    @router.post("/api/angle/poll_status")
    async def poll_angle_cloud(req: CloudPollRequest):
        token = clean_token(req.api_key)
        task_id = req.task_id
        print(f"Resuming polling for Angle Task: {task_id}")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                return await poll_angle_task(client, token, task_id, req.client_id, f"Resumed {task_id}", broadcast=False)
        except Exception as exc:
            print(f"Angle polling error: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/angle/generate")
    async def generate_angle_cloud(req: CloudGenRequest):
        token = clean_token(req.api_key)
        headers = angle_headers(token)
        model = selected_model(req.model, ANGLE_DEFAULT_MODEL)
        payload = {
            "model": model,
            "prompt": req.prompt.strip(),
            "image_url": [modelscope_image_url(url, max_size=1536) for url in req.image_urls],
        }
        if req.resolution:
            payload["size"] = modelscope_size(req.resolution)
        if req.loras is not None:
            payload["loras"] = req.loras

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                submit_res = await client.post(f"{MODELSCOPE_BASE_URL}v1/images/generations", headers=headers, json=payload)
                if submit_res.status_code != 200:
                    try:
                        detail = submit_res.json()
                    except Exception:
                        detail = submit_res.text
                    raise HTTPException(status_code=submit_res.status_code, detail=detail)

                task_id = submit_res.json().get("task_id")
                print(f"Angle Task submitted, ID: {task_id}")
                return await poll_angle_task(client, token, task_id, req.client_id, req.prompt, broadcast=True)
        except HTTPException:
            raise
        except Exception as exc:
            print(f"Angle generation error: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
