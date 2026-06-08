"""Logging setup helpers for the FastAPI/uvicorn app."""

import logging


QUIET_ACCESS_PATHS = {
    "/api/queue_status",
    "/api/canvases",
    "/api/canvases/trash",
}

QUIET_ACCESS_PREFIXES = (
    "/api/canvases/",
)


class QuietAccessLogFilter(logging.Filter):
    """Suppress noisy successful polling requests from uvicorn access logs."""

    def filter(self, record):
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 3:
            path = str(args[2]).split("?", 1)[0]
            status = int(args[4]) if len(args) >= 5 and str(args[4]).isdigit() else 0
            quiet_dynamic = any(
                path.startswith(prefix) and path.endswith("/meta")
                for prefix in QUIET_ACCESS_PREFIXES
            )
            if (path in QUIET_ACCESS_PATHS or quiet_dynamic) and status < 400:
                return False

        message = record.getMessage()
        if any(f'"GET {path}' in message and '" 200' in message for path in QUIET_ACCESS_PATHS):
            return False
        if 'GET /api/canvases/' in message and '/meta' in message and '" 200' in message:
            return False
        return True


def configure_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, QuietAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(QuietAccessLogFilter())

