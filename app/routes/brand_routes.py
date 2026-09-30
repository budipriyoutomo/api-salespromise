"""Brand dan mapping outlet → brand.

- `GET  /api/brands`                      → admin & manager (sumber dropdown filter `?brand=`)
- `POST /api/brands`, `PATCH /{id}`       → admin
- `GET  /api/brands/outlets`              → admin, semua outlet beserta brand-nya
- `PUT  /api/brands/outlets/{outlet_code}` → admin, petakan / pindahkan / lepas

Tidak ada DELETE: brand dimatikan lewat `is_active`, outlet dilepas dengan
`brand_id: null`.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_roles
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, User
from app.schemas.brand_schema import (
    BrandDetailResponse,
    BrandListResponse,
    BrandResponse,
    CreateBrandRequest,
    OutletBrandDetailResponse,
    OutletBrandListResponse,
    OutletBrandResponse,
    SetOutletBrandRequest,
    UpdateBrandRequest,
)
from app.services import brand_service
from app.utils.logger import logger

router = APIRouter(prefix="/api/brands", tags=["Brands"])

require_admin = require_roles(ROLE_ADMIN)


def _tidak_valid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("", response_model=BrandListResponse)
def list_brands(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER)),
):
    """Semua brand, termasuk yang nonaktif, beserta outlet-nya."""
    rows = brand_service.list_brands(db)

    return BrandListResponse(data=[BrandResponse.model_validate(row) for row in rows])


@router.post("", response_model=BrandDetailResponse, status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: CreateBrandRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        row = brand_service.create_brand(db, payload.code, payload.name, is_active=payload.is_active)
    except brand_service.BrandSudahAda as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand '{exc}' sudah terdaftar. Aktifkan lewat PATCH kalau sedang nonaktif.",
        )
    except brand_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(f"BRAND DIBUAT code={row.code!r} nama={row.name!r} aktif={row.is_active} oleh={admin.email}")

    return BrandDetailResponse(data=BrandResponse.model_validate(row))


# Path statis `/outlets` dideklarasikan sebelum `/{brand_id}` — alasan yang
# sama dengan route laporan di sales_routes.


@router.get("/outlets", response_model=OutletBrandListResponse)
def list_outlet_brands(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Semua outlet (dari API key) beserta brand-nya — termasuk yang belum dipetakan."""
    rows = brand_service.list_outlets(db)

    return OutletBrandListResponse(data=[OutletBrandResponse.model_validate(row) for row in rows])


@router.put("/outlets/{outlet_code}", response_model=OutletBrandDetailResponse)
def set_outlet_brand(
    outlet_code: str,
    payload: SetOutletBrandRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Petakan outlet ke brand. Outlet yang sudah punya brand dipindahkan."""
    try:
        row = brand_service.set_outlet_brand(db, outlet_code, payload.brand_id)
    except brand_service.OutletTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet tidak ditemukan")
    except brand_service.BrandTidakDitemukan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Brand id {payload.brand_id} tidak ditemukan",
        )
    except brand_service.BrandNonaktif as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Brand '{exc}' nonaktif. Aktifkan dulu sebelum memetakan outlet.",
        )

    logger.info(f"OUTLET BRAND DIUBAH outlet={outlet_code} brand={row.brand_code!r} oleh={admin.email}")

    return OutletBrandDetailResponse(data=OutletBrandResponse.model_validate(row))


@router.patch("/{brand_id}", response_model=BrandDetailResponse)
def update_brand(
    brand_id: int,
    payload: UpdateBrandRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ubah nama / aktifkan / nonaktifkan brand. Mapping outlet-nya tidak ikut berubah."""
    try:
        row = brand_service.update_brand(db, brand_id, name=payload.name, is_active=payload.is_active)
    except brand_service.BrandTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand tidak ditemukan")
    except brand_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(f"BRAND DIUBAH code={row.code!r} nama={row.name!r} aktif={row.is_active} oleh={admin.email}")

    return BrandDetailResponse(data=BrandResponse.model_validate(row))
