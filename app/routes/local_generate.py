"""Local ComfyUI generation route."""

import asyncio
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

import requests
from fastapi import APIRouter

from app.schemas import GenerateRequest

router = APIRouter()
_ROUTE_DEPS: Dict[str, Any] = {}


def create_router(deps: Dict[str, Any]) -> APIRouter:
    _ROUTE_DEPS.clear()
    _ROUTE_DEPS.update(deps)
    globals().update(deps)
    return router

@router.post("/api/generate")
def generate(req: GenerateRequest):
    current_task = LOCAL_TASK_QUEUE.enqueue(req.client_id)
    target_backend = None
    task_id = current_task["task_id"]

    try:
        required_media = []
        for node_id, node_inputs in req.params.items():
            if isinstance(node_inputs, dict):
                for input_name, media_name in node_inputs.items():
                    if not isinstance(media_name, str) or not media_name:
                        continue
                    input_key = str(input_name or "").lower()
                    looks_media = input_key in {"image", "video", "audio"} or re.search(r"\.(png|jpe?g|webp|gif|bmp|mp4|webm|mov|m4v|mkv|avi|wmv|flv|f4v|mpg|mpeg|ts|mts|m2ts|3gp|3g2|ogv|vob|rm|rmvb|mp3|wav|ogg|m4a|flac|aac|wma|opus|aiff|aif|amr)$", media_name, re.I)
                    if looks_media:
                        required_media.append(media_name)

        target_backend = get_best_backend(required_media)
        with LOAD_LOCK:
            BACKEND_LOCAL_LOAD.setdefault(target_backend, 0)
            BACKEND_LOCAL_LOAD[target_backend] += 1

        for media_name in required_media:
            need_sync = False
            try:
                check_url = f"http://{target_backend}/view?filename={urllib.parse.quote(media_name)}&type=input"
                resp = requests.get(check_url, stream=True, timeout=0.5)
                resp.close()
                if resp.status_code != 200:
                    need_sync = True
            except:
                need_sync = True

            if need_sync:
                media_content = None
                media_type = content_type_for_path(media_name)
                for addr in get_active_comfyui_instances():
                    if addr == target_backend: continue
                    try:
                        src_url = f"http://{addr}/view?filename={urllib.parse.quote(media_name)}&type=input"
                        r = requests.get(src_url, timeout=5)
                        if r.status_code == 200:
                            media_content = r.content
                            media_type = r.headers.get("Content-Type", media_type)
                            break
                    except: continue

                if media_content:
                    try:
                        files = {'image': (media_name, media_content, media_type)}
                        requests.post(f"http://{target_backend}/upload/image", files=files, timeout=10)
                    except Exception as e:
                        print(f"Sync upload failed: {e}")

        workflow_path = os.path.join(WORKFLOW_DIR, req.workflow_json)
        if not os.path.exists(workflow_path) and req.workflow_json == "Z-Image.json":
            workflow_path = WORKFLOW_PATH
        if not os.path.exists(workflow_path):
            raise Exception(f"Workflow file not found: {req.workflow_json}")

        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow = json.load(f)

        seed = random.randint(1, 10**15)

        if "23" in workflow and req.prompt:
            workflow["23"]["inputs"]["text"] = req.prompt
        if "144" in workflow:
            workflow["144"]["inputs"]["width"] = req.width
            workflow["144"]["inputs"]["height"] = req.height
        if "22" in workflow:
            workflow["22"]["inputs"]["seed"] = seed
        if "158" in workflow:
            workflow["158"]["inputs"]["noise_seed"] = seed
        for node_id in ["146", "181"]:
            if node_id in workflow and "inputs" in workflow[node_id] and "seed" in workflow[node_id]["inputs"]:
                workflow[node_id]["inputs"]["seed"] = seed
        if "184" in workflow and "inputs" in workflow["184"] and "seed" in workflow["184"]["inputs"]:
            workflow["184"]["inputs"]["seed"] = seed
        if "172" in workflow and "inputs" in workflow["172"] and "seed" in workflow["172"]["inputs"]:
            workflow["172"]["inputs"]["seed"] = seed % 4294967295
        if "14" in workflow and "inputs" in workflow["14"] and "seed" in workflow["14"]["inputs"]:
            workflow["14"]["inputs"]["seed"] = seed

        for node_id, node_inputs in req.params.items():
            if node_id in workflow:
                if "inputs" not in workflow[node_id]:
                    workflow[node_id]["inputs"] = {}
                for input_name, value in node_inputs.items():
                    workflow[node_id]["inputs"][input_name] = value

        body_ratio_fixes = repair_body_ratio_mapper_api_values(workflow)
        if body_ratio_fixes:
            print(f"Repaired BodyRatioMapper API values before prompt submit: {body_ratio_fixes}")
        body_ratio_issues = validate_body_ratio_mapper_api_values(workflow)
        if body_ratio_issues:
            raise Exception(f"BodyRatioMapper API values are invalid after repair: {body_ratio_issues}")

        removed_reroutes = strip_comfy_reroute_nodes(workflow)
        if removed_reroutes:
            print(f"Removed {removed_reroutes} ComfyUI reroute nodes before prompt submit.")
        removed_api_helpers = fold_comfy_api_helper_nodes(workflow)
        if removed_api_helpers:
            print(f"Folded {removed_api_helpers} ComfyUI API helper nodes before prompt submit.")

        p = {"prompt": workflow, "client_id": CLIENT_ID}
        data = json.dumps(p).encode('utf-8')
        try:
            post_req = urllib.request.Request(f"http://{target_backend}/prompt", data=data)
            prompt_id = json.loads(urllib.request.urlopen(post_req, timeout=10).read())['prompt_id']
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise Exception(f"HTTP Error {e.code}: {error_body}")

        history_data = None
        for i in range(COMFYUI_HISTORY_TIMEOUT):
            try:
                res = get_comfy_history(target_backend, prompt_id)
                if prompt_id in res:
                    history_data = res[prompt_id]
                    break
            except Exception:
                pass
            time.sleep(1)

        if not history_data:
            raise Exception("ComfyUI rendering timed out")

        local_images = []
        local_videos = []
        local_urls = []
        current_timestamp = time.time()
        if 'outputs' in history_data:
            for node_id in history_data['outputs']:
                node_output = history_data['outputs'][node_id]
                if 'images' in node_output:
                    for img in node_output['images']:
                        prefix = f"{req.type}_{int(current_timestamp)}_"
                        local_path = download_comfy_output(target_backend, img, prefix=prefix)
                        if req.convert_to_jpg:
                            local_path = convert_output_to_jpg(local_path)
                        local_images.append(local_path)
                        local_urls.append(local_path)
                for output_key in ("videos", "gifs", "animated"):
                    for video in node_output.get(output_key, []) or []:
                        if not isinstance(video, dict) or not video.get("filename"):
                            continue
                        prefix = f"{req.type}_{int(current_timestamp)}_"
                        local_path = download_comfy_output(target_backend, video, prefix=prefix)
                        local_videos.append(local_path)
                        local_urls.append(local_path)

        if not local_urls:
            detail = describe_comfy_failure(history_data)
            raise Exception(f"ComfyUI returned no image/video output: {detail}")

        result = {
            "prompt": req.prompt if req.prompt else "Detail Enhance",
            "images": local_images,
            "videos": local_videos,
            "outputs": local_urls,
            "seed": seed,
            "timestamp": current_timestamp,
            "type": req.type,
            "workflow_json": req.workflow_json,
            "task_id": task_id,
            "prompt_id": prompt_id,
            "backend": target_backend,
            "params": req.params
        }
        save_to_history(result)
        global_loop = get_global_loop()
        if global_loop:
            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(result), global_loop)
        return result

    except Exception as e:
        return {"images": [], "error": str(e)}
    finally:
        if target_backend:
            with LOAD_LOCK:
                if BACKEND_LOCAL_LOAD.get(target_backend, 0) > 0:
                    BACKEND_LOCAL_LOAD[target_backend] -= 1
        LOCAL_TASK_QUEUE.remove(current_task)

