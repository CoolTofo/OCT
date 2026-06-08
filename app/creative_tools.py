"""High-level creative helpers used by canvas tool nodes."""

from typing import Any, Dict, List

from app.schemas import ImageExtendRequest, OnlineImageRequest, PanoramaGenerateRequest


EXTEND_STRENGTH_TEXT = {
    "light": "Make a conservative extension with minimal new elements.",
    "subtle": "Make a conservative extension with minimal new elements.",
    "balanced": "Extend naturally with coherent new scene details.",
    "large": "Extend more imaginatively while preserving the source image identity and perspective.",
    "creative": "Extend more imaginatively while preserving the source image identity and perspective.",
}


def build_extend_prompt(payload: ImageExtendRequest) -> str:
    directions = []
    if payload.left:
        directions.append("left")
    if payload.right:
        directions.append("right")
    if payload.top:
        directions.append("top")
    if payload.bottom:
        directions.append("bottom")
    direction_text = ", ".join(directions) if directions else "all sides"
    user_prompt = (payload.prompt or "").strip()
    strength = EXTEND_STRENGTH_TEXT.get((payload.strength or "balanced").strip(), EXTEND_STRENGTH_TEXT["balanced"])
    base = (
        f"Outpaint and extend the connected image toward: {direction_text}. "
        "Preserve the original subject, pose, camera angle, perspective, lighting, color palette, and material details. "
        "Fill the new canvas area with a seamless continuation of the environment. "
        "Do not duplicate the main subject. Avoid visible seams, warped edges, or broken geometry. "
        f"{strength}"
    )
    return "\n\n".join(part for part in [user_prompt, base] if part)


def build_panorama_prompt(payload: PanoramaGenerateRequest) -> str:
    prompt = (payload.prompt or "").strip()
    panorama = (
        "Create a 360-degree equirectangular panorama image in a 2:1 aspect ratio. "
        "The left and right edges must connect seamlessly. Keep the horizon level, preserve natural perspective, "
        "avoid fisheye warping, and make the environment continuous in every direction."
    )
    if payload.seamless:
        panorama += " Emphasize seamless wraparound continuity and natural pole transitions."
    if payload.include_viewer_hint:
        panorama += " The result should be suitable for VR panorama viewers."
    return "\n\n".join(part for part in [prompt, panorama] if part)


def image_extend_online_payload(payload: ImageExtendRequest) -> OnlineImageRequest:
    return OnlineImageRequest(
        prompt=build_extend_prompt(payload),
        provider_id=payload.provider_id,
        model=payload.model,
        size=payload.size,
        quality=payload.quality,
        reference_images=[payload.image],
        n=payload.n,
        canvas_id=payload.canvas_id,
        output_id=payload.output_id,
        pending_id=payload.pending_id,
        source_node_id=payload.source_node_id,
        client_id=payload.client_id,
    )


def panorama_online_payload(payload: PanoramaGenerateRequest) -> OnlineImageRequest:
    return OnlineImageRequest(
        prompt=build_panorama_prompt(payload),
        provider_id=payload.provider_id,
        model=payload.model,
        size=payload.size,
        quality=payload.quality,
        reference_images=payload.reference_images,
        n=payload.n,
        canvas_id=payload.canvas_id,
        output_id=payload.output_id,
        pending_id=payload.pending_id,
        source_node_id=payload.source_node_id,
        client_id=payload.client_id,
    )


def creative_recipes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "image_extend",
            "name": "扩展图片",
            "description": "连接一张图片，向左/右/上/下补全画面。",
            "output": "image",
            "required_inputs": ["image"],
        },
        {
            "id": "panorama_360",
            "name": "360 全景图",
            "description": "生成 2:1 无缝全景图，可接全景预览。",
            "output": "image",
            "required_inputs": ["prompt"],
        },
    ]
