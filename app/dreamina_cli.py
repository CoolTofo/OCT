import asyncio
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import uuid
from glob import glob
from typing import Any, Dict, List, Tuple

import httpx
from fastapi import HTTPException

from app import media_store
from app.paths import BASE_DIR
from app.schemas import DreaminaRunRequest


ALLOWED_MODES = {"auto", "text2image", "text2video", "image2image", "image2video", "multimodal2video"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
MEDIA_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
SUBMIT_ID_RE = re.compile(r"(?:submit[_-]?id|task[_-]?id)[\"'\s:=]+([A-Za-z0-9_-]{8,})", re.I)
LOG_SUBMIT_ID_RE = re.compile(r"submit_id=([A-Za-z0-9_-]{8,})", re.I)
CONTENT_TYPE_EXTS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


def _default_cli_path() -> str:
    user_bin = os.path.join(os.path.expanduser("~"), "bin", "dreamina.exe")
    if os.path.exists(user_bin):
        return user_bin
    return "dreamina"


def _clean_cli_path(cli_path: str) -> str:
    value = (cli_path or os.getenv("DREAMINA_CLI_PATH") or _default_cli_path()).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    return value or "dreamina"


def _local_path_from_ref(ref: Any) -> Tuple[str, str]:
    url = ref.url if hasattr(ref, "url") else ""
    path = media_store.output_file_from_url(url)
    if not path:
        raise HTTPException(
            status_code=400,
            detail="Dreamina CLI needs local canvas assets. Upload the media into the canvas first, then connect it to the node.",
        )
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return path, "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}:
        return path, "audio"
    return path, "image"


def _resolve_mode(payload: DreaminaRunRequest, local_inputs: List[Tuple[str, str]]) -> str:
    mode = (payload.mode or "auto").strip()
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail="Unsupported Dreamina CLI mode.")
    if mode != "auto":
        return mode
    wants_video = (payload.output_type or "").lower() == "video"
    kinds = {kind for _, kind in local_inputs}
    if wants_video and ({"video", "audio"} & kinds or len(local_inputs) > 1):
        return "multimodal2video"
    if local_inputs and wants_video:
        return "image2video"
    if local_inputs:
        return "image2image"
    return "text2video" if wants_video else "text2image"


def _build_command(payload: DreaminaRunRequest) -> Tuple[str, List[str], List[str]]:
    refs = payload.media or payload.images or []
    local_inputs = [_local_path_from_ref(ref) for ref in refs if getattr(ref, "url", "")]
    mode = _resolve_mode(payload, local_inputs)
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Dreamina CLI needs a prompt.")
    if mode in {"image2image", "image2video", "multimodal2video"} and not local_inputs:
        raise HTTPException(status_code=400, detail="Dreamina CLI media modes need one connected image or video.")
    kinds = {kind for _, kind in local_inputs}
    if mode in {"text2image", "image2image"} and ({"video", "audio"} & kinds):
        raise HTTPException(status_code=400, detail="Video or audio inputs require a video output mode.")
    if mode == "image2video" and "image" not in kinds:
        raise HTTPException(status_code=400, detail="image2video needs a connected image. Use multimodal2video for video inputs.")

    cli = _clean_cli_path(payload.cli_path)
    args = [cli, mode, f"--prompt={prompt}", f"--poll={int(payload.poll or 30)}"]
    if mode in {"text2image", "image2image"}:
        args.extend([f"--ratio={payload.ratio or '1:1'}", f"--resolution_type={payload.resolution_type or '2k'}"])
    if mode in {"text2video", "image2video"}:
        args.extend([
            f"--duration={int(payload.duration or 5)}",
            f"--video_resolution={(payload.video_resolution or '720P').lower()}",
        ])
        if payload.model_version:
            args.append(f"--model_version={payload.model_version}")
    if mode in {"text2video", "multimodal2video"}:
        args.append(f"--ratio={payload.ratio or '16:9'}")
    if mode == "image2image":
        first_image = next((path for path, kind in local_inputs if kind == "image"), "")
        args.extend(["--images", first_image])
    elif mode == "image2video":
        first_image = next((path for path, kind in local_inputs if kind == "image"), "")
        args.extend(["--image", first_image])
    elif mode == "multimodal2video":
        duration = max(4, min(15, int(payload.duration or 5)))
        args = [cli, mode, f"--prompt={prompt}", f"--duration={duration}", f"--ratio={payload.ratio or '16:9'}", f"--video_resolution={(payload.video_resolution or '720P').lower()}", f"--model_version={payload.model_version or 'seedance2.0fast'}", f"--poll={int(payload.poll or 30)}"]
        for path, kind in local_inputs:
            if kind == "image":
                args.extend(["--image", path])
            elif kind == "video":
                args.extend(["--video", path])
            elif kind == "audio":
                args.extend(["--audio", path])
    return mode, args, [path for path, _ in local_inputs]


def _run_process(args: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def _extract_submit_id(text: str) -> str:
    match = SUBMIT_ID_RE.search(text or "")
    return match.group(1) if match else ""


def _latest_dreamina_log_text(max_chars: int = 12000) -> str:
    log_dir = os.path.join(os.path.expanduser("~"), ".dreamina_cli", "logs")
    try:
        candidates = sorted(glob(os.path.join(log_dir, "dreamina.log*")), key=os.path.getmtime, reverse=True)
    except Exception:
        return ""
    for path in candidates[:3]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            if text:
                return text[-max_chars:]
        except Exception:
            continue
    return ""


def _extract_latest_log_submit_id() -> str:
    text = _latest_dreamina_log_text()
    matches = LOG_SUBMIT_ID_RE.findall(text)
    return matches[-1] if matches else ""


def _json_media_urls(text: str) -> List[str]:
    try:
        data = json.loads(text or "{}")
    except Exception:
        return []
    urls = []

    def walk(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if isinstance(item, str) and item.startswith("http") and ("url" in key_text or key_text in {"uri", "src"}):
                    urls.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return urls


def _media_urls(text: str) -> List[str]:
    urls = []
    seen = set()
    for raw in [*_json_media_urls(text), *MEDIA_URL_RE.findall(text or "")]:
        url = raw.rstrip(".,;)]}'\"")
        path = urllib.parse.urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        format_hint = "." + (query.get("format", [""])[0] or "").lstrip(".").lower()
        if (ext in IMAGE_EXTS | VIDEO_EXTS or format_hint in IMAGE_EXTS | VIDEO_EXTS) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _local_outputs(text: str) -> List[str]:
    outputs = []
    seen = set()
    for token in re.findall(r"(?:(?:[A-Za-z]:)?[\\/][^\s\"'<>]+|[A-Za-z]:\\[^\s\"'<>]+)", text or ""):
        path = token.rstrip(".,;)]}'\"")
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            continue
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path) and abs_path not in seen:
            seen.add(abs_path)
            outputs.append(abs_path)
    return outputs


def _copy_local_output(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    prefix = "dreamina_video_" if ext in VIDEO_EXTS else "dreamina_"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext or '.bin'}"
    dest = media_store.output_path_for(filename, "output")
    shutil.copyfile(path, dest)
    return media_store.output_url_for(filename, "output")


def _ext_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower()
    query = urllib.parse.parse_qs(parsed.query)
    format_hint = "." + (query.get("format", [""])[0] or "").lstrip(".").lower()
    if format_hint in IMAGE_EXTS | VIDEO_EXTS:
        return format_hint
    return ext if ext in IMAGE_EXTS | VIDEO_EXTS else ""


def _ext_from_content_type(content_type: str, fallback: str) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_EXTS.get(normalized) or fallback


async def _save_remote_output(url: str) -> Tuple[str, str]:
    ext = _ext_from_url(url)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if not ext:
        fallback = ".mp4" if content_type.lower().startswith("video/") else ".png"
        ext = _ext_from_content_type(content_type, fallback)
    kind = "video" if ext in VIDEO_EXTS or content_type.lower().startswith("video/") else "image"
    if ext not in IMAGE_EXTS | VIDEO_EXTS:
        ext = ".mp4" if kind == "video" else ".png"
    prefix = "dreamina_video_" if kind == "video" else "dreamina_"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext}"
    dest = media_store.output_path_for(filename, "output")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(response.content)
    return media_store.output_url_for(filename, "output"), kind


async def _localize_outputs(urls: List[str], local_paths: List[str]) -> Tuple[List[str], List[str]]:
    images, videos = [], []
    for url in urls:
        local_url, kind = await _save_remote_output(url)
        if kind == "video":
            videos.append(local_url)
        else:
            images.append(local_url)
    for path in local_paths:
        url = _copy_local_output(path)
        if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
            videos.append(url)
        else:
            images.append(url)
    return images, videos


async def _query_result(cli: str, submit_id: str, timeout: int) -> subprocess.CompletedProcess:
    download_dir = media_store.output_storage("output")[0]
    return await asyncio.to_thread(
        _run_process,
        [cli, "query_result", f"--submit_id={submit_id}", f"--download_dir={download_dir}"],
        timeout,
    )


async def _query_until_outputs(cli: str, submit_id: str, wait_seconds: int) -> Tuple[List[str], List[str], str, str]:
    deadline = asyncio.get_running_loop().time() + max(1, wait_seconds)
    last_stdout = ""
    last_stderr = ""
    while True:
        proc = await _query_result(cli, submit_id, min(60, max(5, wait_seconds)))
        last_stdout = proc.stdout or ""
        last_stderr = proc.stderr or ""
        combined = "\n".join([last_stdout, last_stderr])
        images, videos = await _localize_outputs(_media_urls(combined), _local_outputs(combined))
        if images or videos:
            return images, videos, last_stdout, last_stderr
        status_text = combined.lower()
        if any(flag in status_text for flag in ['"gen_status": "fail', '"gen_status":"fail', '"queue_status": "fail', '"queue_status":"fail']):
            return images, videos, last_stdout, last_stderr
        if asyncio.get_running_loop().time() >= deadline:
            return images, videos, last_stdout, last_stderr
        await asyncio.sleep(2)


async def run_dreamina_cli(payload: DreaminaRunRequest) -> Dict[str, Any]:
    mode, args, local_inputs = _build_command(payload)
    try:
        proc = await asyncio.to_thread(_run_process, args, int(payload.timeout or 1800))
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Dreamina CLI was not found. Install dreamina or set cli_path.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Dreamina CLI timed out before returning a result.")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = "\n".join([stdout, stderr])
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=(stderr or stdout or "Dreamina CLI failed.")[:1200])

    images, videos = await _localize_outputs(_media_urls(combined), _local_outputs(combined))
    submit_id = _extract_submit_id(combined) or _extract_latest_log_submit_id()
    query_stdout = ""
    query_stderr = ""
    if not images and not videos and submit_id:
        images, videos, query_stdout, query_stderr = await _query_until_outputs(args[0], submit_id, int(payload.poll or 30))
    message = ""
    if not images and not videos:
        message = "Dreamina CLI returned no media output."
        if submit_id:
            message += f" submit_id={submit_id}. Open Dreamina history or run query_result to check whether the task failed."
    return {
        "mode": mode,
        "images": images,
        "videos": videos,
        "submit_id": submit_id,
        "message": "Dreamina CLI returned no media output." if not images and not videos else "",
        "request": {
            "mode": mode,
            "inputs": len(local_inputs),
            "command": [args[0], args[1]],
        },
        "raw": {
            "returncode": proc.returncode,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "query_stdout": query_stdout[-4000:],
            "query_stderr": query_stderr[-4000:],
        },
    }


async def query_dreamina_media(submit_id: str, kind: str = "image", cli_path: str = "", timeout: int = 300) -> Dict[str, Any]:
    cli = _clean_cli_path(cli_path)
    proc = await _query_result(cli, submit_id, timeout)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = "\n".join([stdout, stderr])
    if proc.returncode != 0:
        return {
            "status": "failed",
            "submit_id": submit_id,
            "kind": kind,
            "error": (stderr or stdout or "Dreamina query_result failed.")[:1200],
            "raw": {"returncode": proc.returncode, "stdout": stdout[-4000:], "stderr": stderr[-4000:]},
        }
    images, videos = await _localize_outputs(_media_urls(combined), _local_outputs(combined))
    outputs = videos if str(kind or "").lower() == "video" else images or videos
    if outputs:
        return {
            "status": "succeeded",
            "submit_id": submit_id,
            "kind": kind,
            "images": images,
            "videos": videos,
            "urls": outputs,
            "raw": {"returncode": proc.returncode, "stdout": stdout[-4000:], "stderr": stderr[-4000:]},
        }
    status_text = combined.lower()
    status = "failed" if any(flag in status_text for flag in ["fail", "error", "invalid"]) else "pending"
    return {
        "status": status,
        "submit_id": submit_id,
        "kind": kind,
        "message": "Dreamina task has no media yet." if status == "pending" else "Dreamina task failed or returned no media.",
        "raw": {"returncode": proc.returncode, "stdout": stdout[-4000:], "stderr": stderr[-4000:]},
    }
