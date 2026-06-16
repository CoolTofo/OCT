"""Import prompt templates from exported Word documents."""

import hashlib
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


CLASSIFY_RULES = [
    (
        r"根据这种图片帮我生成.*右侧三视|要求人物保持不变.*专业角色设定表",
        "参考图转角色三视图",
        "character_design",
        ["参考图", "三视图", "角色设定"],
        "保持人物不变，生成角色特写加正侧背三视图设定表。",
    ),
    (
        r"人物三视图.*故事板|打斗或动作.*运动方向",
        "人物三视图故事板",
        "storyboard",
        ["故事板", "动作", "三视图"],
        "基于人物三视图生成带动作方向和镜头信息的故事板。",
    ),
    (
        r"根据下方故事.*手绘风格分镜稿|故事内容如下",
        "12镜头手绘分镜稿",
        "storyboard_sketch",
        ["故事板", "手绘", "12镜头"],
        "根据具体故事生成 4x3 手绘风格分镜稿。",
    ),
    (
        r"小说推文改文|第一人称解说文案|八大金刚公式",
        "小说推文改文：第一人称解说",
        "novel_rewrite",
        ["改文", "小说推文", "解说"],
        "把小说原文改成适合短视频配音的第一人称解说文案。",
    ),
    (
        r"电影级纯净场景|纯净场景|无人, 纯场景",
        "电影级纯净场景设定",
        "scene_design",
        ["场景", "无人场景", "设定"],
        "从文案中提取地点并生成无人物、可直接生图的场景设定。",
    ),
    (
        r"电影级角色建模|角色内核提取|专业角色设定表",
        "电影级角色设定表",
        "character_design",
        ["角色", "三视图", "设定"],
        "根据文案提取角色并生成专业角色设定表。",
    ),
    (
        r"旁白和对话拆分分镜头|内容镜头一致性原则|六维一致性准则",
        "15秒分镜脚本与视频提示词",
        "storyboard",
        ["分镜", "视频提示词", "连续性"],
        "把旁白和对话拆分成连续分镜，并生成带角色映射的视频提示词。",
    ),
    (
        r"参考图生成人物全身照|手和脚都要完全显示",
        "参考图人物全身照",
        "character_reference",
        ["参考图", "全身照", "角色一致"],
        "根据参考图生成自然站立、手脚完整可见的人物全身照。",
    ),
    (
        r"三视图.*场景.*故事板|9.?宫格描述剧本",
        "三视图与场景故事板",
        "storyboard",
        ["故事板", "三视图", "场景"],
        "根据三视图、场景和剧本生成九宫格故事板。",
    ),
    (
        r"专业故事板故事板主体是一个表格|镜头号.*时间.*景别",
        "专业故事板表格",
        "storyboard",
        ["故事板", "表格", "镜头设计"],
        "按导演逻辑生成非平均时长的专业分镜表格。",
    ),
    (
        r"卧室醒过来|穿越大厅|照镜子|3X2",
        "火柴人连贯动作调度图",
        "storyboard_sketch",
        ["动作调度", "火柴人", "分镜草图"],
        "生成 3x2 火柴人动作调度图，标注站位和运动轨迹。",
    ),
    (
        r"擂台中两位拳手|激烈打斗",
        "打斗动作分镜草稿",
        "storyboard_action",
        ["打斗", "动作分镜", "草稿"],
        "生成 4x3 打斗动作分镜草稿，突出动作张力和镜头节奏。",
    ),
    (
        r"故事展开完全参照图中@图片1|严格按照故事版路径",
        "故事板路径续写",
        "storyboard_control",
        ["故事板", "参考图", "路径锁定"],
        "严格参考已给故事板路径生成，不增减情节。",
    ),
    (
        r"视觉专家，摄影师|分析这张照片|人物景别",
        "图片反推提示词分析",
        "prompt_reverse",
        ["图片分析", "反推提示词", "摄影"],
        "分析图片并输出人物景别、构图、风格、光线和色调等提示词字段。",
    ),
    (
        r"即梦 Seedance 2.0|AI生成视频的导演|直接给即梦可用",
        "即梦 Seedance 视频导演智能体",
        "seedance",
        ["Seedance", "视频提示词", "导演"],
        "按即梦 Seedance 2.0 标准生成可直接使用的视频提示词。",
    ),
    (
        r"无字幕，无贴图，无旁白|面部特征100%相同|禁止美化",
        "视频提示词结尾负面约束",
        "seedance",
        ["Seedance", "负面约束", "角色一致"],
        "用于视频提示词结尾，约束字幕、贴图、旁白、音乐和人物一致性。",
    ),
]


def parse_docx_prompt_templates(content: bytes) -> List[Dict[str, Any]]:
    """Return normalized template payloads parsed from a .docx byte stream."""
    paragraphs = extract_docx_paragraphs(content)
    templates: List[Dict[str, Any]] = []
    seen = set()
    for paragraph in paragraphs:
        text = clean_exported_paragraph(paragraph)
        if not is_prompt_paragraph(text):
            continue
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        templates.append(classify_prompt_text(text, len(templates) + 1))
    return templates


def extract_docx_paragraphs(content: bytes) -> List[str]:
    if not content:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception as exc:
        raise ValueError("无法读取 Word 文档，请确认上传的是 .docx 文件") from exc
    root = ET.fromstring(document_xml)
    paragraphs: List[str] = []
    for paragraph in root.findall(".//w:p", WORD_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS))
        text = normalize_space(text)
        if text:
            paragraphs.append(text)
    return paragraphs


def clean_exported_paragraph(text: str) -> str:
    value = normalize_space(text)
    value = re.sub(r"^\s*杨广\s+\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}\s*", "", value)
    value = re.sub(r"^\s*杨广\s+\d{4}年\d{1,2}月\d{1,2}日\s*$", "", value)
    value = re.sub(r"^\s*查看原消息记录.*$", "", value)
    return normalize_space(value)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\u3000", " ")).strip()


def is_prompt_paragraph(text: str) -> bool:
    if len(text) < 24:
        return False
    return bool(re.search(r"提示词|Prompt|Role|任务|根据|你是|无字幕|故事|分镜|角色|场景|即梦|Seedance", text, re.I))


def classify_prompt_text(text: str, index: int) -> Dict[str, Any]:
    for pattern, name, category, tags, scene in CLASSIFY_RULES:
        if re.search(pattern, text, re.I):
            return build_template_payload(name, category, scene, text, tags)
    return build_template_payload(
        f"文档导入模板 {index}",
        "docx_import",
        "从 Word 文档导入的提示词模板。",
        text,
        ["Word导入"],
    )


def build_template_payload(name: str, category: str, scene: str, positive: str, tags: List[str]) -> Dict[str, Any]:
    digest = hashlib.sha1((name + "\n" + positive).encode("utf-8")).hexdigest()[:12]
    next_tags = list(dict.fromkeys([*tags, "Word导入", "2026-06-16"]))
    return {
        "id": f"docx_{digest}",
        "name": name,
        "category": category,
        "scene": scene,
        "positive": positive,
        "negative": "",
        "params": {"source": "杨广 2026年6月16日.docx"},
        "tags": next_tags,
        "builtin": False,
    }
