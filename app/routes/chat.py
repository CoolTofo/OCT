import json
import uuid
from typing import Any, Callable, Dict

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import CanvasLLMRequest, ChatRequest


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()

    safe_user_id = deps["safe_user_id"]
    load_conversation = deps["load_conversation"]
    new_conversation = deps["new_conversation"]
    save_conversation = deps["save_conversation"]
    display_title = deps["display_title"]
    now_ms = deps["now_ms"]
    selected_model = deps["selected_model"]
    get_api_provider = deps["get_api_provider"]
    is_apimart_provider = deps["is_apimart_provider"]
    resolve_chat_provider = deps["resolve_chat_provider"]
    generate_ai_image = deps["generate_ai_image"]
    save_ai_image_to_output = deps["save_ai_image_to_output"]
    reference_to_data_url = deps["reference_to_data_url"]
    text_from_chat_response = deps["text_from_chat_response"]
    text_delta_from_chat_chunk = deps["text_delta_from_chat_chunk"]
    upstream_message_from_record = deps["upstream_message_from_record"]
    unwrap_apimart_response = deps["unwrap_apimart_response"]
    sse_event = deps["sse_event"]

    image_model = deps["IMAGE_MODEL"]
    system_prompt = deps["SYSTEM_PROMPT"]
    max_history_messages = deps["MAX_HISTORY_MESSAGES"]
    ai_request_timeout = deps["AI_REQUEST_TIMEOUT"]

    @router.post("/api/canvas-llm")
    async def canvas_llm(payload: CanvasLLMRequest):
        chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
        llm_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
        is_apimart = is_apimart_provider(llm_provider)
        payload_system_prompt = (payload.system_prompt or "").strip()
        upstream_messages = [{"role": "system", "content": payload_system_prompt}] if payload_system_prompt else []
        for item in payload.messages[-max_history_messages:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                upstream_messages.append({"role": role, "content": content})
        if payload.images:
            content_parts = [{"type": "text", "text": payload.message}]
            ok_imgs = 0
            for img in payload.images[:8]:
                if not img or not isinstance(img, str):
                    continue
                if img.startswith("/output/") or img.startswith("/assets/"):
                    ref_url = reference_to_data_url({"url": img}, max_size=1024)
                else:
                    ref_url = img
                if not ref_url:
                    continue
                content_parts.append({"type": "image_url", "image_url": {"url": ref_url}})
                ok_imgs += 1
            print(f"[canvas-llm] model={model} provider={payload.provider} text_len={len(payload.message)} images={ok_imgs}/{len(payload.images)}")
            upstream_messages.append({"role": "user", "content": content_parts})
        else:
            upstream_messages.append({"role": "user", "content": payload.message})
        raw = None
        try:
            async with httpx.AsyncClient(timeout=ai_request_timeout) as client:
                req_body = {"model": model, "messages": upstream_messages}
                if is_apimart:
                    req_body["stream"] = False
                response = await client.post(
                    f"{chat_base}/chat/completions",
                    headers=chat_hdrs,
                    json=req_body,
                )
                response.raise_for_status()
                if not response.content:
                    raise HTTPException(status_code=502, detail="Upstream API returned an empty response.")
                raw = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text or ""
            raise HTTPException(status_code=exc.response.status_code, detail=f"Upstream API error: {body}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to request upstream API: {exc}") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to parse upstream response: {exc}") from exc
        try:
            text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
            text = text or "The upstream API returned an empty response."
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to parse response content: {exc}") from exc
        raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else {}
        return {"text": text, "model": model, "raw_usage": raw_data.get("usage")}

    @router.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request, x_user_id: str = Header(default="")):
        user_id = safe_user_id(x_user_id, request)
        conversation = (
            load_conversation(user_id, payload.conversation_id)
            if payload.conversation_id
            else new_conversation(user_id, display_title(payload.message))
        )
        if not conversation.get("messages"):
            conversation["title"] = display_title(payload.message)

        refs = [ref.dict() for ref in payload.reference_images if ref.url]
        user_message = {
            "id": uuid.uuid4().hex,
            "role": "user",
            "content": payload.message,
            "created_at": now_ms(),
            "attachments": refs,
            "mode": payload.mode,
        }
        conversation["messages"].append(user_message)
        conversation["updated_at"] = now_ms()
        save_conversation(user_id, conversation)

        if payload.mode == "image":
            image_provider_id = payload.provider if payload.provider not in {"modelscope"} else "comfly"
            provider = get_api_provider(image_provider_id)
            default_model = (provider.get("image_models") or [image_model])[0]
            model = selected_model(payload.image_model or payload.model, default_model)
            try:
                image_data, raw = await generate_ai_image(payload.message, payload.size, payload.quality, model, refs, provider["id"])
                local_url = await save_ai_image_to_output(image_data, prefix="chat_")
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail=f"Upstream image API error: {exc.response.text}") from exc
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"Upstream image API request failed: {exc}") from exc
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "type": "image",
                "content": payload.message,
                "image_url": local_url,
                "created_at": now_ms(),
                "model": model,
                "raw_usage": raw.get("usage") if isinstance(raw, dict) else None,
            }
        else:
            chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
            conv_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
            conv_is_apimart = is_apimart_provider(conv_provider)
            history = conversation["messages"][-max_history_messages:]
            upstream_messages = [{"role": "system", "content": system_prompt}]
            for item in history:
                msg = upstream_message_from_record(item)
                if msg:
                    upstream_messages.append(msg)
            try:
                async with httpx.AsyncClient(timeout=ai_request_timeout) as client:
                    conv_req_body = {"model": model, "messages": upstream_messages}
                    if conv_is_apimart:
                        conv_req_body["stream"] = False
                    response = await client.post(
                        f"{chat_base}/chat/completions",
                        headers=chat_hdrs,
                        json=conv_req_body,
                    )
                    response.raise_for_status()
                    raw = response.json()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail=f"Upstream API error: {exc.response.text}") from exc
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"Upstream API request failed: {exc}") from exc
            raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else raw
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": text_from_chat_response(raw).strip() or "The upstream API returned an empty response.",
                "created_at": now_ms(),
                "model": model,
                "raw_usage": raw_data.get("usage") if isinstance(raw_data, dict) else None,
            }

        conversation["messages"].append(assistant_message)
        conversation["updated_at"] = now_ms()
        save_conversation(user_id, conversation)
        return {"conversation": conversation, "message": assistant_message}

    @router.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request, x_user_id: str = Header(default="")):
        if payload.mode == "image":
            raise HTTPException(status_code=400, detail="Image mode must use /api/chat.")

        user_id = safe_user_id(x_user_id, request)
        conversation = (
            load_conversation(user_id, payload.conversation_id)
            if payload.conversation_id
            else new_conversation(user_id, display_title(payload.message))
        )
        if not conversation.get("messages"):
            conversation["title"] = display_title(payload.message)

        refs = [ref.dict() for ref in payload.reference_images if ref.url]
        user_message = {
            "id": uuid.uuid4().hex,
            "role": "user",
            "content": payload.message,
            "created_at": now_ms(),
            "attachments": refs,
            "mode": payload.mode,
        }
        conversation["messages"].append(user_message)
        conversation["updated_at"] = now_ms()
        save_conversation(user_id, conversation)

        chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
        history = conversation["messages"][-max_history_messages:]
        upstream_messages = [{"role": "system", "content": system_prompt}]
        for item in history:
            msg = upstream_message_from_record(item)
            if msg:
                upstream_messages.append(msg)

        async def stream():
            content_parts = []
            raw_usage = None
            yield sse_event({"type": "meta", "conversation": conversation})
            try:
                async with httpx.AsyncClient(timeout=ai_request_timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{chat_base}/chat/completions",
                        headers=chat_hdrs,
                        json={"model": model, "messages": upstream_messages, "stream": True},
                    ) as response:
                        if response.status_code >= 400:
                            detail = await response.aread()
                            yield sse_event({"type": "error", "detail": f"Upstream API error: {detail.decode('utf-8', errors='ignore')}"})
                            return
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            if line.startswith("data:"):
                                line = line[5:].strip()
                            if line == "[DONE]":
                                break
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(chunk, dict) and chunk.get("usage"):
                                raw_usage = chunk.get("usage")
                            delta = text_delta_from_chat_chunk(chunk)
                            if delta:
                                content_parts.append(delta)
                                yield sse_event({"type": "delta", "delta": delta})
            except httpx.HTTPError as exc:
                yield sse_event({"type": "error", "detail": f"Upstream API request failed: {exc}"})
                return

            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": "".join(content_parts).strip() or "The upstream API returned an empty response.",
                "created_at": now_ms(),
                "model": model,
                "raw_usage": raw_usage,
            }
            conversation["messages"].append(assistant_message)
            conversation["updated_at"] = now_ms()
            save_conversation(user_id, conversation)
            yield sse_event({"type": "done", "conversation": conversation, "message": assistant_message})

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
