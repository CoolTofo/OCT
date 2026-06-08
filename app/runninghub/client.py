"""RunningHub HTTP client configuration helpers."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict


DEFAULT_BASE_URL = "https://rhtv.runninghub.cn"
DEFAULT_UPLOAD_BASE_URL = "https://www.runninghub.cn"


def base_url(provider: Dict[str, Any] | None = None) -> str:
    provider = provider or {}
    value = str(provider.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    return value or DEFAULT_BASE_URL


def api_base_url(provider: Dict[str, Any] | None = None) -> str:
    value = base_url(provider)
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower()
    if host in {"rhtv.runninghub.cn", "www.runninghub.cn"}:
        return DEFAULT_BASE_URL
    return value


def upload_base_url(provider: Dict[str, Any] | None = None) -> str:
    value = base_url(provider)
    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower()
    if host in {"rhtv.runninghub.cn", "www.runninghub.cn"}:
        return DEFAULT_UPLOAD_BASE_URL
    return value


def headers(api_key: str, base_url_value: str, json_body: bool = True) -> Dict[str, str]:
    parsed = urllib.parse.urlparse(base_url_value)
    result = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if parsed.netloc:
        result["Host"] = parsed.netloc
    if json_body:
        result["Content-Type"] = "application/json"
    return result

