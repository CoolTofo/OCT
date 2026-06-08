"""FastAPI application bootstrap helpers."""

import logging
import os
import subprocess
import sys
import time
import urllib.request
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


def setup_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_static_files(app: FastAPI, *, static_dir: str, output_dir: str, assets_dir: str) -> None:
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/output", StaticFiles(directory=output_dir), name="output")
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


def setup_no_cache_for_ui_assets(app: FastAPI) -> None:
    @app.middleware("http")
    async def no_cache_for_ui_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            if path == "/" or path.endswith((".html", ".js", ".css")):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
        return response


def setup_validation_error_handler(app: FastAPI, friendly_validation_error) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": friendly_validation_error(exc.errors()), "errors": exc.errors()},
        )


def schedule_open_local_browser(port: int) -> None:
    if str(os.getenv("OCT_OPEN_BROWSER", "")).lower() not in ("1", "true", "yes", "on"):
        return
    url = f"http://127.0.0.1:{port}/"

    def worker() -> None:
        for _ in range(80):
            try:
                with urllib.request.urlopen(url, timeout=1):
                    break
            except Exception:
                time.sleep(0.5)
        try:
            if os.name == "nt":
                os.startfile(url)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
        except Exception as exc:
            logging.warning("Failed to open browser automatically: %s", exc)

    Thread(target=worker, daemon=True).start()
