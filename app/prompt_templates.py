"""Prompt template library storage and built-in creative recipes."""

import json
import os
import re
import uuid
from typing import Any, Dict, List


DEFAULT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "builtin_outpaint_scene",
        "name": "图片扩展：补全场景",
        "category": "image_extend",
        "scene": "用于把已有图片向四周扩展，补全背景、光影和构图。",
        "positive": (
            "Extend the image beyond its current borders. Keep the original subject, camera angle, "
            "lighting, color grading, texture, and perspective consistent. Fill the new areas with "
            "natural scene continuation, coherent details, and no duplicated subject."
        ),
        "negative": "cropped subject, duplicated character, broken perspective, visible seams, low quality, blurry",
        "params": {"recommended_ratio": "16:9", "recommended_size": "1792x1024"},
        "tags": ["扩图", "outpaint", "场景补全"],
        "builtin": True,
    },
    {
        "id": "builtin_panorama_360",
        "name": "360 全景图",
        "category": "panorama",
        "scene": "生成可用于 VR/全景预览的 2:1 横向无缝全景图。",
        "positive": (
            "Create a seamless 360-degree equirectangular panorama image in 2:1 aspect ratio. "
            "The left and right edges must connect perfectly. Keep horizon level, natural pole "
            "transitions, immersive environment detail, and no visible seam."
        ),
        "negative": "visible seam, broken horizon, duplicated objects at edges, fisheye distortion, text, watermark",
        "params": {"recommended_ratio": "2:1", "recommended_size": "2048x1024"},
        "tags": ["360", "VR", "panorama", "全景"],
        "builtin": True,
    },
    {
        "id": "builtin_panorama_room",
        "name": "360 室内空间",
        "category": "panorama",
        "scene": "室内、展厅、办公室、商业空间的 360 全景概念图。",
        "positive": (
            "Generate a seamless 360-degree equirectangular panorama of an interior space. "
            "Use coherent room geometry, consistent lighting, realistic materials, balanced exposure, "
            "and a continuous wraparound composition."
        ),
        "negative": "warped walls, broken ceiling, impossible doors, visible seam, low detail",
        "params": {"recommended_ratio": "2:1", "recommended_size": "2048x1024"},
        "tags": ["室内", "空间", "360"],
        "builtin": True,
    },
    {
        "id": "builtin_cli_image_refine",
        "name": "即梦 CLI：参考图重绘",
        "category": "dreamina",
        "scene": "配合 Dreamina 图节点，用参考图进行重绘、换背景或风格迁移。",
        "positive": (
            "Use the connected reference image as the main composition and identity anchor. "
            "Preserve subject placement, proportions, pose, and camera angle unless the prompt asks otherwise. "
            "Apply the requested edit cleanly and keep high detail."
        ),
        "negative": "identity drift, wrong pose, extra limbs, distorted face, text artifacts, low quality",
        "params": {"mode": "image2image", "resolution_type": "2k"},
        "tags": ["即梦", "Dreamina", "参考图"],
        "builtin": True,
    },
]


def template_store_path(data_dir: str) -> str:
    return os.path.join(data_dir, "prompt_templates.json")


def load_custom_templates(data_dir: str) -> List[Dict[str, Any]]:
    path = template_store_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    items = data.get("templates") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [normalize_template(item, builtin=False) for item in items if isinstance(item, dict)]


def save_custom_templates(data_dir: str, templates: List[Dict[str, Any]]) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = template_store_path(data_dir)
    custom = [normalize_template(item, builtin=False) for item in templates if not item.get("builtin")]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"templates": custom}, f, ensure_ascii=False, indent=2)


def normalize_template(item: Dict[str, Any], builtin: bool = False) -> Dict[str, Any]:
    tid = str(item.get("id") or "").strip() or f"tpl_{uuid.uuid4().hex[:12]}"
    return {
        "id": tid,
        "name": str(item.get("name") or "未命名模板").strip()[:120],
        "category": str(item.get("category") or "custom").strip() or "custom",
        "scene": str(item.get("scene") or "").strip(),
        "positive": str(item.get("positive") or item.get("prompt") or "").strip(),
        "negative": str(item.get("negative") or "").strip(),
        "params": item.get("params") if isinstance(item.get("params"), dict) else {},
        "tags": [str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip()],
        "builtin": bool(item.get("builtin", builtin)),
    }


def list_templates(data_dir: str) -> List[Dict[str, Any]]:
    merged = [normalize_template(item, builtin=True) for item in DEFAULT_TEMPLATES]
    custom = load_custom_templates(data_dir)
    builtin_ids = {item["id"] for item in merged}
    merged.extend(item for item in custom if item["id"] not in builtin_ids)
    return merged


def upsert_template(data_dir: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    item = normalize_template(payload, builtin=False)
    if not item["positive"]:
        raise ValueError("模板正向提示词不能为空")
    custom = load_custom_templates(data_dir)
    index = next((i for i, existing in enumerate(custom) if existing["id"] == item["id"]), -1)
    if index >= 0:
        custom[index] = item
    else:
        custom.append(item)
    save_custom_templates(data_dir, custom)
    return item


def delete_template(data_dir: str, template_id: str) -> bool:
    if any(item["id"] == template_id for item in DEFAULT_TEMPLATES):
        return False
    custom = load_custom_templates(data_dir)
    next_items = [item for item in custom if item["id"] != template_id]
    if len(next_items) == len(custom):
        return False
    save_custom_templates(data_dir, next_items)
    return True


def find_template(data_dir: str, template_id: str) -> Dict[str, Any]:
    return next((item for item in list_templates(data_dir) if item["id"] == template_id), {})


def apply_template_text(template: Dict[str, Any], user_prompt: str = "") -> str:
    positive = str(template.get("positive") or "").strip()
    user_prompt = str(user_prompt or "").strip()
    if "{prompt}" in positive:
        return positive.replace("{prompt}", user_prompt)
    return "\n\n".join(part for part in [user_prompt, positive] if part)


def parse_markdown_templates(text: str) -> List[Dict[str, Any]]:
    """Best-effort parser for the reference markdown template format."""
    items: List[Dict[str, Any]] = []
    blocks = re.split(r"(?m)^##\s+", text or "")
    for block in blocks:
        title_line, _, body = block.partition("\n")
        title = title_line.strip()
        if not title or not body:
            continue
        name = re.sub(r"^预设\s*\d+\s*[：:]\s*", "", title).strip()
        positive = _section(body, "正向提示词")
        if not positive:
            continue
        scene = _section(body, "适用场景")
        negative = _section(body, "负向提示词")
        category = "panorama" if "360" in name or "全景" in name or "VR" in scene else "custom"
        items.append(normalize_template({
            "id": f"md_{uuid.uuid5(uuid.NAMESPACE_URL, name).hex[:12]}",
            "name": name,
            "category": category,
            "scene": scene,
            "positive": positive,
            "negative": negative,
            "tags": [category],
        }, builtin=True))
    return items


def _section(block: str, title: str) -> str:
    match = re.search(rf"###\s*{re.escape(title)}\s*\n(?P<body>.*?)(?=\n###\s+|\Z)", block, re.S)
    if not match:
        return ""
    body = match.group("body").strip()
    fence = re.search(r"```(?:\w+)?\s*\n(?P<code>.*?)\n```", body, re.S)
    return (fence.group("code") if fence else body).strip()
