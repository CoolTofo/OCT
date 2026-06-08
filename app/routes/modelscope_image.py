import asyncio
import time
from typing import Any, Callable, Dict

import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import CloudGenRequest, MsGenerateRequest


MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/"
TERMINAL_FAILED_STATUSES = {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT", "REVOKED"}


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    get_modelscope_api_key: Callable[[], str] = deps["get_modelscope_api_key"]
    modelscope_image_url: Callable[..., str] = deps["modelscope_image_url"]
    modelscope_size: Callable[[str], str] = deps["modelscope_size"]
    output_path_for: Callable[[str, str], str] = deps["output_path_for"]
    output_url_for: Callable[[str, str], str] = deps["output_url_for"]
    save_to_history: Callable[[dict], None] = deps["save_to_history"]
    manager = deps["manager"]
    get_global_loop = deps["get_global_loop"]

    def clean_token(req_key: str = "", label: str = "ModelScope API key") -> str:
        token = (req_key or get_modelscope_api_key()).strip()
        if not token:
            raise HTTPException(status_code=400, detail=f"{label} is not configured.")
        return token

    def async_headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-ModelScope-Async-Mode": "true",
        }

    async def save_output_image(img_url: str, filename: str) -> str:
        local_path = ""
        try:
            async with httpx.AsyncClient() as dl_client:
                img_res = await dl_client.get(img_url)
                if img_res.status_code == 200:
                    file_path = output_path_for(filename, "output")
                    with open(file_path, "wb") as handle:
                        handle.write(img_res.content)
                    local_path = output_url_for(filename, "output")
                else:
                    local_path = img_url
        except Exception as exc:
            print(f"Download error: {exc}")
            local_path = img_url
        return local_path

    @router.post("/generate")
    async def generate_cloud(req: CloudGenRequest):
        token = clean_token(req.api_key, "ModelScope API key")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "Tongyi-MAI/Z-Image-Turbo",
            "prompt": req.prompt.strip(),
            "size": modelscope_size(req.resolution),
            "n": 1,
        }
        if req.loras is not None:
            payload["loras"] = req.loras

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                submit_res = await client.post(
                    f"{MODELSCOPE_BASE_URL}v1/images/generations",
                    headers={**headers, "X-ModelScope-Async-Mode": "true"},
                    json=payload,
                )
                if submit_res.status_code != 200:
                    try:
                        detail = submit_res.json()
                    except Exception:
                        detail = submit_res.text
                    raise HTTPException(status_code=submit_res.status_code, detail=detail)

                task_id = submit_res.json().get("task_id")
                print(f"Z-Image Task submitted, ID: {task_id}")

                for i in range(200):
                    await asyncio.sleep(3)
                    try:
                        result = await client.get(
                            f"{MODELSCOPE_BASE_URL}v1/tasks/{task_id}",
                            headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                        )
                        data = result.json()
                        status = data.get("task_status")

                        if i % 5 == 0:
                            print(f"Task {task_id} status check {i}: {status}")

                        if status == "SUCCEED":
                            img_url = data["output_images"][0]
                            local_path = await save_output_image(img_url, f"cloud_{int(time.time())}.png")
                            record = {"timestamp": time.time(), "prompt": req.prompt, "images": [local_path], "type": "cloud"}
                            save_to_history(record)
                            try:
                                await manager.broadcast_new_image(record)
                            except Exception:
                                pass
                            return {"url": local_path}

                        if status == "FAILED":
                            raise Exception(f"ModelScope task failed: {data}")

                    except Exception as exc:
                        print(f"Polling error (retrying): {exc}")
                        continue

                raise Exception("Cloud generation timeout")

        except HTTPException:
            raise
        except Exception as exc:
            print(f"Cloud generation error: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/ms/generate")
    async def ms_generate(req: MsGenerateRequest):
        token = clean_token(req.api_key, "ModelScope API Key")
        headers = async_headers(token)
        payload = {
            "model": req.model,
            "prompt": req.prompt.strip(),
        }
        if req.width and req.height:
            payload["width"] = req.width
            payload["height"] = req.height
            payload["size"] = modelscope_size(req.size or f"{req.width}x{req.height}")
        elif req.size:
            payload["size"] = modelscope_size(req.size)
        if req.image_urls:
            payload["image_url"] = [modelscope_image_url(url, max_size=1536) for url in req.image_urls]
        if req.loras is not None:
            payload["loras"] = req.loras

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                submit_res = await client.post(
                    f"{MODELSCOPE_BASE_URL}v1/images/generations",
                    headers=headers,
                    json=payload,
                )
                if submit_res.status_code != 200:
                    try:
                        detail = submit_res.json()
                    except Exception:
                        detail = submit_res.text
                    raise HTTPException(status_code=submit_res.status_code, detail=detail)

                task_id = submit_res.json().get("task_id")
                print(f"MS Generate Task submitted ({req.model}), ID: {task_id}")

                for i in range(300):
                    await asyncio.sleep(2)
                    try:
                        result = await client.get(
                            f"{MODELSCOPE_BASE_URL}v1/tasks/{task_id}",
                            headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                        )
                        data = result.json()
                        status = data.get("task_status")
                        print(f"MS Task {task_id} poll {i}: status={status}")

                        if status == "SUCCEED":
                            img_url = data["output_images"][0]
                            safe_model = req.model.replace("/", "_").replace(":", "_")
                            local_path = await save_output_image(img_url, f"ms_{safe_model}_{int(time.time())}.png")
                            record = {
                                "timestamp": time.time(),
                                "prompt": req.prompt,
                                "images": [local_path],
                                "type": "klein",
                                "model": req.model,
                            }
                            save_to_history(record)
                            loop = get_global_loop()
                            if loop:
                                asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(record), loop)
                            return {"url": local_path, "task_id": task_id}

                        if status in TERMINAL_FAILED_STATUSES:
                            error_info = data.get("error_info") or data.get("message") or data.get("detail") or str(data)
                            raise HTTPException(status_code=502, detail=f"MS task {status}: {error_info}")

                    except HTTPException:
                        raise
                    except Exception as exc:
                        print(f"MS polling error: {exc}")
                        continue

                raise HTTPException(status_code=504, detail="ModelScope image generation timed out.")

        except HTTPException:
            raise
        except Exception as exc:
            print(f"MS generate error: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
