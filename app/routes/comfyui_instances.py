from typing import Callable, Dict, List

from fastapi import APIRouter, HTTPException

from app.comfyui.schemas import ComfyInstancesPayload


def create_router(deps: Dict[str, Callable]) -> APIRouter:
    router = APIRouter()
    get_instances: Callable[[], List[str]] = deps["get_instances"]
    discover_local_instances: Callable[[], List[str]] = deps["discover_local_instances"]
    motion_transfer_fields: Callable[[], list] = deps["motion_transfer_fields"]
    save_instances: Callable[[List[str]], List[str]] = deps["save_instances"]

    @router.get("/api/comfyui/instances")
    def get_comfyui_instances():
        return {"instances": get_instances(), "active_instances": discover_local_instances()}

    @router.get("/api/motion-transfer/local-workflow")
    def get_motion_transfer_local_workflow():
        return {
            "workflow": "MotionTransfer.json",
            "fields": motion_transfer_fields(),
            "active_comfy_instances": discover_local_instances(),
        }

    @router.put("/api/comfyui/instances")
    def save_comfyui_instances(payload: ComfyInstancesPayload):
        try:
            instances = save_instances(payload.instances)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to write env: {exc}") from exc
        return {"instances": instances}

    return router
