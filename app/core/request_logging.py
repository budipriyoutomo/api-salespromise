"""Middleware `X-Request-ID` + access log.

Sengaja ASGI murni, bukan `BaseHTTPMiddleware`: yang terakhir menjalankan app
di task terpisah, dan `HTTPException` yang lolos darinya pernah berubah jadi
500 di repo ini (lihat `app/dependencies/auth.py`).
"""

import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import (
    REQUEST_ID_HEADER,
    new_request_id,
    request_id_var,
    sanitize_request_id,
)
from app.utils.logger import logger

# Probe orchestrator dipanggil tiap beberapa detik; mencatatnya hanya menenggelamkan
# log yang penting. Header `X-Request-ID` tetap dipasang.
PATH_TANPA_ACCESS_LOG = frozenset({"/", "/health", "/health/ready"})


class RequestIdMiddleware:

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = sanitize_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER)) or new_request_id()
        token = request_id_var.set(request_id)

        status_code = None
        mulai = time.perf_counter()

        async def send_dengan_header(message: Message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_dengan_header)
        except Exception:
            self._catat(scope, status_code or 500, mulai, exc_info=True)
            raise
        else:
            self._catat(scope, status_code, mulai)
        finally:
            request_id_var.reset(token)

    @staticmethod
    def _catat(scope: Scope, status_code, mulai: float, exc_info=False):
        path = scope["path"]
        if path in PATH_TANPA_ACCESS_LOG:
            return

        durasi_ms = round((time.perf_counter() - mulai) * 1000, 2)

        if status_code is None or status_code >= 500:
            level = "error"
        elif status_code >= 400:
            level = "warning"
        else:
            level = "info"

        # Hanya path, tanpa query string — query bisa memuat email atau data lain
        # yang tidak perlu menumpuk di log.
        getattr(logger, level)(
            f"{scope['method']} {path} {status_code} {durasi_ms}ms",
            exc_info=exc_info,
            extra={
                "event": "http_request",
                "method": scope["method"],
                "path": path,
                "status_code": status_code,
                "duration_ms": durasi_ms,
            },
        )
