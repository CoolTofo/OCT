"""GitLab self-update helpers for the local OCT server."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Lock
from typing import Any, Dict, List


DEFAULT_UPDATE_REPO = "aigc/oct_aiflow"
DEFAULT_UPDATE_BRANCH = "master"
DEFAULT_GITLAB_BASE_URL = "http://gitlab.ds.com"


def gitlab_base_url() -> str:
    return os.getenv("OCT_GITLAB_BASE_URL", DEFAULT_GITLAB_BASE_URL).rstrip("/")


def normalized_update_repo() -> str:
    repo = os.getenv("OCT_UPDATE_REPO", DEFAULT_UPDATE_REPO).strip().strip("/")
    for prefix in (
        "https://gitlab.ds.com/",
        "http://gitlab.ds.com/",
        "git@gitlab.ds.com:",
    ):
        if repo.startswith(prefix):
            repo = repo.removeprefix(prefix).strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo or DEFAULT_UPDATE_REPO


def update_branch() -> str:
    return os.getenv("OCT_UPDATE_BRANCH", DEFAULT_UPDATE_BRANCH).strip() or DEFAULT_UPDATE_BRANCH


def gitlab_project_id() -> str:
    return urllib.parse.quote(normalized_update_repo(), safe="")


def gitlab_repo_url() -> str:
    return f"{gitlab_base_url()}/{normalized_update_repo()}"


def gitlab_version_url() -> str:
    return f"{gitlab_repo_url()}/-/raw/{update_branch()}/VERSION"


def gitlab_tree_url(page: int = 1) -> str:
    quoted_ref = urllib.parse.quote(update_branch(), safe="")
    return (
        f"{gitlab_base_url()}/api/v4/projects/{gitlab_project_id()}/repository/tree"
        f"?ref={quoted_ref}&recursive=true&per_page=100&page={int(page)}"
    )


def gitlab_raw_url(path: str) -> str:
    quoted_path = urllib.parse.quote(path, safe="")
    quoted_ref = urllib.parse.quote(update_branch(), safe="")
    return (
        f"{gitlab_base_url()}/api/v4/projects/{gitlab_project_id()}"
        f"/repository/files/{quoted_path}/raw?ref={quoted_ref}"
    )


UPDATE_LOCK = Lock()
GITLAB_TREE_CACHE: Dict[str, Any] = {"etag": "", "data": None, "expires_at": 0.0}


class UpdateBusyError(RuntimeError):
    """Raised when another update or rollback is already running."""


def update_allowed_file(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    if not normalized or any(part in {"", ".", ".."} for part in normalized.split("/")):
        return False
    root_allowed = {
        ".gitignore",
        "AGENTS.md",
        "main.py",
        "requirements.txt",
        "VERSION",
        "启动服务.bat",
        "安装依赖.bat",
        "更新GitLab最新版.bat",
        "更新GitHub最新版.bat",
        "上传到GitLab.bat",
        "上传到GitHub.bat",
        "mac-启动服务.command",
        "mac-修复权限.command",
        "MAC-使用说明.md",
        "MIGRATION_DEV_README.md",
        "换电脑使用说明.txt",
    }
    allowed_dirs = ("app/", "static/", "tools/", "workflows/", "Doc/")
    return normalized in root_allowed or normalized.startswith(allowed_dirs)


def safe_update_target(base_dir: str, path: str) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if not update_allowed_file(rel):
        raise ValueError(f"Update target is not allowed: {rel}")
    target = os.path.abspath(os.path.join(base_dir, *rel.split("/")))
    base = os.path.abspath(base_dir)
    if os.path.commonpath([base, target]) != base:
        raise ValueError(f"Unsafe update path: {rel}")
    return target


def gitlab_headers() -> Dict[str, str]:
    headers = {"User-Agent": "Infinite-Canvas-Updater"}
    token = os.getenv("OCT_GITLAB_TOKEN", "").strip()
    if token:
        headers["PRIVATE-TOKEN"] = token
    return headers


def gitlab_json(url: str, use_etag_cache: bool = False) -> Any:
    headers = gitlab_headers()
    cache_key = url
    if use_etag_cache and cache_key == gitlab_tree_url():
        if GITLAB_TREE_CACHE["data"] and time.time() < GITLAB_TREE_CACHE["expires_at"]:
            return GITLAB_TREE_CACHE["data"]
        if GITLAB_TREE_CACHE["etag"]:
            headers["If-None-Match"] = GITLAB_TREE_CACHE["etag"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            etag = resp.headers.get("ETag", "")
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if use_etag_cache and cache_key == gitlab_tree_url():
                GITLAB_TREE_CACHE.update({
                    "etag": etag,
                    "data": payload,
                    "expires_at": time.time() + 600,
                })
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and use_etag_cache and GITLAB_TREE_CACHE["data"]:
            GITLAB_TREE_CACHE["expires_at"] = time.time() + 600
            return GITLAB_TREE_CACHE["data"]
        raise


def gitlab_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=gitlab_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def gitlab_text(url: str) -> str:
    return gitlab_bytes(url).decode("utf-8-sig", errors="replace").strip()


def gitlab_tree_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    page = 1
    while True:
        chunk = gitlab_json(gitlab_tree_url(page), use_etag_cache=(page == 1))
        if not isinstance(chunk, list) or not chunk:
            break
        entries.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return entries


def read_local_version(base_dir: str) -> str:
    version_path = os.path.join(base_dir, "VERSION")
    try:
        with open(version_path, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def update_status(base_dir: str) -> Dict[str, Any]:
    local_version = read_local_version(base_dir)
    remote_version = gitlab_text(gitlab_version_url())
    return {
        "ok": True,
        "repo": normalized_update_repo(),
        "repo_url": gitlab_repo_url(),
        "branch": update_branch(),
        "local_version": local_version,
        "remote_version": remote_version,
        "update_available": bool(remote_version and remote_version != local_version),
        "checked_at": time.time(),
    }


def schedule_self_restart(base_dir: str, delay_seconds: int = 3) -> bool:
    """Restart the local server from a detached helper process."""
    delay = max(1, int(delay_seconds or 3))
    pid = os.getpid()
    try:
        if os.name == "nt":
            launcher = os.path.join(base_dir, "启动服务.bat")
            if not os.path.exists(launcher):
                launcher = os.path.join(base_dir, "start.bat")
            bat_path = os.path.join(base_dir, "_self_restart.bat")
            script = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                f"timeout /t {delay} /nobreak >nul\r\n"
                f"taskkill /F /PID {pid} >nul 2>&1\r\n"
                f"cd /d \"{base_dir}\"\r\n"
                f"if exist \"{launcher}\" start \"\" \"{launcher}\"\r\n"
                "del \"%~f0\"\r\n"
            )
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            launcher = os.path.join(base_dir, "mac-启动服务.command")
            if not os.path.exists(launcher):
                launcher = os.path.join(base_dir, "start.sh")
            sh_path = os.path.join(base_dir, "_self_restart.sh")
            script = (
                "#!/bin/sh\n"
                f"sleep {delay}\n"
                f"kill -9 {pid} 2>/dev/null\n"
                f"cd \"{base_dir}\"\n"
                f"if [ -x \"{launcher}\" ]; then nohup \"{launcher}\" >/dev/null 2>&1 &\n"
                f"elif [ -f \"{launcher}\" ]; then nohup /bin/sh \"{launcher}\" >/dev/null 2>&1 &\n"
                "fi\n"
                "rm -- \"$0\"\n"
            )
            with open(sh_path, "w", encoding="utf-8") as f:
                f.write(script)
            os.chmod(sh_path, 0o755)
            subprocess.Popen(
                ["/bin/sh", sh_path],
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:
        logging.exception("schedule_self_restart failed: %s", exc)
        return False


def run_update(base_dir: str, data_dir: str, auto_restart: bool = False, restart_delay: int = 3) -> Dict[str, Any]:
    if not UPDATE_LOCK.acquire(blocking=False):
        raise UpdateBusyError("An update or rollback is already running.")
    try:
        local_version = read_local_version(base_dir)
        remote_version = gitlab_text(gitlab_version_url())
        entries = gitlab_tree_entries()
        files = []
        for entry in entries:
            path = str(entry.get("path") or "").replace("\\", "/")
            if entry.get("type") == "blob" and update_allowed_file(path):
                files.append(path)
        if "main.py" not in files:
            files.append("main.py")
        if "VERSION" not in files:
            files.append("VERSION")
        files = sorted(set(files))
        backup_root = os.path.join(data_dir, "update_backups", time.strftime("%Y%m%d-%H%M%S"))
        updated = []
        for rel in files:
            target = safe_update_target(base_dir, rel)
            data = gitlab_bytes(gitlab_raw_url(rel))
            if os.path.exists(target):
                backup_path = os.path.join(backup_root, *rel.split("/"))
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(target, backup_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            temp_path = f"{target}.update_tmp"
            with open(temp_path, "wb") as f:
                f.write(data)
            os.replace(temp_path, target)
            updated.append(rel)
        restart_scheduled = False
        if auto_restart and updated:
            restart_scheduled = schedule_self_restart(base_dir, restart_delay)
        return {
            "ok": True,
            "updated": updated,
            "count": len(updated),
            "backup_dir": backup_root if os.path.exists(backup_root) else "",
            "restart_required": True,
            "restart_scheduled": restart_scheduled,
            "local_version": local_version,
            "remote_version": remote_version,
            "repo_url": gitlab_repo_url(),
            "branch": update_branch(),
        }
    finally:
        UPDATE_LOCK.release()


def list_update_backups(data_dir: str) -> List[Dict[str, Any]]:
    root = os.path.join(data_dir, "update_backups")
    if not os.path.isdir(root):
        return []
    items: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(root), reverse=True):
        backup_path = os.path.join(root, name)
        if not os.path.isdir(backup_path):
            continue
        file_count = 0
        for _, _, files in os.walk(backup_path):
            file_count += len(files)
        try:
            created_at = os.path.getmtime(backup_path)
        except OSError:
            created_at = 0.0
        items.append({
            "name": name,
            "file_count": file_count,
            "created_at": created_at,
        })
    return items


def rollback_update(base_dir: str, data_dir: str, name: str, auto_restart: bool = False, restart_delay: int = 3) -> Dict[str, Any]:
    if not name:
        raise ValueError("Backup name is required.")
    if not UPDATE_LOCK.acquire(blocking=False):
        raise UpdateBusyError("An update or rollback is already running.")
    try:
        backup_root_abs = os.path.abspath(os.path.join(data_dir, "update_backups"))
        backup_dir = os.path.abspath(os.path.join(backup_root_abs, name))
        if os.path.commonpath([backup_root_abs, backup_dir]) != backup_root_abs:
            raise ValueError("Unsafe backup path.")
        if not os.path.isdir(backup_dir):
            raise FileNotFoundError("Backup does not exist.")
        restored = []
        skipped = []
        for dirpath, _, filenames in os.walk(backup_dir):
            for filename in filenames:
                src = os.path.join(dirpath, filename)
                rel = os.path.relpath(src, backup_dir).replace("\\", "/")
                if not update_allowed_file(rel):
                    skipped.append(rel)
                    continue
                try:
                    target = safe_update_target(base_dir, rel)
                except ValueError:
                    skipped.append(rel)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                temp_path = f"{target}.rollback_tmp"
                with open(src, "rb") as fin, open(temp_path, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                os.replace(temp_path, target)
                restored.append(rel)
        restart_scheduled = False
        if auto_restart and restored:
            restart_scheduled = schedule_self_restart(base_dir, restart_delay)
        return {
            "ok": True,
            "restored": restored,
            "skipped": skipped,
            "count": len(restored),
            "restart_required": True,
            "restart_scheduled": restart_scheduled,
        }
    finally:
        UPDATE_LOCK.release()
