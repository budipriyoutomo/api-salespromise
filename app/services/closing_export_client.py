"""HTTP ke API tujuan rekap closing (TODO Fase 8.5).

Aturan response mengikuti docs/usulan-kontrak-kirim-closing.md bagian 3:

    2xx                     terkirim
    409                     duplikat — isi sudah ada di API tujuan
    4xx lain                gagal, tidak diulang
    429 / 5xx / timeout /   diulang `max_retries` kali dengan body dan
    koneksi gagal           `Idempotency-Key` yang sama, lalu gagal

Tidak pernah melempar exception; token tidak ikut dicatat.
"""

import json
import time
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

MAX_RESPONSE_BODY = 2000
# Batas jeda antar percobaan, termasuk yang diminta lewat Retry-After —
# admin menunggu di depan layar.
MAX_JEDA = 30


@dataclass
class HasilKirim:
    status: Literal["terkirim", "duplikat", "gagal"]
    http_status: Optional[int]
    response_body: Optional[str]
    error: Optional[str]
    attempts: int


def _jeda(percobaan: int, response: httpx.Response | None) -> float:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after and retry_after.strip().isdigit():
        return min(int(retry_after), MAX_JEDA)
    return min(2**percobaan, MAX_JEDA)


def kirim(
    payload: dict,
    *,
    message_id: str,
    url: str,
    token: str,
    timeout: float,
    max_retries: int,
    transport: httpx.BaseTransport | None = None,
    sleep=time.sleep,
) -> HasilKirim:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": message_id,
    }
    # Body yang sama persis di setiap percobaan.
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    response = None
    error = None
    attempts = 0
    with httpx.Client(timeout=timeout, transport=transport) as client:
        for percobaan in range(max_retries + 1):
            if percobaan:
                sleep(_jeda(percobaan - 1, response))
            attempts += 1
            response, error = None, None
            try:
                response = client.post(url, content=body, headers=headers)
            except httpx.TimeoutException:
                error = "timeout"
                continue
            except httpx.HTTPError as e:
                # Pesan httpx bisa memuat URL, tetapi tidak pernah header.
                error = f"koneksi gagal: {type(e).__name__}"
                continue

            kode = response.status_code
            if 200 <= kode < 300:
                return _hasil("terkirim", response, None, attempts)
            if kode == 409:
                return _hasil("duplikat", response, None, attempts)
            if kode != 429 and kode < 500:
                return _hasil("gagal", response, f"HTTP {kode}", attempts)
            error = f"HTTP {kode}"

    return _hasil("gagal", response, error, attempts)


def _hasil(status, response: httpx.Response | None, error, attempts) -> HasilKirim:
    return HasilKirim(
        status=status,
        http_status=response.status_code if response is not None else None,
        response_body=(response.text[:MAX_RESPONSE_BODY] or None) if response is not None else None,
        error=error,
        attempts=attempts,
    )
