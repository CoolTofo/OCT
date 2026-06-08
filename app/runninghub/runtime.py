"""RunningHub provider runtime and workflow storage helpers."""

import os
from typing import Any, Dict

from fastapi import HTTPException

from app.runninghub import client as rh_client
from app.runninghub import converter as rh_converter
from app.runninghub import extractors as rh_extractors
from app.runninghub import service as rh_service
from app.runninghub import storage as rh_storage

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

def runninghub_base_url(provider=None):
    provider = provider or get_api_provider_exact("runninghub")
    base_url = rh_client.base_url(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail="RunningHub Base URL is not configured.")
    return base_url

def runninghub_api_base_url(provider=None):
    provider = provider or get_api_provider_exact("runninghub")
    return rh_client.api_base_url(provider)

def runninghub_upload_base_url(provider=None):
    provider = provider or get_api_provider_exact("runninghub")
    return rh_client.upload_base_url(provider)

def runninghub_api_key(provider):
    api_key = os.getenv(provider_key_env(provider["id"]), "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="RunningHub API Key is not configured in API settings.")
    return api_key

def runninghub_headers(provider, json_body=True, base_url=None):
    api_key = runninghub_api_key(provider)
    return rh_client.headers(api_key, base_url or runninghub_base_url(provider), json_body=json_body)

def load_runninghub_workflows():
    return rh_storage.load_workflows(RUNNINGHUB_WORKFLOWS_FILE, normalize_runninghub_workflow)

def save_runninghub_workflows(items):
    rh_storage.save_workflows(RUNNINGHUB_WORKFLOWS_FILE, DATA_DIR, items, GLOBAL_CONFIG_LOCK)

# RunningHub field extraction and conversion live in app.runninghub.* modules.
runninghub_fields_from_workflow_json = rh_extractors.fields_from_workflow_json


def normalize_runninghub_workflow(raw):
    return rh_service.normalize_workflow(raw, now_ms())


convert_runninghub_frontend_workflow = rh_converter.convert_frontend_workflow

