"""Endpoint closing report dari RabbitMQ (TODO Fase 7.6).

- `/api/closing-menus`    admin — mapping menuCode → ProductID × pengali.
                          Pilihan ProductID: `/api/product-menus/candidates`.
- `/api/closing-reports`  user dashboard, ter-scope outlet lewat
                          `resolve_outlet_scope` — daftar, detail, dan
                          perbandingan closing vs POS.
- `/api/closing-messages` admin — log setiap pesan RabbitMQ yang diterima
                          consumer (termasuk duplikat dan yang ditolak) beserta
                          JSON aslinya.

Data closing hanya ditulis oleh consumer; tidak ada endpoint tulis laporan.
"""

from datetime import date as date_type
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_roles, resolve_outlet_scope
from app.models.user import ROLE_ADMIN, User
from app.schemas.closing_schema import (
    ClosingComparisonResponse,
    ClosingComparisonRow,
    ClosingMenuListResponse,
    ClosingMenuProductDetailResponse,
    ClosingMenuProductResponse,
    ClosingMenuResponse,
    ClosingMessageCounts,
    ClosingMessageDetail,
    ClosingMessageDetailResponse,
    ClosingMessageListResponse,
    ClosingMessageSummary,
    ClosingReportDetail,
    ClosingReportDetailResponse,
    ClosingReportListResponse,
    ClosingReportSummary,
    CreateClosingMenuProductRequest,
    UpdateClosingMenuProductRequest,
)
from app.schemas.sales_response import PaginationMeta
from app.services import closing_menu_service, closing_message_log_service, closing_report_service
from app.utils.logger import logger

require_admin = require_roles(ROLE_ADMIN)


# ---------------------------------------------------------------------------
# Mapping menu (admin)
# ---------------------------------------------------------------------------

closing_menu_router = APIRouter(prefix="/api/closing-menus", tags=["Admin - Closing Menus"])


@closing_menu_router.get("", response_model=ClosingMenuListResponse)
def list_closing_menus(
    status_: Literal["all", "mapped", "unmapped"] = Query("all", alias="status"),
    q: Optional[str] = Query(None, max_length=100, description="Cari menuCode atau nama menu"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """menuCode yang pernah muncul di closing report. `unmapped` = belum punya mapping aktif."""
    rows = closing_menu_service.list_menus(db, status=status_, q=q)

    return ClosingMenuListResponse(data=[ClosingMenuResponse.model_validate(row) for row in rows])


@closing_menu_router.post(
    "/{menu_id}/products",
    response_model=ClosingMenuProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_closing_menu_product(
    menu_id: int,
    payload: CreateClosingMenuProductRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Hitung menu closing ini dari `product_id` POS × `multiplier`."""
    try:
        row = closing_menu_service.add_product(
            db, menu_id, payload.product_id, multiplier=payload.multiplier, is_active=payload.is_active
        )
    except closing_menu_service.MenuTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu closing tidak ditemukan")
    except closing_menu_service.ProductSudahAda:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ProductID {payload.product_id} sudah dipetakan ke menu ini. Ubah lewat PATCH.",
        )
    except closing_menu_service.ProductTidakAdaDiData:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ProductID {payload.product_id} tidak ditemukan di data penjualan.",
        )

    logger.info(
        f"CLOSING MENU PRODUCT DIBUAT menu_id={menu_id} product_id={row.product_id} "
        f"x{row.multiplier} aktif={row.is_active} oleh={admin.email}"
    )

    return ClosingMenuProductDetailResponse(data=ClosingMenuProductResponse.model_validate(row))


@closing_menu_router.patch("/{menu_id}/products/{mapping_id}", response_model=ClosingMenuProductDetailResponse)
def update_closing_menu_product(
    menu_id: int,
    mapping_id: int,
    payload: UpdateClosingMenuProductRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ubah pengali / aktifkan / nonaktifkan. Berlaku langsung di laporan perbandingan."""
    try:
        row = closing_menu_service.update_product(
            db, menu_id, mapping_id, multiplier=payload.multiplier, is_active=payload.is_active
        )
    except closing_menu_service.MappingTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping tidak ditemukan")

    logger.info(
        f"CLOSING MENU PRODUCT DIUBAH menu_id={menu_id} product_id={row.product_id} "
        f"x{row.multiplier} aktif={row.is_active} oleh={admin.email}"
    )

    return ClosingMenuProductDetailResponse(data=ClosingMenuProductResponse.model_validate(row))


# ---------------------------------------------------------------------------
# Laporan (user dashboard)
# ---------------------------------------------------------------------------

closing_report_router = APIRouter(prefix="/api/closing-reports", tags=["Closing Reports"])


@closing_report_router.get("", response_model=ClosingReportListResponse)
def list_closing_reports(
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    start_date: Optional[date_type] = Query(None, description="Tanggal closing awal (inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal closing akhir (inklusif)"),
    limit: int = Query(closing_report_service.DEFAULT_LIMIT, ge=1, le=closing_report_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    outlet = resolve_outlet_scope(user, outlet)
    rows, total = closing_report_service.list_reports(
        db, outlet=outlet, start_date=start_date, end_date=end_date, limit=limit, offset=offset
    )

    return ClosingReportListResponse(
        data=[ClosingReportSummary.model_validate(row) for row in rows],
        pagination=PaginationMeta(limit=limit, offset=offset, total=total, has_more=offset + len(rows) < total),
    )


# Didaftarkan sebelum `/{closing_report_id}`.
@closing_report_router.get("/comparison", response_model=ClosingComparisonResponse)
def compare_closing_with_pos(
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    start_date: Optional[date_type] = Query(None, description="Tanggal produksi awal (inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal produksi akhir (inklusif)"),
    include_deleted: bool = Query(False, description="Ikutkan transaksi POS Deleted=1"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Colorplate vs POS per outlet / tanggal produksi / menu.

    Angka colorplate apa adanya; `pos_qty` = Σ qty orderdetail outlet & tanggal
    yang sama dari ProductID yang dipetakan ke menu itu (kosong = belum dipetakan).
    """
    outlet = resolve_outlet_scope(user, outlet)
    rows = closing_report_service.compare_with_pos(
        db, outlet=outlet, start_date=start_date, end_date=end_date, include_deleted=include_deleted
    )

    return ClosingComparisonResponse(data=[ClosingComparisonRow.model_validate(row) for row in rows])


@closing_report_router.get("/{closing_report_id}", response_model=ClosingReportDetailResponse)
def get_closing_report(
    closing_report_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    outlet = resolve_outlet_scope(user, None)
    detail = closing_report_service.get_report(db, closing_report_id, outlet=outlet)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Closing report tidak ditemukan")

    return ClosingReportDetailResponse(data=ClosingReportDetail.model_validate(detail))


# ---------------------------------------------------------------------------
# Log pesan RabbitMQ (admin)
# ---------------------------------------------------------------------------

closing_message_router = APIRouter(prefix="/api/closing-messages", tags=["Admin - Closing Messages"])


@closing_message_router.get("", response_model=ClosingMessageListResponse)
def list_closing_messages(
    status_: Optional[Literal["baru", "revisi", "revisi_lama", "duplikat", "ditolak"]] = Query(None, alias="status"),
    q: Optional[str] = Query(None, max_length=100, description="Cari messageId atau kode outlet"),
    start_date: Optional[date_type] = Query(None, description="Tanggal diterima awal (WIB, inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal diterima akhir (WIB, inklusif)"),
    limit: int = Query(closing_message_log_service.DEFAULT_LIMIT, ge=1, le=closing_message_log_service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Pesan terbaru dulu, tanpa payload. `counts` = jumlah per status untuk filter yang sama tanpa `status`."""
    rows, total, jumlah = closing_message_log_service.list_logs(
        db, status=status_, q=q, start_date=start_date, end_date=end_date, limit=limit, offset=offset
    )

    return ClosingMessageListResponse(
        data=[ClosingMessageSummary.model_validate(row) for row in rows],
        pagination=PaginationMeta(limit=limit, offset=offset, total=total, has_more=offset + len(rows) < total),
        counts=ClosingMessageCounts(**jumlah),
    )


@closing_message_router.get("/{log_id}", response_model=ClosingMessageDetailResponse)
def get_closing_message(
    log_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Satu pesan beserta JSON asli (atau teks, kalau bukan JSON) dan detail error validasi."""
    row = closing_message_log_service.get_log(db, log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pesan tidak ditemukan")

    return ClosingMessageDetailResponse(data=ClosingMessageDetail.model_validate(row))
