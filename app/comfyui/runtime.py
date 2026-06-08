"""ComfyUI output download and failure parsing helpers."""

import json
import os
import shutil
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict

_DEPS: Dict[str, Any] = {}


def configure(deps: Dict[str, Any]) -> None:
    _DEPS.clear()
    _DEPS.update(deps)
    globals().update(deps)

def download_image(comfy_address, comfy_url_path, prefix="studio_"):
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    local_path = output_path_for(filename, "output")
    full_url = f"http://{comfy_address}{comfy_url_path}"
    try:
        with urllib.request.urlopen(full_url) as response, open(local_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return output_url_for(filename, "output")
    except Exception as e:
        print(f"Failed to download image: {e}")
        if comfy_url_path.startswith("/view"):
            return comfy_url_path.replace("/view", "/api/view", 1)
        return full_url

def comfy_output_extension(item):
    filename = str((item or {}).get("filename") or "")
    ext = os.path.splitext(filename)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".m4v", ".gif"}:
        return ext
    fmt = str((item or {}).get("format") or "").lower()
    if "webm" in fmt:
        return ".webm"
    if "quicktime" in fmt or "mov" in fmt:
        return ".mov"
    if "mp4" in fmt or "h264" in fmt or "video" in fmt:
        return ".mp4"
    return ".png"

def is_video_output_item(item):
    ext = comfy_output_extension(item)
    fmt = str((item or {}).get("format") or "").lower()
    return ext in {".mp4", ".webm", ".mov", ".m4v"} or "video" in fmt

def download_comfy_output(comfy_address, item, prefix="studio_"):
    ext = comfy_output_extension(item)
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext}"
    local_path = output_path_for(filename, "output")
    subfolder = urllib.parse.quote(str(item.get("subfolder") or ""))
    file_type = urllib.parse.quote(str(item.get("type") or "output"))
    comfy_url_path = f"/view?filename={urllib.parse.quote(str(item['filename']))}&subfolder={subfolder}&type={file_type}"
    full_url = f"http://{comfy_address}{comfy_url_path}"
    try:
        with urllib.request.urlopen(full_url) as response, open(local_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return output_url_for(filename, "output")
    except Exception as e:
        print(f"Failed to download ComfyUI output: {e}")
        if comfy_url_path.startswith("/view"):
            return comfy_url_path.replace("/view", "/api/view", 1)
        return full_url


def get_comfy_history(comfy_address, prompt_id):
    try:
        with urllib.request.urlopen(f"http://{comfy_address}/history/{prompt_id}") as response:
            return json.loads(response.read())
    except Exception as e:
        return {}

def describe_comfy_failure(history_data):
    status = (history_data or {}).get("status") or {}
    messages = status.get("messages") or []
    details = []
    for item in messages:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        event, payload = item[0], item[1]
        if not isinstance(payload, dict):
            continue
        event_name = str(event or "")
        if "error" not in event_name and not payload.get("exception_message"):
            continue
        node_id = payload.get("node_id") or payload.get("node") or payload.get("current_node")
        node_type = payload.get("node_type") or payload.get("class_type")
        exc = payload.get("exception_message") or payload.get("message") or payload.get("error")
        if exc:
            if node_id or node_type:
                details.append(f"Node {node_id or '?'} {node_type or ''}: {exc}".strip())
            else:
                details.append(str(exc))
    if details:
        return "; ".join(details[:3])
    outputs = (history_data or {}).get("outputs") or {}
    if outputs:
        return "ComfyUI workflow finished, but the output node did not generate an image. Check whether it is connected to Save Image/Preview Image and whether required models loaded successfully."
    return "ComfyUI workflow finished without outputs. Check the ComfyUI console for missing models, node errors, or insufficient VRAM."
