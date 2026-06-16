"""AI website library imported from the manga assistant extension."""

import json
import os
import re
import uuid
from typing import Any, Dict, List
from urllib.parse import urlparse


CATEGORY_LABELS = {
    "common": "常用",
    "reasoning": "推理 / 对话",
    "image": "出图",
    "video": "视频",
    "canvas": "画布",
    "voice": "配音",
    "tool": "工具",
}


DEFAULT_SITES: List[Dict[str, Any]] = [
    {"id": "doubao", "title": "豆包", "url": "https://www.doubao.com", "category": "common", "tags": ["对话"]},
    {"id": "deepseek", "title": "DeepSeek", "url": "https://chat.deepseek.com", "category": "common", "tags": ["推理"]},
    {"id": "jimeng", "title": "即梦", "url": "https://jimeng.jianying.com/ai-tool/home/", "category": "common", "tags": ["出图", "视频"]},
    {"id": "oiioii", "title": "Oiioii", "url": "https://oiioii.ai/", "category": "common", "tags": ["画布"]},
    {"id": "chatgpt", "title": "ChatGPT", "url": "https://chatgpt.com/", "category": "reasoning", "tags": ["对话", "写作"]},
    {"id": "claude", "title": "Claude", "url": "https://claude.ai/", "category": "reasoning", "tags": ["对话", "写作"]},
    {"id": "kimi", "title": "Kimi", "url": "https://kimi.com/", "category": "reasoning", "tags": ["长文", "对话"]},
    {"id": "tongyi", "title": "通义千问", "url": "https://tongyi.aliyun.com/", "category": "reasoning", "tags": ["对话"]},
    {"id": "qianwen", "title": "Qianwen", "url": "https://qianwen.com/", "category": "reasoning", "tags": ["对话"]},
    {"id": "chatglm", "title": "智谱清言", "url": "https://chatglm.cn/", "category": "reasoning", "tags": ["对话"]},
    {"id": "yiyan", "title": "文心一言", "url": "https://yiyan.baidu.com/", "category": "reasoning", "tags": ["对话"]},
    {"id": "gemini", "title": "Gemini", "url": "https://gemini.google.com/", "category": "reasoning", "tags": ["对话"]},
    {"id": "grok", "title": "Grok", "url": "https://grok.com/", "category": "reasoning", "tags": ["对话"]},
    {"id": "youmind", "title": "YouMind", "url": "https://youmind.com/", "category": "reasoning", "tags": ["知识库"]},
    {"id": "liblib", "title": "LibLib", "url": "https://www.liblib.tv/", "category": "image", "tags": ["出图", "素材"]},
    {"id": "volcengine-seedance", "title": "火山 Seedance", "url": "https://exp.volcengine.com/", "category": "video", "tags": ["Seedance", "视频"]},
    {"id": "vidu", "title": "Vidu", "url": "https://www.vidu.cn/", "category": "video", "tags": ["视频"]},
    {"id": "kling", "title": "可灵 Kling", "url": "https://klingai.com/", "category": "video", "tags": ["视频"]},
    {"id": "pai", "title": "Pai Video", "url": "https://pai.video/", "category": "video", "tags": ["视频"]},
    {"id": "runway", "title": "Runway", "url": "https://app.runwayml.com/", "category": "video", "tags": ["视频"]},
    {"id": "minimax", "title": "MiniMax", "url": "https://minimaxi.com/", "category": "video", "tags": ["视频"]},
    {"id": "noiz", "title": "Noiz", "url": "https://noiz.ai/", "category": "video", "tags": ["视频"]},
    {"id": "peiyinshenqi", "title": "配音神器", "url": "https://www.peiyinshenqi.com/", "category": "voice", "tags": ["配音"]},
]


def ai_sites_store_path(data_dir: str) -> str:
    return os.path.join(data_dir, "ai_sites.json")


def normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if value and not re.match(r"^https?://", value, re.I):
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("网站地址必须是有效的 http/https 链接")
    return value


def normalize_site(item: Dict[str, Any], builtin: bool = False) -> Dict[str, Any]:
    title = str(item.get("title") or item.get("name") or "").strip()[:80]
    url = normalize_url(str(item.get("url") or ""))
    sid = str(item.get("id") or "").strip()
    if not sid:
        sid = f"site_{uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]}"
    category = str(item.get("category") or "tool").strip() or "tool"
    if category not in CATEGORY_LABELS:
        category = "tool"
    tags = [str(tag).strip()[:24] for tag in (item.get("tags") or []) if str(tag).strip()]
    return {
        "id": sid,
        "title": title or parsed_title_from_url(url),
        "url": url,
        "category": category,
        "description": str(item.get("description") or "").strip()[:240],
        "tags": tags,
        "sort": int(item.get("sort") or 0),
        "builtin": bool(item.get("builtin", builtin)),
    }


def parsed_title_from_url(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host or "未命名网站"


def load_custom_sites(data_dir: str) -> List[Dict[str, Any]]:
    path = ai_sites_store_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    items = data.get("sites") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            result.append(normalize_site(item, builtin=False))
        except ValueError:
            continue
    return result


def save_custom_sites(data_dir: str, sites: List[Dict[str, Any]]) -> None:
    os.makedirs(data_dir, exist_ok=True)
    custom = [normalize_site(item, builtin=False) for item in sites if not item.get("builtin")]
    with open(ai_sites_store_path(data_dir), "w", encoding="utf-8") as f:
        json.dump({"sites": custom}, f, ensure_ascii=False, indent=2)


def list_sites(data_dir: str) -> List[Dict[str, Any]]:
    builtins = [normalize_site(item, builtin=True) for item in DEFAULT_SITES]
    builtin_ids = {item["id"] for item in builtins}
    custom = [item for item in load_custom_sites(data_dir) if item["id"] not in builtin_ids]
    return sorted([*builtins, *custom], key=lambda item: (item["category"], item["sort"], item["title"].lower()))


def grouped_sites(data_dir: str) -> List[Dict[str, Any]]:
    sites = list_sites(data_dir)
    groups = []
    for category, label in CATEGORY_LABELS.items():
        items = [item for item in sites if item["category"] == category]
        if items:
            groups.append({"id": category, "label": label, "sites": items})
    return groups


def upsert_site(data_dir: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    site = normalize_site(payload, builtin=False)
    if not site["title"]:
        raise ValueError("网站名称不能为空")
    custom = load_custom_sites(data_dir)
    index = next((i for i, existing in enumerate(custom) if existing["id"] == site["id"]), -1)
    if index >= 0:
        custom[index] = site
    else:
        custom.append(site)
    save_custom_sites(data_dir, custom)
    return site


def delete_site(data_dir: str, site_id: str) -> bool:
    if any(item["id"] == site_id for item in DEFAULT_SITES):
        return False
    custom = load_custom_sites(data_dir)
    next_items = [item for item in custom if item["id"] != site_id]
    if len(next_items) == len(custom):
        return False
    save_custom_sites(data_dir, next_items)
    return True
