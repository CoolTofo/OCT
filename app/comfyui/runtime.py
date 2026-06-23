"""ComfyUI output download and failure parsing helpers."""

import json
import os
import re
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


def normalize_comfy_class_name(class_type: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(class_type or "").lower())


def comfy_output_node_class(workflow: Dict[str, Any], node_id: Any) -> str:
    if not isinstance(workflow, dict):
        return ""
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        return ""
    return normalize_comfy_class_name(node.get("class_type") or "")


def comfy_is_preview_output_class(class_name: str) -> bool:
    return class_name in {
        "previewimage",
        "saveimagewebsocket",
    } or "preview" in class_name


def comfy_is_final_image_output_class(class_name: str) -> bool:
    return class_name in {
        "saveimage",
        "saveimagewithalpha",
        "saveanimatedwebp",
        "saveanimatedpng",
        "savewebpimage",
    } or (class_name.startswith("save") and "image" in class_name)


def is_comfy_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and str(value[0]).isdigit()


def comfy_node_output_has_media(node_output: Dict[str, Any]) -> bool:
    if not isinstance(node_output, dict):
        return False
    if node_output.get("images"):
        return True
    return any(node_output.get(key) for key in ("videos", "gifs", "animated"))

def comfy_node_has_linked_media_input(node: Dict[str, Any]) -> bool:
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if not inputs:
        return False
    media_input_names = {"image", "images", "video", "videos", "audio", "audios", "frames", "gif", "gifs", "animated"}
    for input_name, value in inputs.items():
        key = normalize_comfy_class_name(input_name)
        if key not in media_input_names:
            continue
        if is_comfy_link(value):
            return True
    return False


def workflow_final_output_node_ids(workflow: Dict[str, Any]) -> list[str]:
    if not isinstance(workflow, dict):
        return []
    result = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_name = normalize_comfy_class_name(node.get("class_type") or "")
        if comfy_is_final_image_output_class(class_name) and comfy_node_has_linked_media_input(node):
            result.append(str(node_id))
    return result


def missing_declared_final_outputs(history_data: Dict[str, Any], workflow: Dict[str, Any]) -> list[str]:
    outputs = (history_data or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        return []
    missing = []
    for node_id in workflow_final_output_node_ids(workflow):
        node_output = outputs.get(node_id) or outputs.get(int(node_id)) or {}
        if not comfy_node_output_has_media(node_output):
            missing.append(node_id)
    return missing


def preferred_history_output_node_ids(history_data: Dict[str, Any], workflow: Dict[str, Any]) -> list[str]:
    outputs = (history_data or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        return []

    node_ids = [str(node_id) for node_id, node_output in outputs.items() if isinstance(node_output, dict)]
    if not node_ids:
        return []

    declared_final_image_node_ids = set(workflow_final_output_node_ids(workflow))
    image_node_ids = []
    final_image_node_ids = []
    preview_image_node_ids = []
    other_node_ids = []

    for node_id in node_ids:
        node_output = outputs.get(node_id) or outputs.get(int(node_id)) or {}
        if not isinstance(node_output, dict):
            continue
        has_images = bool(node_output.get("images"))
        class_name = comfy_output_node_class(workflow, node_id)
        if has_images:
            image_node_ids.append(node_id)
            if node_id in declared_final_image_node_ids:
                final_image_node_ids.append(node_id)
            elif comfy_is_preview_output_class(class_name):
                preview_image_node_ids.append(node_id)
        else:
            other_node_ids.append(node_id)

    if final_image_node_ids:
        chosen_image_nodes = final_image_node_ids
    elif image_node_ids:
        non_preview = [node_id for node_id in image_node_ids if node_id not in preview_image_node_ids]
        chosen_image_nodes = non_preview or image_node_ids
    else:
        chosen_image_nodes = []

    preferred = []
    preferred.extend(chosen_image_nodes)
    preferred.extend(node_id for node_id in other_node_ids if node_id not in preferred)
    return preferred

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
