import urllib.error

from fastapi import APIRouter, HTTPException

from app import updater
from app.paths import BASE_DIR, DATA_DIR
from app.schemas import RollbackRequest, UpdateRequest


router = APIRouter()


@router.get("/api/update-status")
def update_status():
    try:
        return updater.update_status(BASE_DIR)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab version check failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot connect to GitLab: {exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update check failed: {exc}") from exc


@router.post("/api/update-from-gitlab")
def update_from_gitlab(req: UpdateRequest = UpdateRequest()):
    try:
        return updater.run_update(
            BASE_DIR,
            DATA_DIR,
            auto_restart=req.auto_restart,
            restart_delay=req.restart_delay,
        )
    except updater.UpdateBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab download failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot connect to GitLab: {exc.reason}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}") from exc


@router.post("/api/update-from-github")
def update_from_github_compat(req: UpdateRequest = UpdateRequest()):
    return update_from_gitlab(req)


@router.get("/api/update-backups")
def get_update_backups():
    return {"backups": updater.list_update_backups(DATA_DIR)}


@router.post("/api/update-rollback")
def rollback_update(req: RollbackRequest):
    try:
        return updater.rollback_update(
            BASE_DIR,
            DATA_DIR,
            req.name,
            auto_restart=req.auto_restart,
            restart_delay=req.restart_delay,
        )
    except updater.UpdateBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}") from exc
