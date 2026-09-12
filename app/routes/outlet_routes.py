"""Endpoint seputar outlet untuk dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_roles, resolve_outlet_scope
from app.models.api_key import ApiKey
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, User
from app.schemas.sales_response import (
    OutletListResponse,
    OutletResponse,
    SyncStatusListResponse,
    SyncStatusRow,
)
from app.services.sales_service import SalesService

router = APIRouter(prefix="/api/outlets", tags=["Outlets"])


@router.get("", response_model=OutletListResponse)
def list_outlets(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER)),
):
    """Daftar outlet untuk dropdown filter.

    Sumbernya tabel `api_keys`: satu outlet = satu key. Hanya role yang berhak
    melihat lintas outlet yang boleh memanggilnya.
    """
    rows = db.query(ApiKey.outlet_code, ApiKey.is_active).order_by(ApiKey.outlet_code).all()

    return OutletListResponse(
        data=[OutletResponse(outlet_code=row.outlet_code, is_active=row.is_active) for row in rows]
    )


@router.get("/sync-status", response_model=SyncStatusListResponse)
def sync_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kapan tiap outlet terakhir mengirim data — untuk mendeteksi outlet yang mati.

    Ditempatkan di sini, bukan di `/api/sync/status` seperti rencana awal:
    prefix `/api/sync` khusus autentikasi API key mesin POS, sedangkan ini
    dibaca manusia lewat dashboard.

    Terbuka untuk semua role, tapi tetap ter-scope — user outlet hanya melihat
    outletnya sendiri.
    """
    outlet = resolve_outlet_scope(user, None)

    rows = SalesService.get_sync_status(db=db, outlet=outlet)

    return SyncStatusListResponse(data=[SyncStatusRow.model_validate(row) for row in rows])
