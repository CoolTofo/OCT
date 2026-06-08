"""API provider normalization utilities.

Keep provider helper logic out of the FastAPI route module so API settings can
grow without making ``main.py`` harder to edit safely.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, Dict, List


SUPPORTED_PROVIDER_PROTOCOLS = {
    "openai",
    "apimart",
    "gemini",
    "holo",
    "seedance",
    "volc_visual",
    "runninghub",
}


def model_list_from_env(env_name: str, primary: str, defaults: List[str]) -> List[str]:
    configured = os.getenv(env_name, "")
    configured_values = [item.strip() for item in configured.split(",") if item.strip()]
    values = configured_values or [primary, *defaults]
    return model_list_from_values(values)


def provider_key_env(provider_id: str) -> str:
    if provider_id == "comfly":
        return "COMFLY_API_KEY"
    if provider_id == "modelscope":
        return "MODELSCOPE_API_KEY"
    return f"API_PROVIDER_{re.sub(r'[^A-Za-z0-9]', '_', provider_id).upper()}_KEY"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return f"********{tail}"


def public_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    key = os.getenv(provider_key_env(provider["id"]), "")
    return {
        **provider,
        "has_key": bool(key),
        "key_preview": mask_secret(key),
        "key_env": provider_key_env(provider["id"]),
    }


def model_list_from_values(values: List[Any] | None) -> List[str]:
    deduped: List[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def normalize_ms_loras(values: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for raw in values or []:
        if not isinstance(raw, dict):
            continue
        lora_id = str(raw.get("id") or "").strip()
        if not lora_id:
            continue
        target_model = str(raw.get("target_model") or raw.get("model") or "").strip()
        if not target_model:
            continue
        key = (target_model, lora_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            strength = float(raw.get("strength", raw.get("default_strength", 0.8)))
        except Exception:
            strength = 0.8
        strength = max(0.0, min(2.0, strength))
        name = re.sub(r"\s+", " ", str(raw.get("name") or "").strip())[:80]
        normalized.append({
            "id": lora_id[:180],
            "name": name or lora_id,
            "target_model": target_model[:180],
            "strength": strength,
            "enabled": bool(raw.get("enabled", True)),
            "note": str(raw.get("note") or "").strip()[:300],
        })
    return normalized


def normalize_endpoint_override(value: Any, label: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    if len(endpoint) > 300 or re.search(r"\s", endpoint):
        raise ValueError(f"{label} is invalid; use a path like /v1/images/edits.")
    if re.match(r"^https?://", endpoint, re.I):
        return endpoint.rstrip("/")
    if not endpoint.startswith("/"):
        raise ValueError(f"{label} must start with /v1/... or be a full http(s) URL.")
    return endpoint


def provider_endpoint_url(provider: Dict[str, Any] | None, key: str, default_path: str, fallback_base_url: str) -> str:
    base_url = str((provider or {}).get("base_url") or fallback_base_url).strip().rstrip("/")
    override = str((provider or {}).get(key) or "").strip()
    if override:
        if re.match(r"^https?://", override, re.I):
            return override.rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{override}"
        return override
    if base_url.endswith("/v1") and default_path.startswith("/v1/"):
        return f"{base_url}{default_path[3:]}"
    if base_url.endswith("/v1beta") and default_path.startswith("/v1beta/"):
        return f"{base_url}{default_path[7:]}"
    return f"{base_url}{default_path}"


def holo_hint(provider: Dict[str, Any] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    provider_id = str(provider.get("id") or "").strip().lower()
    protocol = str(provider.get("protocol") or "").strip().lower()
    name = str(provider.get("name") or "").strip().lower()
    base_url = str(provider.get("base_url") or "").strip().lower()
    return (
        protocol == "holo"
        or provider_id == "holo"
        or provider_id.startswith("holo-")
        or provider_id.startswith("holo_")
        or "holo" in name
        or "dealonhorizon.us" in base_url
    )


def seedance_hint(provider: Dict[str, Any] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    provider_id = str(provider.get("id") or "").strip().lower()
    protocol = str(provider.get("protocol") or "").strip().lower()
    name = str(provider.get("name") or "").strip().lower()
    base_url = str(provider.get("base_url") or "").strip().lower()
    return (
        protocol == "seedance"
        or provider_id == "seedance"
        or provider_id.startswith("seedance-")
        or provider_id.startswith("seedance_")
        or provider_id in {"sd2", "sd20", "sd2-0", "sd2_0"}
        or "seedance" in name
        or "sd2.0" in name
        or "ark.cn-beijing.volces.com" in base_url
    )


def volc_visual_hint(provider: Dict[str, Any] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    provider_id = str(provider.get("id") or "").strip().lower()
    protocol = str(provider.get("protocol") or "").strip().lower()
    name = str(provider.get("name") or "").strip().lower()
    base_url = str(provider.get("base_url") or "").strip().lower()
    return (
        protocol == "volc_visual"
        or provider_id in {"motion-transfer", "motion-transfer-2", "dreamactor", "volc-visual", "volc_visual"}
        or "\u52a8\u4f5c\u8fc1\u79fb" in name
        or "\u52a8\u4f5c\u6a21\u4eff" in name
        or "visual.volcengineapi.com" in base_url
    )


def runninghub_hint(provider: Dict[str, Any] | None) -> bool:
    if not isinstance(provider, dict):
        return False
    provider_id = str(provider.get("id") or "").strip().lower()
    protocol = str(provider.get("protocol") or "").strip().lower()
    name = str(provider.get("name") or "").strip().lower()
    base_url = str(provider.get("base_url") or "").strip().lower()
    return (
        protocol == "runninghub"
        or provider_id == "runninghub"
        or provider_id.startswith("runninghub-")
        or provider_id.startswith("runninghub_")
        or "runninghub" in name
        or "runninghub.cn" in base_url
        or "runninghub.ai" in base_url
    )
