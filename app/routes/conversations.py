import os
from typing import Callable, Dict

from fastapi import APIRouter, Header, Request

from app.schemas import ConversationCreateRequest


def create_router(deps: Dict[str, Callable]) -> APIRouter:
    router = APIRouter()
    safe_user_id = deps["safe_user_id"]
    list_conversations = deps["list_conversations"]
    new_conversation = deps["new_conversation"]
    load_conversation = deps["load_conversation"]
    conversation_path = deps["conversation_path"]

    @router.get("/api/conversations")
    async def conversations(request: Request, x_user_id: str = Header(default="")):
        user_id = safe_user_id(x_user_id, request)
        return {"user_id": user_id, "conversations": list_conversations(user_id)}

    @router.post("/api/conversations")
    async def create_conversation(payload: ConversationCreateRequest, request: Request, x_user_id: str = Header(default="")):
        user_id = safe_user_id(x_user_id, request)
        return {"conversation": new_conversation(user_id, payload.title)}

    @router.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, request: Request, x_user_id: str = Header(default="")):
        user_id = safe_user_id(x_user_id, request)
        return {"conversation": load_conversation(user_id, conversation_id)}

    @router.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, request: Request, x_user_id: str = Header(default="")):
        user_id = safe_user_id(x_user_id, request)
        path = conversation_path(user_id, conversation_id)
        if os.path.exists(path):
            os.remove(path)
        return {"ok": True}

    return router
