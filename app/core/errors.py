"""Error database yang sifatnya sementara → 503 JSON.

Tiga kasus yang muncul "kadang-kadang" saat data besar:
- query melewati `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`);
- pool koneksi habis, menunggu lebih dari `DB_POOL_TIMEOUT`;
- koneksi ke Postgres putus / ditolak.

Ketiganya bukan bug di request itu, jadi 503 + pesan yang bisa ditindaklanjuti,
bukan 500 teks polos. Detail error database hanya masuk log, tidak ke klien.

Handler ini dipasang lewat `add_exception_handler` untuk kelas spesifik —
ditangani `ExceptionMiddleware` yang ada DI DALAM `RequestIdMiddleware`, jadi
response tetap membawa `X-Request-ID` dan contextvar masih terisi.
"""

import psycopg2.errors
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.request_context import get_request_id
from app.utils.logger import logger

PESAN_QUERY_TERLALU_LAMA = "Permintaan terlalu lama diproses. Persempit rentang tanggal atau filter, lalu coba lagi."
PESAN_SERVER_SIBUK = "Server sedang sibuk. Coba lagi beberapa saat."
PESAN_DATABASE_GANGGUAN = "Koneksi ke database sedang bermasalah. Coba lagi beberapa saat."

# Klien (dan proxy) boleh mencoba lagi setelah jeda ini.
RETRY_AFTER_DETIK = "5"


def _respons(pesan: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": pesan, "request_id": get_request_id()},
        headers={"Retry-After": RETRY_AFTER_DETIK},
    )


def _query_dibatalkan(exc: OperationalError) -> bool:
    return isinstance(getattr(exc, "orig", None), psycopg2.errors.QueryCanceled)


async def database_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
    if _query_dibatalkan(exc):
        logger.error(
            f"QUERY TIMEOUT {request.method} {request.url.path}",
            extra={"event": "db_statement_timeout", "path": request.url.path},
        )
        return _respons(PESAN_QUERY_TERLALU_LAMA)

    logger.error(
        f"DATABASE ERROR {request.method} {request.url.path}: {exc.orig}",
        exc_info=exc,
        extra={"event": "db_operational_error", "path": request.url.path},
    )
    return _respons(PESAN_DATABASE_GANGGUAN)


async def database_pool_timeout(request: Request, exc: PoolTimeoutError) -> JSONResponse:
    logger.error(
        f"POOL DATABASE PENUH {request.method} {request.url.path}: {exc}",
        extra={"event": "db_pool_timeout", "path": request.url.path},
    )
    return _respons(PESAN_SERVER_SIBUK)


# Ditangkap ulang (lalu di-raise) oleh route yang punya `except Exception`
# sendiri, supaya tidak tertelan jadi 500.
ERROR_DATABASE_SEMENTARA = (OperationalError, PoolTimeoutError)


def pasang_handler(app: FastAPI) -> None:
    app.add_exception_handler(OperationalError, database_operational_error)
    app.add_exception_handler(PoolTimeoutError, database_pool_timeout)
