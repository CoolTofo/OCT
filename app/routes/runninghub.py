import asyncio
import json
import mimetypes
import os
import re
import time
import urllib.parse
import uuid
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.runninghub import responses as rh_responses
from app.runninghub import service as rh_service
from app.runninghub.schemas import (
    RunningHubTaskRequest,
    RunningHubWorkflowConvertRequest,
    RunningHubWorkflowPayload,
)


SUCCESS_STATUSES = {"SUCCESS", "SUCCEED", "COMPLETED", "DONE"}
FAILED_STATUSES = {"FAILED", "FAIL", "ERROR"}


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    load_workflows = deps["load_workflows"]
    save_workflows = deps["save_workflows"]
    normalize_workflow = deps["normalize_workflow"]
    fields_from_workflow_json = deps["fields_from_workflow_json"]
    convert_frontend_workflow = deps["convert_frontend_workflow"]
    get_api_provider_exact = deps["get_api_provider_exact"]
    is_runninghub_provider = deps["is_runninghub_provider"]
    runninghub_api_key = deps["runninghub_api_key"]
    runninghub_base_url = deps["runninghub_base_url"]
    runninghub_api_base_url = deps["runninghub_api_base_url"]
    runninghub_upload_base_url = deps["runninghub_upload_base_url"]
    runninghub_headers = deps["runninghub_headers"]
    node_info_from_payload = deps["node_info_from_payload"]
    save_to_history = deps["save_to_history"]
    save_ai_image_to_output = deps["save_ai_image_to_output"]
    save_remote_video_to_output = deps["save_remote_video_to_output"]
    get_global_loop = deps["get_global_loop"]
    manager = deps["manager"]
    now_ms = deps["now_ms"]

    async def localize_results(items):
        images, videos, texts, files = [], [], [], []
        for item in items:
            url = str(item.get("url") or "").strip()
            output_type = str(item.get("outputType") or "").strip().lower()
            if item.get("text"):
                texts.append(str(item.get("text")))
            if not url:
                continue
            if output_type in {"png", "jpg", "jpeg", "webp", "gif"} or re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", url, re.I):
                images.append(await save_ai_image_to_output({"type": "url", "value": url}, prefix="runninghub_"))
            elif output_type in {"mp4", "webm", "mov", "m4v"} or re.search(r"\.(mp4|webm|mov|m4v)(\?|$)", url, re.I):
                videos.append(await save_remote_video_to_output(url, prefix="runninghub_"))
            else:
                files.append(url)
        return images, videos, texts, files

    def broadcast_record(record):
        loop = get_global_loop()
        if loop:
            asyncio.run_coroutine_threadsafe(manager.broadcast_new_image(record), loop)

    async def fetch_remote_workflow_fields(provider, workflow_id: str):
        api_key = runninghub_api_key(provider)
        url = f"{runninghub_base_url(provider)}/api/openapi/getJsonApiFormat"
        body = {"apiKey": api_key, "workflowId": workflow_id}
        timeout = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = None
            raw = {}
            for attempt in range(2):
                try:
                    resp = await client.post(url, headers=runninghub_headers(provider), json=body)
                    try:
                        raw = resp.json()
                    except Exception:
                        raw = {"code": resp.status_code, "message": (resp.text or "RunningHub returned a non-JSON response")[:500]}
                    break
                except httpx.RequestError as exc:
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    message = str(exc).strip() or repr(exc)
                    raise HTTPException(status_code=502, detail=f"RunningHub request failed ({exc.__class__.__name__}): {message}") from exc
            if resp is None:
                raise HTTPException(status_code=502, detail="RunningHub request failed: no response received.")
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"RunningHub HTTP {resp.status_code}: {rh_responses.api_error_text(raw)}")
        if not isinstance(raw, dict) or raw.get("code") not in (None, 0, "0"):
            detail = rh_responses.api_error_text(raw, f"RunningHub workflow fetch failed: {raw}")
            raise HTTPException(status_code=400, detail=detail)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        prompt = data.get("prompt")
        workflow = {}
        if isinstance(prompt, str) and prompt.strip():
            try:
                workflow = json.loads(prompt)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to parse RunningHub workflow JSON: {exc}") from exc
        elif isinstance(prompt, dict):
            workflow = prompt
        fields = fields_from_workflow_json(workflow)
        return {"workflowId": workflow_id, "fields": fields, "workflow": workflow, "raw": raw}

    @router.get("/api/runninghub/workflows")
    async def list_runninghub_workflows():
        return {"workflows": load_workflows()}

    @router.post("/api/runninghub/workflows")
    async def create_runninghub_workflow(payload: RunningHubWorkflowPayload):
        items = load_workflows()
        raw = payload.dict()
        raw["id"] = raw.get("id") or f"rh_{uuid.uuid4().hex[:12]}"
        item = normalize_workflow(raw)
        if any(existing.get("id") == item["id"] for existing in items):
            raise HTTPException(status_code=400, detail="RunningHub workflow id already exists.")
        items.insert(0, item)
        save_workflows(items)
        return {"workflow": item, "workflows": items}

    @router.put("/api/runninghub/workflows/{workflow_id}")
    async def update_runninghub_workflow(workflow_id: str, payload: RunningHubWorkflowPayload):
        items = load_workflows()
        index = next((i for i, item in enumerate(items) if item.get("id") == workflow_id), -1)
        if index < 0:
            raise HTTPException(status_code=404, detail="RunningHub workflow not found.")
        raw = payload.dict()
        raw["id"] = workflow_id
        raw["created_at"] = items[index].get("created_at")
        raw["updated_at"] = now_ms()
        item = normalize_workflow(raw)
        items[index] = item
        save_workflows(items)
        return {"workflow": item, "workflows": items}

    @router.delete("/api/runninghub/workflows/{workflow_id}")
    async def delete_runninghub_workflow(workflow_id: str):
        items = load_workflows()
        next_items = [item for item in items if item.get("id") != workflow_id]
        if len(next_items) == len(items):
            raise HTTPException(status_code=404, detail="RunningHub workflow not found.")
        save_workflows(next_items)
        return {"ok": True, "workflows": next_items}

    @router.post("/api/runninghub/workflow-fields/extract")
    @router.post("/api/runninghub/workflows/extract-fields")
    async def extract_runninghub_fields(payload: Dict[str, Any]):
        workflow = payload.get("workflow") if isinstance(payload, dict) else None
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Workflow JSON is invalid.") from exc
        return {"fields": fields_from_workflow_json(workflow)}

    @router.post("/api/runninghub/workflow-fields/convert")
    @router.post("/api/runninghub/workflows/convert-fields")
    async def convert_runninghub_fields(payload: RunningHubWorkflowConvertRequest):
        return convert_frontend_workflow(payload)

    @router.post("/api/runninghub/workflow-fields/fetch")
    @router.post("/api/runninghub/workflows/fetch")
    async def fetch_runninghub_workflow_fields(payload: Dict[str, Any]):
        workflow_id = str((payload or {}).get("workflowId") or (payload or {}).get("workflow_id") or "").strip()
        provider_id = str((payload or {}).get("provider_id") or "runninghub").strip() or "runninghub"
        if not workflow_id:
            raise HTTPException(status_code=400, detail="workflowId is required.")
        provider = get_api_provider_exact(provider_id)
        if not is_runninghub_provider(provider):
            raise HTTPException(status_code=400, detail="Selected provider is not RunningHub.")
        return await fetch_remote_workflow_fields(provider, workflow_id)

    @router.post("/api/runninghub/upload")
    async def upload_runninghub_files(files: List[UploadFile] = File(...), provider_id: str = "runninghub", fileType: str = "input"):
        provider = get_api_provider_exact(provider_id)
        if not is_runninghub_provider(provider):
            raise HTTPException(status_code=400, detail="Selected provider is not RunningHub.")
        upload_base = runninghub_upload_base_url(provider)
        upload_url = f"{upload_base}/openapi/v2/media/upload/binary"
        headers = runninghub_headers(provider, json_body=False, base_url=upload_base)
        uploaded = []
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            for file in files[:10]:
                content = await file.read()
                if not content:
                    continue
                filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}"
                guessed_type = mimetypes.guess_type(filename)[0] or ""
                content_type = file.content_type or guessed_type or "application/octet-stream"
                if content_type == "application/octet-stream" and guessed_type:
                    content_type = guessed_type
                files_payload = {"file": (filename, content, content_type)}
                try:
                    resp = await client.post(upload_url, headers=headers, files=files_payload)
                except httpx.RequestError as exc:
                    message = str(exc).strip() or repr(exc)
                    raise HTTPException(status_code=502, detail=f"RunningHub upload request failed ({exc.__class__.__name__}): {message}") from exc
                try:
                    raw = resp.json()
                except Exception:
                    raw = {"code": resp.status_code, "msg": resp.text[:500]}
                if resp.status_code >= 400 or (isinstance(raw, dict) and raw.get("code") not in (None, 0)):
                    message = rh_responses.api_error_text(raw, "RunningHub upload failed")
                    raise HTTPException(status_code=resp.status_code if resp.status_code >= 400 else 502, detail=message)
                data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else {}
                uploaded.append({
                    "url": data.get("download_url") or data.get("url") or "",
                    "download_url": data.get("download_url") or "",
                    "fileName": data.get("fileName") or "",
                    "fileType": data.get("type") or data.get("fileType") or fileType or "input",
                    "size": data.get("size") or "",
                    "name": file.filename or "",
                    "raw": raw,
                })
        return {"files": uploaded}

    @router.post("/api/runninghub/tasks")
    async def create_runninghub_task(payload: RunningHubTaskRequest):
        provider = get_api_provider_exact(payload.provider_id or "runninghub")
        if not is_runninghub_provider(provider):
            raise HTTPException(status_code=400, detail="Selected provider is not RunningHub.")
        template = None
        if payload.workflow_local_id:
            template = next((item for item in load_workflows() if item.get("id") == payload.workflow_local_id), None)
        workflow_id = (payload.workflowId or payload.workflow_id or (template or {}).get("workflowId") or "").strip()
        if not workflow_id:
            raise HTTPException(status_code=400, detail="RunningHub workflowId is required.")
        node_info = node_info_from_payload(payload, template=template)
        options = {}
        if template and isinstance(template.get("options"), dict):
            options.update(template.get("options") or {})
        options.update(payload.options or {})
        access_password = (payload.accessPassword or payload.access_password or (template or {}).get("accessPassword") or "").strip()
        retain = payload.retainSeconds if payload.retainSeconds is not None else (template or {}).get("defaultRetainSeconds")

        def build_task_body(current_node_info):
            body = {
                "addMetadata": True,
                "randomSeed": True,
                "nodeInfoList": current_node_info,
                "instanceType": "default",
                "usePersonalQueue": False,
            }
            if access_password:
                body["accessPassword"] = access_password
            if retain:
                try:
                    retain_value = int(retain)
                    if 10 <= retain_value <= 180:
                        body["retainSeconds"] = retain_value
                except Exception:
                    pass
            for key in ("addMetadata", "randomSeed", "webhookUrl", "instanceType", "usePersonalQueue", "retainSeconds"):
                if key in options and options[key] not in ("", None):
                    body[key] = options[key]
            if payload.addMetadata is not None:
                body["addMetadata"] = bool(payload.addMetadata)
            if payload.randomSeed is not None:
                body["randomSeed"] = bool(payload.randomSeed)
            if payload.webhookUrl:
                body["webhookUrl"] = payload.webhookUrl
            if payload.instanceType:
                body["instanceType"] = payload.instanceType
            if payload.usePersonalQueue is not None:
                body["usePersonalQueue"] = bool(payload.usePersonalQueue)
            return body

        api_base = runninghub_api_base_url(provider)
        submit_url = f"{api_base}/openapi/v2/run/workflow/{urllib.parse.quote(workflow_id, safe='')}"

        async def submit_task_body(body):
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                return await client.post(submit_url, headers=runninghub_headers(provider, base_url=api_base), json=body)

        def submit_response_failed(resp, raw) -> bool:
            if resp.status_code >= 400 or not isinstance(raw, dict):
                return True
            if raw.get("code") not in (None, "", 0, "0"):
                return True
            error_code = str(raw.get("errorCode") or raw.get("error_code") or "").strip().upper()
            if error_code and error_code not in {"0", "NONE", "NULL"}:
                return True
            error_message = str(raw.get("errorMessage") or raw.get("error_message") or "").strip()
            return bool(error_message)

        body = build_task_body(node_info)
        resp = await submit_task_body(body)
        try:
            raw = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"RunningHub returned non-JSON response: {resp.text[:500]}") from exc

        dropped_node_info = []
        if submit_response_failed(resp, raw) and rh_responses.node_info_mismatch(raw):
            remote = await fetch_remote_workflow_fields(provider, workflow_id)
            filtered_node_info, dropped_node_info = rh_service.filter_node_info_by_fields(node_info, remote.get("fields") or [])
            if dropped_node_info:
                node_info = filtered_node_info
                body = build_task_body(node_info)
                resp = await submit_task_body(body)
                try:
                    raw = resp.json()
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"RunningHub returned non-JSON response: {resp.text[:500]}") from exc

        if submit_response_failed(resp, raw):
            detail = raw.get("message") or raw.get("msg") or raw.get("errorMessage") or raw if isinstance(raw, dict) else raw
            raise HTTPException(status_code=resp.status_code if resp.status_code >= 400 else 502, detail=detail)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        task_id = str(data.get("taskId") or raw.get("taskId") or "").strip()
        if not task_id:
            raise HTTPException(status_code=502, detail=f"RunningHub did not return taskId: {raw}")
        status = data.get("status") or data.get("taskStatus") or raw.get("status") or "RUNNING"
        result = {
            "task_id": task_id,
            "taskId": task_id,
            "status": status,
            "clientId": data.get("clientId") or raw.get("clientId") or "",
            "promptTips": data.get("promptTips") or raw.get("promptTips") or "",
            "raw": raw,
        }
        if dropped_node_info:
            result["nodeInfoSync"] = {
                "dropped": [
                    {"nodeId": item.get("nodeId") or item.get("node_id") or "", "fieldName": item.get("fieldName") or item.get("field_name") or ""}
                    for item in dropped_node_info
                ]
            }
        items = rh_responses.result_items(raw)
        if str(status or "").upper() in SUCCESS_STATUSES and items:
            images, videos, texts, files = await localize_results(items)
            record = {
                "timestamp": time.time(),
                "type": "runninghub",
                "prompt": (template or {}).get("title") or f"RunningHub {task_id}",
                "images": images,
                "videos": videos,
                "files": files,
                "texts": texts,
                "task_id": task_id,
                "provider_id": provider["id"],
                "provider_name": provider.get("name") or "RunningHub",
                "workflow_id": workflow_id,
                "workflow_local_id": payload.workflow_local_id or "",
                "raw_usage": raw.get("usage") if isinstance(raw, dict) else None,
            }
            if images or videos:
                save_to_history(record)
                broadcast_record(record)
            result.update({"status": "SUCCESS", "results": items, "images": images, "videos": videos, "texts": texts, "files": files, "record": record})
        return result

    @router.get("/api/runninghub/tasks/{task_id}")
    async def get_runninghub_task(task_id: str, provider_id: str = "runninghub", workflow_local_id: str = ""):
        provider = get_api_provider_exact(provider_id or "runninghub")
        if not is_runninghub_provider(provider):
            raise HTTPException(status_code=400, detail="Selected provider is not RunningHub.")
        api_key = runninghub_api_key(provider)
        base = runninghub_api_base_url(provider)
        body = {"taskId": task_id}
        headers = runninghub_headers(provider, base_url=base)
        raw = {}
        status = "RUNNING"
        query_error = ""
        query_timeout = httpx.Timeout(12.0, connect=5.0, read=12.0, write=8.0, pool=5.0)
        async with httpx.AsyncClient(timeout=query_timeout, follow_redirects=True) as client:
            try:
                v2_resp = await client.post(f"{base}/openapi/v2/query", headers=headers, json=body)
                raw = rh_responses.response_json(v2_resp)
                status = rh_responses.task_status(raw)
                if v2_resp.status_code >= 400:
                    query_error = f"RunningHub query HTTP {v2_resp.status_code}: {rh_responses.error_message(raw)}"
            except httpx.RequestError as exc:
                query_error = f"RunningHub query network error ({exc.__class__.__name__}): {str(exc).strip() or repr(exc)}"
                raw = {}
            if not raw or query_error:
                try:
                    legacy_resp = await client.post(f"{base}/task/openapi/outputs", headers=headers, json={"apiKey": api_key, "taskId": task_id})
                    legacy_raw = rh_responses.response_json(legacy_resp)
                    legacy_status = rh_responses.task_status_from_legacy(legacy_raw)
                    if legacy_resp.status_code < 400 or legacy_raw:
                        raw = legacy_raw
                        status = legacy_status
                        if legacy_resp.status_code < 400:
                            query_error = ""
                        elif not query_error:
                            query_error = f"RunningHub legacy query HTTP {legacy_resp.status_code}: {rh_responses.error_message(legacy_raw)}"
                except httpx.RequestError as exc:
                    if not raw:
                        query_error = f"RunningHub legacy query network error ({exc.__class__.__name__}): {str(exc).strip() or repr(exc)}"
        if not raw and query_error:
            return {"task_id": task_id, "status": "QUERY_RETRY", "query_error": query_error, "raw": {}}
        if status in FAILED_STATUSES:
            return {"task_id": task_id, "status": "FAILED", "error": rh_responses.error_message(raw), "raw": raw}
        if status in SUCCESS_STATUSES and not rh_responses.result_items(raw):
            async with httpx.AsyncClient(timeout=query_timeout, follow_redirects=True) as client:
                for _ in range(6):
                    await asyncio.sleep(1.5)
                    try:
                        retry_resp = await client.post(f"{base}/openapi/v2/query", headers=headers, json=body)
                        retry_raw = retry_resp.json()
                    except Exception:
                        continue
                    retry_status = str(retry_raw.get("status") or "").upper() or status
                    raw = retry_raw
                    status = retry_status
                    has_results = bool(rh_responses.result_items(raw))
                    if status in FAILED_STATUSES or has_results or status not in SUCCESS_STATUSES:
                        break
        if status in FAILED_STATUSES:
            return {"task_id": task_id, "status": "FAILED", "error": rh_responses.error_message(raw), "raw": raw}
        if status not in SUCCESS_STATUSES:
            return {"task_id": task_id, "status": status or "RUNNING", "raw": raw}
        items = rh_responses.result_items(raw)
        if not items:
            return {"task_id": task_id, "status": "RUNNING", "message": "RunningHub task succeeded; waiting for result files.", "raw": raw}
        images, videos, texts, files = await localize_results(items)
        template = next((item for item in load_workflows() if item.get("id") == workflow_local_id), None) if workflow_local_id else None
        record = {
            "timestamp": time.time(),
            "type": "runninghub",
            "prompt": (template or {}).get("title") or f"RunningHub {task_id}",
            "images": images,
            "videos": videos,
            "files": files,
            "texts": texts,
            "task_id": task_id,
            "provider_id": provider["id"],
            "provider_name": provider.get("name") or "RunningHub",
            "workflow_id": (template or {}).get("workflowId") or "",
            "workflow_local_id": workflow_local_id,
            "raw_usage": raw.get("usage") if isinstance(raw, dict) else None,
        }
        if images or videos:
            save_to_history(record)
            broadcast_record(record)
        return {"task_id": task_id, "status": "SUCCESS", "results": items, "images": images, "videos": videos, "texts": texts, "files": files, "record": record, "raw": raw}

    return router


def node_info_from_payload(payload: RunningHubTaskRequest, template=None):
    node_info = payload.nodeInfoList or payload.node_info_list or []
    cleaned = []
    template_fields = [
        rh_service.normalize_field(field, i)
        for i, field in enumerate((template or {}).get("fields") or [])
        if isinstance(field, dict)
    ]
    template_field_by_key = {
        (str(field.get("nodeId") or ""), str(field.get("fieldName") or "")): field
        for field in template_fields
    }
    for item in node_info:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("nodeId") or item.get("node_id") or "").strip()
        field_name = str(item.get("fieldName") or item.get("field_name") or "").strip()
        if node_id and field_name:
            field = template_field_by_key.get((node_id, field_name), {"nodeId": node_id, "fieldName": field_name})
            value = item.get("fieldValue", item.get("field_value", ""))
            cleaned.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": rh_service.coerce_value(value, field, use_default_for_empty=False)})
    if cleaned:
        return cleaned
    fields = [
        rh_service.normalize_field(field.dict() if hasattr(field, "dict") else field, i)
        for i, field in enumerate(payload.fields or [])
    ]
    if not fields and template:
        fields = template_fields
    values = payload.values or {}
    for field in fields:
        node_id = str(field.get("nodeId") or "").strip()
        field_name = str(field.get("fieldName") or "").strip()
        if not node_id or not field_name:
            continue
        field_id = field.get("id")
        dotted_key = f"{node_id}.{field_name}"
        explicit = False
        if field_id in values:
            value = values.get(field_id)
            explicit = True
        elif dotted_key in values:
            value = values.get(dotted_key)
            explicit = True
        else:
            value = field.get("default", "")
        cleaned.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": rh_service.coerce_value(value, field, use_default_for_empty=not explicit)})
    return cleaned
