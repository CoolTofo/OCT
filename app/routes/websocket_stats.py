"""WebSocket routes for realtime status updates."""

import json
from typing import Any, Callable, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


def create_router(deps: Dict[str, Any]) -> APIRouter:
    router = APIRouter()
    manager = deps["manager"]
    set_global_loop: Callable[[Any], None] = deps["set_global_loop"]
    get_running_loop: Callable[[], Any] = deps["get_running_loop"]

    @router.on_event("startup")
    async def startup_event():
        set_global_loop(get_running_loop())

    @router.websocket("/ws/stats")
    async def websocket_endpoint(websocket: WebSocket, client_id: str = None):
        await manager.connect(websocket, client_id)
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            await manager.disconnect(websocket, client_id)
        except Exception as exc:
            print(f"WS Error: {exc}")
            await manager.disconnect(websocket, client_id)

    return router
