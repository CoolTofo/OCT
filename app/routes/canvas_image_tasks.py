import asyncio
import json
import logging
import time
import uuid
from threading import Lock
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException

from app.schemas import OnlineImageRequest


CANVAS_IMAGE_TASKS: Dict[str, Dict[str, Any]] = {}
CANVAS_IMAGE_TASK_LOCK = Lock()


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    build_online_image_result = deps["build_online_image_result"]
    load_canvas = deps["load_canvas"]
    save_canvas = deps["save_canvas"]
    now_ms: Callable[[], int] = deps["now_ms"]
    manager = deps["manager"]

    def canvas_media_url(item):
        if isinstance(item, dict):
            return item.get("url") or item.get("src") or ""
        return item if isinstance(item, str) else ""

    def canvas_result_image_urls(result: Dict[str, Any]) -> list[str]:
        urls: list[str] = []
        seen = set()
        url_keys = ("url", "src", "image", "image_url", "imageUrl", "output", "output_url", "outputUrl")
        nested_keys = ("images", "outputs", "output_images", "files", "data", "result", "raw", "raws")

        def add_url(value: Any) -> None:
            if not isinstance(value, str):
                return
            url = value.strip()
            if not url.startswith(("http://", "https://", "/assets/", "/output/", "data:image/")):
                return
            if url in seen:
                return
            seen.add(url)
            urls.append(url)

        def walk(value: Any) -> None:
            if isinstance(value, str):
                add_url(value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                for key in url_keys:
                    add_url(value.get(key))
                for key in nested_keys:
                    walk(value.get(key))

        walk(result or {})
        return urls

    def canvas_result_request_meta(result: Dict[str, Any]) -> Dict[str, Any]:
        result = result or {}
        params = result.get("params") if isinstance(result.get("params"), dict) else {}
        return {
            "task_id": result.get("task_id") or "",
            "request_id": result.get("request_id") or "",
            "provider_id": result.get("provider_id") or params.get("provider_id") or "",
            "backend": result.get("backend") or "",
            "prompt_id": result.get("prompt_id") or "",
            "workflow_json": result.get("workflow_json") or "",
            "seed": result.get("seed") or "",
        }

    def canvas_run_label(run: Dict[str, Any]) -> str:
        node = run.get("node") if isinstance(run.get("node"), dict) else {}
        if run.get("taskLabel"):
            return str(run.get("taskLabel"))
        if run.get("nodeType") == "generator":
            return str(node.get("model") or "API Image")
        if run.get("nodeType") == "comfy":
            return str(node.get("comfyWorkflow") or "ComfyUI")
        if run.get("nodeType") == "rh":
            return str(node.get("workflowId") or "RunningHub")
        if run.get("nodeType") == "video":
            return str(node.get("model") or "Video")
        return str(run.get("nodeType") or "Generate")

    def canvas_platform_label(run: Dict[str, Any]) -> str:
        node = run.get("node") if isinstance(run.get("node"), dict) else {}
        if run.get("nodeType") == "generator":
            return str(node.get("apiProvider") or "API")
        if run.get("nodeType") == "comfy":
            return "ComfyUI"
        if run.get("nodeType") == "rh":
            return "RunningHub"
        return str(run.get("nodeType") or "Generate")

    def canvas_pending_matches(pending: Dict[str, Any], task_id: str, pending_id: str) -> bool:
        return bool(
            pending
            and (
                (pending_id and pending.get("id") == pending_id)
                or (task_id and pending.get("canvasTaskId") == task_id)
            )
        )

    async def apply_canvas_image_task_to_canvas(task_id: str, task: Dict[str, Any], result: Optional[Dict[str, Any]] = None, error: str = "") -> bool:
        canvas_id = str(task.get("canvas_id") or "")
        output_id = str(task.get("output_id") or "")
        pending_id = str(task.get("pending_id") or "")
        source_node_id = str(task.get("source_node_id") or "")
        if not canvas_id or not output_id:
            return False

        max_attempts = 25 if pending_id else 1
        result = result or {}
        images = canvas_result_image_urls(result)
        if not images and not error:
            error = str(result.get("message") or result.get("error") or "Image generation completed but returned no images.")
        last_canvas = None
        for attempt in range(max_attempts):
            try:
                canvas = load_canvas(canvas_id)
            except HTTPException:
                return False
            last_canvas = canvas
            nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
            out = next((node for node in nodes if node.get("id") == output_id and node.get("type") == "output"), None)
            pending = None
            if out:
                pending = next((p for p in (out.get("_pending") or []) if canvas_pending_matches(p, task_id, pending_id)), None)
            if out and (pending or not pending_id or attempt == max_attempts - 1):
                break
            await asyncio.sleep(1)
        else:
            return False

        canvas = last_canvas
        if not canvas:
            return False
        nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
        out = next((node for node in nodes if node.get("id") == output_id and node.get("type") == "output"), None)
        if not out:
            return False
        pendings = out.get("_pending") if isinstance(out.get("_pending"), list) else []
        pending = next((p for p in pendings if canvas_pending_matches(p, task_id, pending_id)), None)

        run = {}
        if isinstance(pending, dict) and isinstance(pending.get("run"), dict):
            try:
                run = json.loads(json.dumps(pending.get("run"), ensure_ascii=False))
            except Exception:
                run = dict(pending.get("run") or {})
        request_meta = canvas_result_request_meta(result)
        if run:
            run["request"] = request_meta

        started_at = pending.get("startedAt") if isinstance(pending, dict) else None
        if not started_at:
            started_at = float(task.get("created_at") or time.time()) * 1000
        try:
            run_ms = max(0, int(now_ms() - float(started_at)))
        except Exception:
            run_ms = 0

        changed = False
        if pending:
            out["_pending"] = [p for p in pendings if not canvas_pending_matches(p, task_id, pending_id)]
            changed = True

        added_urls = []
        if images:
            out_images = out.get("images") if isinstance(out.get("images"), list) else []
            existing = {canvas_media_url(item) for item in out_images}
            for url in images:
                if url in existing:
                    continue
                out_images.append({"url": url, "viewed": False, "runMs": run_ms, "run": run or None})
                existing.add(url)
                added_urls.append(url)
            out["images"] = out_images
            if added_urls:
                changed = True
                refs = run.get("refs") if isinstance(run.get("refs"), list) else []
                compare_ref = refs[0] if refs and isinstance(refs[0], dict) else {}
                if compare_ref.get("url"):
                    comparisons = out.get("imageComparisons") if isinstance(out.get("imageComparisons"), dict) else {}
                    for url in added_urls:
                        comparisons[url] = {"url": compare_ref.get("url"), "name": compare_ref.get("name") or "input image"}
                    out["imageComparisons"] = comparisons

        gen_id = source_node_id
        if not gen_id and isinstance(run.get("node"), dict):
            gen_id = run.get("node", {}).get("id") or ""
        gen = next((node for node in nodes if node.get("id") == gen_id), None) if gen_id else None
        if gen:
            gen["running"] = False
            if error:
                gen["runStatus"] = "failed"
                gen["runError"] = str(error)
            else:
                gen["runStatus"] = "done"
                gen["runError"] = ""
                append_generated = bool(pending.get("appendGenerated")) if isinstance(pending, dict) else True
                clean = [url for url in images if url]
                if append_generated:
                    generated = gen.get("generatedOutputs") if isinstance(gen.get("generatedOutputs"), list) else []
                    seen = set(generated)
                    gen["generatedOutputs"] = generated + [url for url in clean if url not in seen and not seen.add(url)]
                elif clean:
                    gen["generatedOutputs"] = clean
            changed = True

        should_log = bool(pending or added_urls or error)
        if should_log:
            if not run:
                run = {"nodeType": "generator", "node": {"id": gen_id}, "prompt": result.get("prompt") or "", "refs": []}
                run["request"] = request_meta
            logs = canvas.get("logs") if isinstance(canvas.get("logs"), list) else []
            logs = [{
                "id": f"log_{uuid.uuid4().hex[:12]}",
                "createdAt": now_ms(),
                "status": "failed" if error else "success",
                "platform": canvas_platform_label(run),
                "nodeType": run.get("nodeType") or "",
                "model": canvas_run_label(run),
                "request": run.get("request") or {},
                "prompt": run.get("prompt") or result.get("prompt") or "",
                "outputs": added_urls or images,
                "refs": run.get("refs") or [],
                "runMs": run_ms,
                "error": str(error) if error else "",
            }] + logs
            canvas["logs"] = logs[:500]
            changed = True

        if not changed:
            return False
        save_canvas(canvas)
        await manager.broadcast_canvas_updated(canvas_id, int(canvas.get("updated_at") or now_ms()), "")
        return True

    async def run_canvas_image_task(task_id: str, payload: OnlineImageRequest):
        with CANVAS_IMAGE_TASK_LOCK:
            if task_id in CANVAS_IMAGE_TASKS:
                CANVAS_IMAGE_TASKS[task_id]["status"] = "running"
                CANVAS_IMAGE_TASKS[task_id]["updated_at"] = time.time()
        try:
            result = await build_online_image_result(payload)
            with CANVAS_IMAGE_TASK_LOCK:
                CANVAS_IMAGE_TASKS[task_id].update({
                    "status": "succeeded",
                    "result": result,
                    "error": "",
                    "updated_at": time.time(),
                })
                task_snapshot = dict(CANVAS_IMAGE_TASKS.get(task_id) or {})
            try:
                await apply_canvas_image_task_to_canvas(task_id, task_snapshot, result=result)
            except Exception as canvas_exc:
                logging.exception("canvas image task writeback failed: %s", canvas_exc)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            status_code = getattr(exc, "status_code", 500)
            with CANVAS_IMAGE_TASK_LOCK:
                CANVAS_IMAGE_TASKS[task_id].update({
                    "status": "failed",
                    "error": str(detail),
                    "status_code": status_code,
                    "updated_at": time.time(),
                })
                task_snapshot = dict(CANVAS_IMAGE_TASKS.get(task_id) or {})
            try:
                await apply_canvas_image_task_to_canvas(task_id, task_snapshot, error=str(detail))
            except Exception as canvas_exc:
                logging.exception("canvas image task failure writeback failed: %s", canvas_exc)

    @router.post("/api/canvas-image-tasks")
    async def create_canvas_image_task(payload: OnlineImageRequest):
        task_id = f"canvas_img_{uuid.uuid4().hex}"
        with CANVAS_IMAGE_TASK_LOCK:
            CANVAS_IMAGE_TASKS[task_id] = {
                "id": task_id,
                "type": "online-image",
                "status": "queued",
                "created_at": time.time(),
                "updated_at": time.time(),
                "result": None,
                "error": "",
                "canvas_id": payload.canvas_id,
                "output_id": payload.output_id,
                "pending_id": payload.pending_id,
                "source_node_id": payload.source_node_id,
                "client_id": payload.client_id,
            }
        asyncio.create_task(run_canvas_image_task(task_id, payload))
        return {"task_id": task_id, "status": "queued"}

    @router.get("/api/canvas-image-tasks/{task_id}")
    async def get_canvas_image_task(task_id: str):
        with CANVAS_IMAGE_TASK_LOCK:
            task = dict(CANVAS_IMAGE_TASKS.get(task_id) or {})
        if not task:
            raise HTTPException(status_code=404, detail="Canvas task not found. The service may have restarted or the task may have expired.")
        return task

    return router
