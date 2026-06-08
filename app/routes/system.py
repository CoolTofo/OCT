from fastapi import APIRouter

from app import updater
from app.version import current_version


router = APIRouter()


@router.get("/api/app-info")
def app_info():
    return {
        "version": current_version(),
        "repo_url": updater.GITHUB_REPO_URL,
        "version_url": updater.GITHUB_VERSION_URL,
    }
