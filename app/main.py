from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routes.admin_routes import api_key_router, user_router
from app.routes.auth_routes import router as auth_router
from app.routes.outlet_routes import router as outlet_router
from app.routes.sales_routes import router as sales_router
from app.routes.sync_routes import router as sync_router
from app.utils.logger import logger

app = FastAPI(
    title="Sales Sync API",
    version="2.0.0",
    description=(
        "Sinkronisasi transaksi outlet (API key) dan endpoint baca untuk "
        "dashboard frontend terpisah (JWT)."
    ),
)

# Frontend berjalan di origin lain, jadi browser butuh izin eksplisit.
# Origin didaftarkan lewat env CORS_ORIGINS (dipisah koma) — bukan "*",
# supaya daftar yang boleh mengakses tetap terkendali.
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,  # token dikirim lewat header, bukan cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Autentikasi dipasang per-router / per-route lewat dependency, bukan middleware
# global — lihat app/dependencies/auth.py.
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(sales_router)
app.include_router(outlet_router)
app.include_router(api_key_router)
app.include_router(user_router)


@app.get("/", tags=["Health"])
def health():
    """Endpoint publik — dipakai monitoring, tidak boleh butuh API key."""
    return {"status": "ok"}


@app.get("/health", tags=["Health"])
def health_alias():
    """Liveness probe — sengaja tidak menyentuh database.

    Kalau probe ini ikut gagal saat database sedang bermasalah, orchestrator
    akan me-restart container yang sebenarnya sehat.
    """
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
def health_ready(db: Session = Depends(get_db)):
    """Readiness probe — memeriksa database sungguhan.

    Mengembalikan 503 supaya load balancer mengeluarkan instance ini dari
    rotasi selama koneksi database bermasalah.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"READINESS GAGAL: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "error"},
        )

    return {"status": "ok", "database": "ok"}
