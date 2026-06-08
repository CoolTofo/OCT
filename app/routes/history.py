from fastapi import APIRouter

from app import history_store
from app.media_store import output_file_from_url
from app.paths import HISTORY_FILE
from app.schemas import DeleteHistoryRequest


router = APIRouter()


@router.get("/api/history")
async def get_history_api(type: str = None):
    return history_store.list_records(HISTORY_FILE, type)


@router.post("/api/history/delete")
async def delete_history(req: DeleteHistoryRequest):
    return history_store.delete_record(HISTORY_FILE, req.timestamp, output_file_from_url)
