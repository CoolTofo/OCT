import os
import re
from typing import Any, Callable, Dict

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class TestConnectionPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    supported_protocols = set(deps["supported_protocols"])
    provider_key_env: Callable[[str], str] = deps["provider_key_env"]
    provider_protocol: Callable[[dict], str] = deps["provider_protocol"]
    get_api_provider_exact: Callable[[str], dict] = deps["get_api_provider_exact"]
    runninghub_api_base_url: Callable[[dict], str] = deps["runninghub_api_base_url"]
    holo_api_url: Callable[[dict, str], str] = deps["holo_api_url"]
    volc_visual_default_base_url = deps["volc_visual_default_base_url"]
    volc_visual_motion_model = deps["volc_visual_motion_model"]
    seedance_default_video_models = deps["seedance_default_video_models"]

    def protocol_from_payload(payload):
        protocol = str(getattr(payload, "protocol", "") or "openai").strip().lower()
        return protocol if protocol in supported_protocols else "openai"

    def upstream_models_url(base_url: str, protocol: str):
        if protocol == "volc_visual":
            return base_url.rstrip("/") or volc_visual_default_base_url
        if protocol == "gemini":
            return f"{base_url}/models" if base_url.endswith("/v1beta") else f"{base_url}/v1beta/models"
        if protocol == "seedance":
            return f"{base_url.rstrip('/')}/models"
        return f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"

    def upstream_model_headers(api_key: str, protocol: str):
        if protocol == "gemini":
            return {"x-goog-api-key": api_key, "Accept": "application/json"}
        return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    def classify_upstream_model(mid, protocol="openai"):
        lc = str(mid or "").lower()
        video_keys = ["veo", "sora", "wan2", "wanx", "doubao-seedance", "doubao-1", "kling", "hailuo", "video", "t2v-", "i2v-", "s2v", "seedance"]
        image_keys = ["banana", "image", "images", "dalle", "dall-e", "imagen", "flux", "stable", "sdxl", "midjourney", "nano-banana", "ideogram", "fal-ai", "z-image", "qwen-image", "klein", "gpt-image", "gemini-3"]
        if protocol == "holo":
            if any(key in lc for key in video_keys):
                return "video"
            if any(key in lc for key in image_keys):
                return "image"
            return "image"
        if any(key in lc for key in video_keys):
            return "video"
        if any(key in lc for key in image_keys):
            return "image"
        return "chat"

    def parse_upstream_models(raw, protocol="openai"):
        if isinstance(raw, list):
            items = raw
        else:
            items = raw.get("data") if isinstance(raw, dict) else None
        if not items and isinstance(raw, dict):
            items = raw.get("models") or raw.get("list") or raw.get("items") or []
        if not isinstance(items, list):
            items = []
        ids = []
        for item in items:
            if isinstance(item, str):
                mid = item
            elif isinstance(item, dict):
                mid = item.get("id") or item.get("name") or item.get("model")
            else:
                mid = ""
            if mid:
                mid = str(mid)
                if protocol == "gemini" and mid.startswith("models/"):
                    mid = mid[len("models/"):]
                ids.append(mid)
        ids = sorted(set(ids))
        grouped = {"image": [], "chat": [], "video": []}
        for mid in ids:
            grouped[classify_upstream_model(mid, protocol)].append(mid)
        return grouped, ids

    async def fetch_models_from_upstream(base_url: str, api_key: str, protocol: str = "openai"):
        base_url = (base_url or "").strip().rstrip("/")
        if not base_url:
            raise HTTPException(status_code=400, detail="Base URL is required.")
        if not re.match(r"^https?://", base_url):
            raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://.")
        api_key = (api_key or "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required. Fill it in or save the provider first.")
        protocol = protocol if protocol in supported_protocols else "openai"
        if protocol == "volc_visual":
            return {"total": 1, "image_models": [], "chat_models": [], "video_models": [volc_visual_motion_model], "all": [volc_visual_motion_model]}
        if protocol == "seedance":
            return {"total": len(seedance_default_video_models), "image_models": [], "chat_models": [], "video_models": seedance_default_video_models, "all": seedance_default_video_models}
        if protocol == "runninghub":
            return {"total": 0, "image_models": [], "chat_models": [], "video_models": [], "all": []}
        url = upstream_models_url(base_url, protocol)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=upstream_model_headers(api_key, protocol))
                if resp.status_code >= 400:
                    endpoint_label = "/v1beta/models" if protocol == "gemini" else "/v1/models"
                    raise HTTPException(status_code=resp.status_code, detail=f"Upstream {endpoint_label} request failed: {resp.text[:300]}")
                raw = resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch upstream model list: {exc}") from exc
        grouped, ids = parse_upstream_models(raw, protocol)
        return {"total": len(ids), "image_models": grouped["image"], "chat_models": grouped["chat"], "video_models": grouped["video"], "all": ids}

    @router.post("/api/providers/test-connection")
    async def test_provider_connection(payload: TestConnectionPayload):
        base_url = (payload.base_url or "").strip().rstrip("/")
        if not base_url:
            raise HTTPException(status_code=400, detail="Base URL is required.")
        if not re.match(r"^https?://", base_url):
            raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://.")
        api_key = (payload.api_key or "").strip()
        if not api_key and payload.provider_id:
            api_key = os.getenv(provider_key_env(payload.provider_id), "")
        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required. Fill it in or save the provider first.")
        protocol = protocol_from_payload(payload)
        url = upstream_models_url(base_url, protocol)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if protocol == "volc_visual":
                    return {
                        "ok": True,
                        "status": 200,
                        "model_count": 1,
                        "image_models": [],
                        "chat_models": [],
                        "video_models": [volc_visual_motion_model],
                        "all": [volc_visual_motion_model],
                        "message": "Motion Transfer 2.0 uses signed Volcengine Visual API requests. Save AK:SK, then submit the task from the Motion Transfer panel.",
                    }
                if protocol == "runninghub":
                    probe_base = runninghub_api_base_url({"id": payload.provider_id or "runninghub", "base_url": base_url, "protocol": "runninghub"})
                    probe_url = f"{probe_base}/openapi/v2/query"
                    resp = await client.post(probe_url, headers=upstream_model_headers(api_key, protocol), json={"taskId": "healthcheck_probe_do_not_submit"})
                    if resp.status_code in {401, 403}:
                        return {"ok": False, "status": resp.status_code, "message": "RunningHub API Key is invalid or unauthorized."}
                    if resp.status_code < 500:
                        return {"ok": True, "status": resp.status_code, "model_count": 0, "image_models": [], "chat_models": [], "video_models": [], "all": [], "message": "RunningHub endpoint reachable. Models are managed by workflow templates."}
                    return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
                if protocol == "seedance":
                    probe_url = f"{base_url.rstrip('/')}/contents/generations/tasks/healthcheck_probe_do_not_submit"
                    resp = await client.get(probe_url, headers=upstream_model_headers(api_key, protocol))
                    if resp.status_code in {400, 404}:
                        return {"ok": True, "status": resp.status_code, "model_count": len(seedance_default_video_models), "image_models": [], "chat_models": [], "video_models": seedance_default_video_models, "all": seedance_default_video_models, "message": "Seedance task endpoint is reachable; using default model list."}
                    if resp.status_code in {401, 403}:
                        return {"ok": False, "status": resp.status_code, "message": "API Key is invalid or lacks Seedance permission."}
                    if resp.status_code >= 400:
                        return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
                    return {"ok": True, "status": resp.status_code, "model_count": len(seedance_default_video_models), "image_models": [], "chat_models": [], "video_models": seedance_default_video_models, "all": seedance_default_video_models}
                if protocol == "holo":
                    provider = {"id": payload.provider_id or "holo", "name": "W Project HOLO", "base_url": base_url, "protocol": "holo"}
                    health_url = holo_api_url(provider, "/health")
                    resp = await client.get(health_url, headers=upstream_model_headers(api_key, protocol))
                    if resp.status_code >= 400:
                        return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
                    model_resp = await client.get(upstream_models_url(base_url, protocol), headers=upstream_model_headers(api_key, protocol))
                    grouped, ids = ({"image": [], "chat": [], "video": []}, [])
                    if model_resp.status_code < 400:
                        model_data = model_resp.json() if model_resp.text else {}
                        grouped, ids = parse_upstream_models(model_data, protocol)
                    return {"ok": True, "status": resp.status_code, "model_count": len(ids), "image_models": grouped["image"], "chat_models": grouped["chat"], "video_models": grouped["video"], "all": ids}
                resp = await client.get(url, headers=upstream_model_headers(api_key, protocol))
            if resp.status_code >= 400:
                return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
            data = resp.json() if resp.text else {}
            grouped, ids = parse_upstream_models(data, protocol)
            return {"ok": True, "status": resp.status_code, "model_count": len(ids), "image_models": grouped["image"], "chat_models": grouped["chat"], "video_models": grouped["video"], "all": ids}
        except httpx.HTTPError as exc:
            return {"ok": False, "status": 0, "message": str(exc)[:300]}

    @router.post("/api/providers/probe-async")
    async def probe_async_endpoint(payload: TestConnectionPayload):
        base_url = (payload.base_url or "").strip().rstrip("/")
        if not base_url:
            raise HTTPException(status_code=400, detail="Please enter the request base URL.")
        api_key = (payload.api_key or "").strip()
        if not api_key and payload.provider_id:
            api_key = os.getenv(provider_key_env(payload.provider_id), "")
        if not api_key:
            raise HTTPException(status_code=400, detail="Please enter or save the API Key.")
        tasks_base = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
        probe_url = f"{tasks_base}/tasks/healthcheck_probe_do_not_submit"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(probe_url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            status_code = resp.status_code
            err_msg = ""
            if isinstance(body, dict):
                err = body.get("error") or {}
                err_msg = str(err.get("message") if isinstance(err, dict) else err or "").lower()
            if status_code == 400 and "invalid task id" in err_msg:
                return {"ok": True, "status_code": status_code, "message": "Async task endpoint is available and the API Key was accepted.", "raw": body}
            if status_code in (401, 403):
                return {"ok": False, "status_code": status_code, "message": "API Key is invalid or unauthorized.", "raw": body}
            if status_code == 404:
                return {"ok": False, "status_code": status_code, "message": "Provider does not support the /v1/tasks/ endpoint; it may not use the APIMart async protocol.", "raw": body}
            if 400 <= status_code < 500:
                return {"ok": None, "status_code": status_code, "message": f"Endpoint returned {status_code}; inspect the raw response.", "raw": body}
            if status_code < 300:
                return {"ok": True, "status_code": status_code, "message": f"Endpoint returned {status_code}; unexpected success.", "raw": body}
            return {"ok": False, "status_code": status_code, "message": f"Server error {status_code}", "raw": body}
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc

    @router.post("/api/providers/fetch-models")
    async def fetch_upstream_models_from_payload(payload: TestConnectionPayload):
        api_key = (payload.api_key or "").strip()
        if not api_key and payload.provider_id:
            api_key = os.getenv(provider_key_env(payload.provider_id), "")
        return await fetch_models_from_upstream(payload.base_url, api_key, protocol_from_payload(payload))

    @router.get("/api/providers/{provider_id}/fetch-models")
    async def fetch_upstream_models(provider_id: str):
        provider = get_api_provider_exact(provider_id)
        api_key = os.getenv(provider_key_env(provider["id"]), "")
        if not api_key:
            raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider_id} API key is not configured.")
        return await fetch_models_from_upstream(provider.get("base_url") or "", api_key, provider_protocol(provider))

    return router
