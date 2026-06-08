import json
import os
import re
from threading import Lock
from typing import Any, Dict, List

from app import providers as provider_utils


PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")


def default_api_providers(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "id": "modelscope",
            "name": "ModelScope",
            "base_url": ctx["modelscope_chat_base_url"],
            "protocol": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": ctx["modelscope_image_models"],
            "chat_models": ctx["modelscope_chat_models"],
            "video_models": ctx["modelscope_video_models"],
            "ms_loras": ctx["modelscope_default_loras"],
            "ms_defaults_version": ctx["modelscope_defaults_version"],
        },
        {
            "id": "holo",
            "name": "W Project HOLO",
            "base_url": "https://api.dealonhorizon.us",
            "protocol": "holo",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": ctx["holo_default_image_models"],
            "chat_models": [],
            "video_models": ctx["holo_default_video_models"],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "motion-transfer",
            "name": "Motion Transfer 2.0",
            "base_url": ctx["volc_visual_default_base_url"],
            "protocol": "volc_visual",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [ctx["volc_visual_motion_model"]],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "runninghub",
            "name": "RunningHub",
            "base_url": ctx["runninghub_default_base_url"],
            "protocol": "runninghub",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
    ]


def merge_default_api_providers(providers: List[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    merged = [dict(item) for item in providers]
    defaults = default_api_providers(ctx)
    for default in defaults:
        current = next((item for item in merged if item.get("id") == default["id"]), None)
        if not current:
            merged.append(dict(default))
            continue
        if not current.get("base_url"):
            current["base_url"] = default.get("base_url", "")
        if not current.get("name"):
            current["name"] = default.get("name", default["id"])
        if not current.get("protocol"):
            current["protocol"] = default.get("protocol", "openai")

    current = next((item for item in merged if item.get("id") == "modelscope"), None)
    if current:
        seeded_version = int(current.get("ms_defaults_version") or 0)
        if seeded_version < ctx["modelscope_defaults_version"]:
            current["image_models"] = provider_utils.model_list_from_values([
                *ctx["modelscope_default_image_models"],
                *(current.get("image_models") or []),
            ])
            current["chat_models"] = provider_utils.model_list_from_values([
                *ctx["modelscope_default_chat_models"],
                *(current.get("chat_models") or []),
            ])
            current["ms_loras"] = provider_utils.normalize_ms_loras([
                *ctx["modelscope_default_loras"],
                *(current.get("ms_loras") or []),
            ])
            current["ms_defaults_version"] = ctx["modelscope_defaults_version"]

    for holo_current in [item for item in merged if provider_utils.holo_hint(item)]:
        if not holo_current.get("base_url"):
            holo_current["base_url"] = "https://api.dealonhorizon.us"
        if not holo_current.get("name"):
            holo_current["name"] = "W Project HOLO"
        holo_current["protocol"] = "holo"
        holo_current["image_generation_endpoint"] = ""
        holo_current["image_edit_endpoint"] = ""
        holo_current["image_models"] = provider_utils.model_list_from_values([
            *(holo_current.get("image_models") or []),
            *ctx["holo_default_image_models"],
        ])
        holo_current["video_models"] = provider_utils.model_list_from_values([
            *(holo_current.get("video_models") or []),
            *ctx["holo_default_video_models"],
        ])

    for seedance_current in [item for item in merged if provider_utils.seedance_hint(item)]:
        if not seedance_current.get("base_url"):
            seedance_current["base_url"] = ctx["seedance_default_base_url"]
        if not seedance_current.get("name"):
            seedance_current["name"] = "Seedance 2.0"
        seedance_current["protocol"] = "seedance"
        seedance_current["image_generation_endpoint"] = ""
        seedance_current["image_edit_endpoint"] = ""
        seedance_current["video_models"] = provider_utils.model_list_from_values([
            *(seedance_current.get("video_models") or []),
            *ctx["seedance_default_video_models"],
        ])

    for visual_current in [item for item in merged if provider_utils.volc_visual_hint(item)]:
        if not visual_current.get("base_url"):
            visual_current["base_url"] = ctx["volc_visual_default_base_url"]
        if not visual_current.get("name"):
            visual_current["name"] = "Motion Transfer 2.0"
        visual_current["protocol"] = "volc_visual"
        visual_current["image_generation_endpoint"] = ""
        visual_current["image_edit_endpoint"] = ""
        visual_current["video_models"] = provider_utils.model_list_from_values([
            *(visual_current.get("video_models") or []),
            ctx["volc_visual_motion_model"],
        ])

    for rh_current in [item for item in merged if provider_utils.runninghub_hint(item)]:
        if not rh_current.get("base_url"):
            rh_current["base_url"] = ctx["runninghub_default_base_url"]
        if not rh_current.get("name"):
            rh_current["name"] = "RunningHub"
        rh_current["protocol"] = "runninghub"
        rh_current["image_generation_endpoint"] = ""
        rh_current["image_edit_endpoint"] = ""
        rh_current["image_models"] = []
        rh_current["chat_models"] = []
        rh_current["video_models"] = []
    return merged


def normalize_provider(item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    provider_id = str(item.get("id") or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise ValueError(f"Invalid API provider ID: {provider_id or '(empty)'}")
    name = re.sub(r"\s+", " ", str(item.get("name") or provider_id).strip())[:60] or provider_id
    base_url = str(item.get("base_url") or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://", base_url):
        raise ValueError(f"{name} Base URL must start with http:// or https://.")
    protocol = str(item.get("protocol") or "openai").strip().lower()
    if protocol not in provider_utils.SUPPORTED_PROVIDER_PROTOCOLS:
        protocol = "openai"

    probe = {"id": provider_id, "name": name, "base_url": base_url, "protocol": protocol}
    holo_hint = provider_utils.holo_hint(probe)
    seedance_hint = provider_utils.seedance_hint(probe)
    volc_visual_hint = provider_utils.volc_visual_hint(probe)
    runninghub_hint = provider_utils.runninghub_hint(probe)
    if holo_hint:
        protocol = "holo"
    elif seedance_hint:
        protocol = "seedance"
    elif volc_visual_hint:
        protocol = "volc_visual"
    elif runninghub_hint:
        protocol = "runninghub"

    image_generation_endpoint = provider_utils.normalize_endpoint_override(item.get("image_generation_endpoint"), "image generation endpoint")
    image_edit_endpoint = provider_utils.normalize_endpoint_override(item.get("image_edit_endpoint"), "image edit endpoint")
    image_models = provider_utils.model_list_from_values(item.get("image_models") or [])
    video_models = provider_utils.model_list_from_values(item.get("video_models") or [])
    if holo_hint:
        image_generation_endpoint = ""
        image_edit_endpoint = ""
        image_models = provider_utils.model_list_from_values([*image_models, *ctx["holo_default_image_models"]])
        video_models = provider_utils.model_list_from_values([*video_models, *ctx["holo_default_video_models"]])
    if seedance_hint:
        image_generation_endpoint = ""
        image_edit_endpoint = ""
        video_models = provider_utils.model_list_from_values([*video_models, *ctx["seedance_default_video_models"]])
    if volc_visual_hint:
        image_generation_endpoint = ""
        image_edit_endpoint = ""
        video_models = provider_utils.model_list_from_values([*video_models, ctx["volc_visual_motion_model"]])
    if runninghub_hint:
        image_generation_endpoint = ""
        image_edit_endpoint = ""
        image_models = []
        video_models = []
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "protocol": protocol,
        "image_generation_endpoint": image_generation_endpoint,
        "image_edit_endpoint": image_edit_endpoint,
        "enabled": bool(item.get("enabled", True)),
        "primary": bool(item.get("primary", False)),
        "image_models": image_models,
        "chat_models": provider_utils.model_list_from_values(item.get("chat_models") or []),
        "video_models": video_models,
        "ms_loras": provider_utils.normalize_ms_loras(item.get("ms_loras") or []),
        "ms_defaults_version": int(item.get("ms_defaults_version") or 0),
    }


def load_api_providers(path: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    defaults = default_api_providers(ctx)
    if not os.path.exists(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        providers = [normalize_provider(item, ctx) for item in raw if isinstance(item, dict)]
        return merge_default_api_providers(providers or defaults, ctx)
    except Exception as exc:
        print(f"Failed to load API provider config: {exc}")
        return defaults


def save_api_providers(path: str, data_dir: str, providers: List[Dict[str, Any]], lock: Any = None) -> None:
    os.makedirs(data_dir, exist_ok=True)
    guard = lock or Lock()
    with guard:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(providers, f, ensure_ascii=False, indent=2)


def get_primary_provider_id(providers: List[Dict[str, Any]] | None) -> str:
    providers = providers or []
    primary = next((p for p in providers if p.get("primary") and p.get("enabled", True)), None)
    if primary:
        return primary["id"]
    non_ms = next((p for p in providers if p["id"] != "modelscope" and p.get("enabled", True)), None)
    if non_ms:
        return non_ms["id"]
    return providers[0]["id"] if providers else "modelscope"
