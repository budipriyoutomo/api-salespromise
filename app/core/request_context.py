"""`request_id` per request, disimpan di contextvar.

Contextvar dipilih karena ikut terbawa ke thread pool: endpoint `def` biasa
dijalankan FastAPI lewat `anyio.to_thread`, yang menyalin context pemanggil.
Dengan begitu `logger.info(...)` di service mana pun otomatis membawa id yang
sama tanpa harus meneruskan parameter ke setiap fungsi.
"""

import re
import uuid
from contextvars import ContextVar
from typing import Optional

REQUEST_ID_HEADER = "X-Request-ID"

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

# Id dari klien ikut tertulis ke log. Karakter dibatasi supaya tidak bisa
# menyisipkan baris log palsu (newline) atau memecah format teks/JSON.
_POLA_ID_AMAN = re.compile(r"[A-Za-z0-9._\-]{1,128}")


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


def sanitize_request_id(value: Optional[str]) -> Optional[str]:
    """Kembalikan id dari klien kalau aman dipakai, selain itu `None`."""
    if not value or not _POLA_ID_AMAN.fullmatch(value):
        return None
    return value
