"""Master data product dan mapping ProductID POS → produk.

- `GET   /api/products`, `/{id}`                    → admin & manager
- `POST  /api/products`, `PATCH /{id}`              → admin
- `GET   /api/products/pos-candidates`              → admin, ProductID per outlet dari penjualan
- `GET   /api/products/import-candidates`           → admin, (brand, ProductID) yang bisa diimpor
- `POST  /api/products/import`                      → admin, buat produk master dari penjualan
- `POST  /api/products/{id}/pos-mappings`           → admin, petakan (outlet, ProductID)
- `PATCH /api/products/{id}/pos-mappings/{mapping}` → admin, aktifkan / nonaktifkan

Tidak ada DELETE: produk dan mapping dimatikan lewat `is_active`.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_roles
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, User
from app.schemas.product_schema import (
    CreatePosMappingRequest,
    CreateProductRequest,
    ImportCandidateListResponse,
    ImportCandidateResponse,
    ImportProductsRequest,
    ImportProductsResponse,
    ImportResult,
    ImportSummary,
    PosCandidateListResponse,
    PosCandidateResponse,
    ProductDetailResponse,
    ProductListResponse,
    ProductResponse,
    UpdatePosMappingRequest,
    UpdateProductRequest,
)
from app.services import product_service
from app.utils.logger import logger

router = APIRouter(prefix="/api/products", tags=["Products"])

require_admin = require_roles(ROLE_ADMIN)
require_reader = require_roles(ROLE_ADMIN, ROLE_MANAGER)


def _tidak_valid(pesan) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(pesan))


def _tidak_ditemukan() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produk tidak ditemukan")


def _product_code_bentrok(product_code) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Product Code '{product_code}' sudah dipakai produk lain.",
    )


def _detail(row) -> ProductDetailResponse:
    return ProductDetailResponse(data=ProductResponse.model_validate(row))


@router.get("", response_model=ProductListResponse)
def list_products(db: Session = Depends(get_db), _user: User = Depends(require_reader)):
    """Semua produk, termasuk yang nonaktif, beserta mapping POS-nya."""
    rows = product_service.list_products(db)

    return ProductListResponse(data=[ProductResponse.model_validate(row) for row in rows])


@router.post("", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: CreateProductRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        row = product_service.create_product(
            db,
            payload.code,
            payload.product_code,
            payload.name,
            brand_id=payload.brand_id,
            category=payload.category,
            subcategory=payload.subcategory,
            is_active=payload.is_active,
        )
    except product_service.ProdukSudahAda as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Produk '{exc}' sudah terdaftar. Aktifkan lewat PATCH kalau sedang nonaktif.",
        )
    except product_service.ProductCodeSudahAda as exc:
        raise _product_code_bentrok(exc)
    except (product_service.DataTidakValid, product_service.BrandTidakValid) as exc:
        raise _tidak_valid(exc)

    logger.info(f"PRODUK DIBUAT code={row.code!r} nama={row.name!r} aktif={row.is_active} oleh={admin.email}")

    return _detail(row)


# Path statis `/pos-candidates` dideklarasikan sebelum `/{product_id}` — alasan
# yang sama dengan route laporan di sales_routes.


@router.get("/pos-candidates", response_model=PosCandidateListResponse)
def list_pos_candidates(
    outlet: Optional[str] = Query(None, description="Batasi ke satu outlet"),
    q: Optional[str] = Query(None, description="Cari nama produk POS atau ProductID persis"),
    limit: int = Query(
        product_service.CANDIDATE_DEFAULT_LIMIT,
        ge=1,
        le=product_service.CANDIDATE_MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """ProductID per outlet dari data penjualan, beserta produk master yang memetakannya."""
    rows = product_service.list_pos_candidates(db, outlet=outlet, q=q, limit=limit)

    return PosCandidateListResponse(data=[PosCandidateResponse.model_validate(row) for row in rows])


@router.get("/import-candidates", response_model=ImportCandidateListResponse)
def list_import_candidates(
    brand_id: Optional[int] = Query(None, gt=0, description="Batasi ke satu brand"),
    q: Optional[str] = Query(None, description="Cari nama produk POS atau ProductID persis"),
    limit: int = Query(
        product_service.IMPORT_CANDIDATE_DEFAULT_LIMIT,
        ge=1,
        le=product_service.IMPORT_CANDIDATE_MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Produk POS per (brand, ProductID) yang masih punya outlet belum dipetakan.

    Hanya outlet yang sudah dipetakan ke brand aktif yang ikut.
    """
    rows = product_service.list_import_candidates(db, brand_id=brand_id, q=q, limit=limit)

    return ImportCandidateListResponse(data=[ImportCandidateResponse.model_validate(row) for row in rows])


@router.post("/import", response_model=ImportProductsResponse)
def import_products(
    payload: ImportProductsRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Buat produk `BRAND-ProductID` (atau tambah outlet ke produk itu) dari penjualan.

    Item yang tidak bisa diimpor dilewati dengan alasannya; yang lain tetap tersimpan.
    """
    hasil = product_service.import_from_pos(db, [(i.brand_id, i.pos_product_id) for i in payload.items])
    jumlah = {s: sum(1 for h in hasil if h.status == s) for s in ("dibuat", "ditambahkan", "dilewati")}

    logger.info(
        f"PRODUK DIIMPOR dibuat={jumlah['dibuat']} ditambahkan={jumlah['ditambahkan']} "
        f"dilewati={jumlah['dilewati']} oleh={admin.email}"
    )

    return ImportProductsResponse(
        data=ImportSummary(
            created=jumlah["dibuat"],
            added=jumlah["ditambahkan"],
            skipped=jumlah["dilewati"],
            results=[ImportResult.model_validate(h) for h in hasil],
        )
    )


@router.get("/{product_id}", response_model=ProductDetailResponse)
def get_product(product_id: int, db: Session = Depends(get_db), _user: User = Depends(require_reader)):
    row = product_service.get_by_id(db, product_id)
    if not row:
        raise _tidak_ditemukan()

    return _detail(row)


@router.patch("/{product_id}", response_model=ProductDetailResponse)
def update_product(
    product_id: int,
    payload: UpdateProductRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ubah field yang dikirim. `null` untuk category / subcategory mengosongkannya."""
    try:
        row = product_service.update_product(db, product_id, payload.changes())
    except product_service.ProdukTidakDitemukan:
        raise _tidak_ditemukan()
    except product_service.ProductCodeSudahAda as exc:
        raise _product_code_bentrok(exc)
    except (product_service.DataTidakValid, product_service.BrandTidakValid) as exc:
        raise _tidak_valid(exc)

    logger.info(
        f"PRODUK DIUBAH code={row.code!r} field={sorted(payload.model_fields_set)} aktif={row.is_active} oleh={admin.email}"
    )

    return _detail(row)


@router.post(
    "/{product_id}/pos-mappings",
    response_model=ProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_pos_mapping(
    product_id: int,
    payload: CreatePosMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Petakan ProductID POS satu outlet ke produk ini."""
    try:
        row = product_service.add_pos_mapping(db, product_id, payload.outlet_code, payload.pos_product_id)
    except product_service.ProdukTidakDitemukan:
        raise _tidak_ditemukan()
    except product_service.ProdukNonaktif as exc:
        raise _tidak_valid(f"Produk '{exc}' nonaktif. Aktifkan dulu sebelum memetakan ProductID.")
    except product_service.PosTidakAdaDiData:
        raise _tidak_valid(
            f"ProductID {payload.pos_product_id} tidak pernah muncul di penjualan outlet {payload.outlet_code}"
        )
    except product_service.PosSudahDipetakan as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ProductID {payload.pos_product_id} outlet {payload.outlet_code} sudah aktif di produk '{exc}'. "
            "Nonaktifkan dulu di sana sebelum memindahkannya.",
        )
    except product_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(
        f"PRODUK POS DIPETAKAN code={row.code!r} outlet={payload.outlet_code} "
        f"pos_product_id={payload.pos_product_id} oleh={admin.email}"
    )

    return _detail(row)


@router.patch("/{product_id}/pos-mappings/{mapping_id}", response_model=ProductDetailResponse)
def update_pos_mapping(
    product_id: int,
    mapping_id: int,
    payload: UpdatePosMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        row = product_service.set_pos_mapping_active(db, product_id, mapping_id, payload.is_active)
    except product_service.ProdukTidakDitemukan:
        raise _tidak_ditemukan()
    except product_service.MappingTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping tidak ditemukan")

    logger.info(
        f"PRODUK POS DIUBAH code={row.code!r} mapping={mapping_id} aktif={payload.is_active} oleh={admin.email}"
    )

    return _detail(row)
