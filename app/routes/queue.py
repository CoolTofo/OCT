from fastapi import APIRouter


def create_router(task_queue) -> APIRouter:
    router = APIRouter()

    @router.get("/api/queue_status")
    async def get_queue_status(client_id: str):
        return task_queue.status_for_client(client_id)

    return router
