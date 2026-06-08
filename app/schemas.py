import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


ONLINE_IMAGE_PROMPT_MAX_LENGTH = int(os.getenv("ONLINE_IMAGE_PROMPT_MAX_LENGTH", "20000"))
VIDEO_PROMPT_MAX_LENGTH = int(os.getenv("VIDEO_PROMPT_MAX_LENGTH", "4000"))
LLM_MESSAGE_MAX_LENGTH = int(os.getenv("LLM_MESSAGE_MAX_LENGTH", "20000"))
VOLC_VISUAL_MOTION_MODEL = "jimeng_dreamactor_m20_gen_video"


class UpdateRequest(BaseModel):
    auto_restart: bool = False
    restart_delay: int = 3


class RollbackRequest(BaseModel):
    name: str = ""
    auto_restart: bool = False
    restart_delay: int = 3


class GenerateRequest(BaseModel):
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    workflow_json: str = "Z-Image.json"
    params: Dict[str, Any] = {}
    type: str = "zimage"
    client_id: str = ""
    convert_to_jpg: bool = False


class DeleteHistoryRequest(BaseModel):
    timestamp: float


class TokenRequest(BaseModel):
    token: str


class CloudGenRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = ""
    resolution: str = "1024x1024"
    type: str = "zimage"
    image_urls: List[str] = []
    loras: Optional[Any] = None
    client_id: Optional[str] = None


class CloudPollRequest(BaseModel):
    task_id: str
    api_key: str = ""
    client_id: Optional[str] = None


class AIReference(BaseModel):
    url: str = ""
    name: str = ""
    role: str = ""


class OnlineImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = ""
    size: str = "1024x1024"
    quality: str = "auto"
    reference_images: List[AIReference] = []
    n: int = Field(default=1, ge=1, le=8)
    canvas_id: str = ""
    output_id: str = ""
    pending_id: str = ""
    source_node_id: str = ""
    client_id: str = ""


class PngComposeRequest(BaseModel):
    rgb_url: str = Field(min_length=1)
    mask_url: str = Field(min_length=1)
    filename: str = "composed_rgba.png"
    mask_mode: str = "auto"
    invert_mask: bool = False


class CanvasVideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=VIDEO_PROMPT_MAX_LENGTH)
    provider_id: str = "comfly"
    model: str = "veo3-fast"
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = ""
    size: str = ""
    images: List[AIReference] = []
    videos: List[str] = []
    audios: List[str] = []
    enhance_prompt: bool = False
    enable_upsample: bool = False
    watermark: bool = False
    seed: Optional[int] = None
    camerafixed: bool = False
    return_last_frame: bool = False
    generate_audio: bool = False


class MotionTransferRequest(BaseModel):
    provider_id: str = "motion-transfer"
    req_key: str = VOLC_VISUAL_MOTION_MODEL
    image_url: str = ""
    image_base64: str = ""
    video_url: str = ""
    cut_result_first_second_switch: bool = True
    poll: bool = True
    aigc_content_producer: str = ""
    aigc_producer_id: str = ""
    aigc_content_propagator: str = ""
    aigc_propagate_id: str = ""


class ApiProviderPayload(BaseModel):
    id: str = ""
    name: str = ""
    base_url: str = ""
    protocol: str = "openai"
    image_generation_endpoint: str = ""
    image_edit_endpoint: str = ""
    enabled: bool = True
    primary: bool = False
    image_models: List[str] = []
    chat_models: List[str] = []
    video_models: List[str] = []
    ms_loras: List[Dict[str, Any]] = []
    ms_defaults_version: int = 0
    api_key: Optional[str] = None
    clear_key: bool = False


class ChatRequest(BaseModel):
    conversation_id: str = ""
    message: str = Field(min_length=1, max_length=LLM_MESSAGE_MAX_LENGTH)
    model: str = ""
    image_model: str = ""
    mode: str = "chat"
    size: str = "1024x1024"
    quality: str = "auto"
    reference_images: List[AIReference] = []
    provider: str = "comfly"
    ms_model: str = ""


class MsGenerateRequest(BaseModel):
    prompt: str
    api_key: str = ""
    model: str = "black-forest-labs/FLUX.2-klein-9B"
    image_urls: List[str] = []
    width: int = 0
    height: int = 0
    size: str = ""
    loras: Optional[Any] = None
    client_id: Optional[str] = None


class CanvasLLMRequest(BaseModel):
    message: str = Field(min_length=1, max_length=LLM_MESSAGE_MAX_LENGTH)
    system_prompt: str = ""
    model: str = ""
    messages: List[Dict[str, Any]] = []
    provider: str = "comfly"
    ms_model: str = ""
    images: List[str] = []


class DreaminaRunRequest(BaseModel):
    mode: str = "auto"
    prompt: str = Field(default="", max_length=VIDEO_PROMPT_MAX_LENGTH)
    images: List[AIReference] = []
    media: List[AIReference] = []
    ratio: str = "16:9"
    duration: int = Field(default=5, ge=1, le=30)
    resolution_type: str = "2k"
    video_resolution: str = "720P"
    model_version: str = "seedance2.0fast"
    poll: int = Field(default=30, ge=1, le=1800)
    output_type: str = "auto"
    timeout: int = Field(default=1800, ge=5, le=3600)
    cli_path: str = ""


class DreaminaQueryMediaRequest(BaseModel):
    submit_id: str = Field(min_length=1)
    kind: str = "image"
    cli_path: str = ""
    timeout: int = Field(default=300, ge=5, le=1800)


class PromptTemplatePayload(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=120)
    category: str = "custom"
    scene: str = ""
    positive: str = Field(min_length=1, max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    negative: str = ""
    params: Dict[str, Any] = {}
    tags: List[str] = []


class ImageExtendRequest(BaseModel):
    prompt: str = Field(default="", max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    image: AIReference
    left: bool = True
    right: bool = True
    top: bool = False
    bottom: bool = False
    strength: str = "balanced"
    provider_id: str = "comfly"
    model: str = ""
    size: str = "1792x1024"
    quality: str = "auto"
    n: int = Field(default=1, ge=1, le=4)
    canvas_id: str = ""
    output_id: str = ""
    pending_id: str = ""
    source_node_id: str = ""
    client_id: str = ""


class PanoramaGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=ONLINE_IMAGE_PROMPT_MAX_LENGTH)
    reference_images: List[AIReference] = []
    provider_id: str = "comfly"
    model: str = ""
    size: str = "2048x1024"
    quality: str = "auto"
    n: int = Field(default=1, ge=1, le=4)
    seamless: bool = True
    include_viewer_hint: bool = True
    canvas_id: str = ""
    output_id: str = ""
    pending_id: str = ""
    source_node_id: str = ""
    client_id: str = ""


class ConversationCreateRequest(BaseModel):
    title: str = "\u65b0\u5bf9\u8bdd"


class CanvasCreateRequest(BaseModel):
    title: str = "\u672a\u547d\u540d\u753b\u5e03"
    icon: str = "layers"
    kind: str = "classic"


class CanvasSaveRequest(BaseModel):
    title: str = "\u672a\u547d\u540d\u753b\u5e03"
    icon: str = "layers"
    nodes: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []
    viewport: Dict[str, Any] = {}
    logs: List[Dict[str, Any]] = []
    settings: Dict[str, Any] = {}
    client_id: str = ""
    base_updated_at: int = 0


class CanvasAssetCheckRequest(BaseModel):
    urls: List[str] = []


class CanvasAssetDownloadRequest(BaseModel):
    urls: List[str] = []
    filename: str = "canvas-output-images.zip"


class AssetLibraryCategoryRequest(BaseModel):
    name: str = "New folder"
    type: str = "image"


class AssetLibraryAddRequest(BaseModel):
    category_id: str = ""
    url: str = ""
    name: str = ""


class AssetLibraryRenameRequest(BaseModel):
    name: str = ""
