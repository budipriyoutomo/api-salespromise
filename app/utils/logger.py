"""Konfigurasi logging aplikasi (item 3.7).

`LOG_FORMAT=json` (default) — satu objek JSON per baris, siap dibaca
Loki/ELK/CloudWatch. `LOG_FORMAT=text` — mudah dibaca manusia saat develop.
Keduanya membawa `request_id` dari `app.core.request_context`.

Field tambahan cukup lewat `extra`:

    logger.info("SYNC SUCCESS", extra={"outlet": outlet, "items": 12})
"""

import copy
import json
import logging
import os
from datetime import datetime, timezone

from app.config import settings
from app.core.request_context import get_request_id

LOGGER_NAME = "sync-api"
TEXT_FORMAT = "%(asctime)s | %(levelname)s | %(request_id)s | %(message)s"

# Atribut bawaan LogRecord — yang di luar daftar ini berasal dari `extra`.
_ATRIBUT_BAWAAN = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
    "request_id",
}


class RequestIdFilter(logging.Filter):
    """Menempelkan `request_id` ke record saat dicatat, bukan saat diformat.

    Handler bisa memformat belakangan — setelah request selesai dan contextvar
    sudah di-reset — jadi nilainya harus diambil sedini mungkin.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }

        # Field inti tidak boleh ditimpa `extra` — kalau tidak, satu log yang ceroboh
        # bisa memalsukan `level` atau `timestamp` di sistem pencarian log.
        for key, value in record.__dict__.items():
            if key not in _ATRIBUT_BAWAAN and not key.startswith("_") and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):

    def __init__(self):
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        # Salinan, supaya "-" tidak ikut terlihat oleh handler lain yang memakai record yang sama.
        salinan = copy.copy(record)
        salinan.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        return super().format(salinan)


def build_formatter(fmt: str) -> logging.Formatter:
    return TextFormatter() if fmt == "text" else JsonFormatter()


def configure_logging(level: str, fmt: str, filename: str) -> logging.Logger:
    """Pasang handler file di root logger. Aman dipanggil berulang."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    folder = os.path.dirname(filename)
    if folder:
        os.makedirs(folder, exist_ok=True)

    handler = logging.FileHandler(filename, encoding="utf-8")
    handler.setFormatter(build_formatter(fmt))
    handler.addFilter(RequestIdFilter())
    handler._sync_api_handler = True

    root = logging.getLogger()
    for lama in [h for h in root.handlers if getattr(h, "_sync_api_handler", False)]:
        root.removeHandler(lama)
        lama.close()
    root.addHandler(handler)
    root.setLevel(log_level)

    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(log_level)
    if not any(isinstance(f, RequestIdFilter) for f in app_logger.filters):
        app_logger.addFilter(RequestIdFilter())

    return app_logger


logger = configure_logging(
    level=settings.LOG_LEVEL,
    fmt=settings.LOG_FORMAT,
    filename=settings.LOG_FILE,
)
