import csv
import io
import json
from datetime import date as date_type
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import (
    get_current_user,
    require_api_key,
    require_roles,
    resolve_outlet_scope,
)
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, User
from app.schemas.sales_event import PublishSalesRequest
from app.schemas.sales_response import (
    ColorplateListResponse,
    ColorplateRow,
    DailyListResponse,
    DailyRow,
    OutletSalesListResponse,
    OutletSalesRow,
    PaginationMeta,
    ProductGroupListResponse,
    ProductGroupSalesListResponse,
    ProductGroupSalesRow,
    PublishResponse,
    SaleDetail,
    SaleDetailResponse,
    SaleItemResponse,
    SaleResponse,
    SalesListResponse,
    SummaryData,
    SummaryResponse,
    TopProductListResponse,
    TopProductRow,
)
from app.services import product_group_service
from app.services.rabbitmq import RabbitMQClient
from app.services.sales_service import SalesService
from app.utils.logger import logger

router = APIRouter(prefix="/api/sales", tags=["Sales"])


def get_rabbitmq_client():
    """Client RabbitMQ per request, ditutup setelah request selesai.

    Sebelumnya client dibuat tiap request dan tidak pernah `close()` — koneksi
    broker menumpuk sampai batas maksimum.

    Sengaja TIDAK dijadikan singleton: `pika.BlockingConnection` tidak
    thread-safe, sedangkan endpoint sync FastAPI dijalankan di threadpool.
    Publish frekuensinya rendah, jadi satu koneksi per request masih murah.
    """
    client = RabbitMQClient()
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception as e:
            # Gagal menutup koneksi tidak boleh mengubah response yang sudah sukses
            logger.warning(f"[RABBITMQ] gagal menutup koneksi: {e}")


@router.get("/", response_model=SalesListResponse)
def get_sales(
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    start_date: Optional[date_type] = Query(None, description="Tanggal awal (inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal akhir (inklusif)"),
    limit: int = Query(SalesService.DEFAULT_LIMIT, ge=1, le=SalesService.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Outlet ditentukan identitas, bukan query param — user 'outlet' tidak bisa
    # membaca data outlet lain sekalipun mengirim ?outlet=
    outlet = resolve_outlet_scope(user, outlet)

    try:
        rows = SalesService.get_sales(
            db=db,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        total = SalesService.count_sales(
            db=db,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
        )

    except Exception as e:
        logger.error(f"GET SALES ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch sales")

    return SalesListResponse(
        data=[SaleResponse.model_validate(row) for row in rows],
        pagination=PaginationMeta(
            limit=limit,
            offset=offset,
            total=total,
            has_more=offset + len(rows) < total,
        ),
    )


@router.get("/colorplate", response_model=ColorplateListResponse)
def get_sales_colorplate(
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    start_date: Optional[date_type] = Query(None, description="Tanggal awal (inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal akhir (inklusif)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    outlet = resolve_outlet_scope(user, outlet)

    try:
        rows = SalesService.get_sales_colorplate(
            db=db,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
        )

    except Exception as e:
        logger.error(f"GET COLORPLATE SALES ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch colorplate sales")

    return ColorplateListResponse(data=[ColorplateRow.model_validate(row) for row in rows])


@router.get("/by-group", response_model=ProductGroupSalesListResponse)
def get_sales_by_group(
    product_group: List[str] = Query(
        ...,
        description="Nama product group; ulangi param untuk beberapa group. Tidak peka huruf besar/kecil dan spasi di ujung.",
    ),
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    start_date: Optional[date_type] = Query(None, description="Tanggal awal (inklusif)"),
    end_date: Optional[date_type] = Query(None, description="Tanggal akhir (inklusif)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rekap qty terjual per product group — versi dinamis dari `/colorplate`."""
    outlet = resolve_outlet_scope(user, outlet)

    if not any(product_group_service.normalize_product_group(g) for g in product_group):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="product_group tidak boleh kosong",
        )

    rows = SalesService.get_sales_by_product_groups(
        db=db,
        product_groups=product_group,
        outlet=outlet,
        start_date=start_date,
        end_date=end_date,
    )

    return ProductGroupSalesListResponse(data=[ProductGroupSalesRow.model_validate(row) for row in rows])


@router.get("/product-groups", response_model=ProductGroupListResponse)
def list_product_groups(
    outlet: Optional[str] = Query(None, description="Kode outlet; diabaikan untuk role 'outlet'"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Group yang pernah muncul di data penjualan, untuk dropdown.

    Berbeda dari `/api/product-groups` (admin): itu daftar group yang
    DIPUBLISH, ini daftar group yang ADA di data.
    """
    outlet = resolve_outlet_scope(user, outlet)

    return ProductGroupListResponse(data=SalesService.list_product_groups(db=db, outlet=outlet))


# ---------------------------------------------------------------------------
# Laporan dashboard
# ---------------------------------------------------------------------------
#
# PENTING: route dengan path statis (/summary, /daily, ...) harus dideklarasikan
# SEBELUM /{transaction_id}, kalau tidak FastAPI akan mencoba membaca "summary"
# sebagai angka dan mengembalikan 422.


@router.get("/summary", response_model=SummaryResponse)
def get_summary(
    outlet: Optional[str] = Query(None),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kartu ringkasan di atas dashboard. Transaksi terhapus tidak dihitung."""
    outlet = resolve_outlet_scope(user, outlet)

    hasil = SalesService.get_summary(db=db, outlet=outlet, start_date=start_date, end_date=end_date)

    return SummaryResponse(data=SummaryData(**hasil))


@router.get("/daily", response_model=DailyListResponse)
def get_daily(
    outlet: Optional[str] = Query(None),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Time series harian untuk grafik."""
    outlet = resolve_outlet_scope(user, outlet)

    rows = SalesService.get_daily_sales(db=db, outlet=outlet, start_date=start_date, end_date=end_date)

    return DailyListResponse(data=[DailyRow.model_validate(row) for row in rows])


@router.get("/by-outlet", response_model=OutletSalesListResponse)
def get_by_outlet(
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_MANAGER)),
):
    """Perbandingan antar outlet — bukan hak user yang terikat satu outlet."""
    rows = SalesService.get_sales_by_outlet(db=db, start_date=start_date, end_date=end_date)

    return OutletSalesListResponse(data=[OutletSalesRow.model_validate(row) for row in rows])


@router.get("/top-products", response_model=TopProductListResponse)
def get_top_products(
    outlet: Optional[str] = Query(None),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    product_group: Optional[str] = Query(None),
    limit: int = Query(
        SalesService.TOP_PRODUCTS_DEFAULT_LIMIT,
        ge=1,
        le=SalesService.TOP_PRODUCTS_MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    outlet = resolve_outlet_scope(user, outlet)

    rows = SalesService.get_top_products(
        db=db,
        outlet=outlet,
        start_date=start_date,
        end_date=end_date,
        product_group=product_group,
        limit=limit,
    )

    return TopProductListResponse(data=[TopProductRow.model_validate(row) for row in rows])


EXPORT_COLUMNS = [
    "transaction_id",
    "outlet_code",
    "sale_date",
    "paid_time",
    "receipt_id",
    "reference_no",
    "receipt_total_amount",
    "receipt_pay_price",
    "receipt_discount",
    "transaction_status_id",
]


@router.get("/export")
def export_sales(
    outlet: Optional[str] = Query(None),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unduh transaksi sebagai CSV.

    Tidak memakai pagination — ini memang dimaksudkan untuk menarik seluruh
    hasil filter. Batasi dengan rentang tanggal untuk data yang besar.
    """
    outlet = resolve_outlet_scope(user, outlet)

    rows = SalesService.get_sales_for_export(
        db=db,
        outlet=outlet,
        start_date=start_date,
        end_date=end_date,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)

    for row in rows:
        writer.writerow([getattr(row, column, "") for column in EXPORT_COLUMNS])

    buffer.seek(0)
    nama_file = f"sales-{outlet or 'semua'}-{datetime.now(timezone.utc).date()}.csv"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nama_file}"'},
    )


@router.get("/{transaction_id}", response_model=SaleDetailResponse)
def get_sale_detail(
    transaction_id: int = Path(description="Nomor transaksi dari POS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Detail satu transaksi beserta itemnya.

    Transaksi milik outlet lain menghasilkan 404, bukan 403 — supaya nomor
    transaksi outlet lain tidak bisa dipetakan lewat beda status code.
    """
    outlet = resolve_outlet_scope(user, None)

    sale, items = SalesService.get_sale_detail(db=db, transaction_id=transaction_id, outlet=outlet)

    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaksi tidak ditemukan")

    detail = SaleDetail(
        **SaleResponse.model_validate(sale).model_dump(),
        items=[SaleItemResponse.model_validate(item) for item in items],
    )

    return SaleDetailResponse(data=detail)


# Group yang dikirim dengan bentuk payload lama, demi consumer yang sudah
# berjalan sebelum Fase 6. Group lain memakai bentuk generik
# {"group": ..., "product": ...}.
#
# Sengaja di kode, bukan kolom di tabel mapping: kontrak dengan consumer tidak
# boleh bisa berubah hanya karena admin mengedit sesuatu di dashboard.
LEGACY_EVENT_FIELDS = {SalesService.COLORPLATE: "platecolor"}


def build_event_data(row) -> dict:
    field = LEGACY_EVENT_FIELDS.get(row.product_group)

    if field:
        data = {field: row.product_name}
    else:
        data = {"group": row.product_group, "product": row.product_name}

    data.update(
        {
            "outlet": row.outlet_code,
            "date": row.sale_date.strftime("%Y-%m-%d"),
            "sold": int(row.sold),
        }
    )
    return data


@router.post("/publish", response_model=PublishResponse)
def publish_sales(
    request: Request,
    body: PublishSalesRequest,
    db: Session = Depends(get_db),
    rabbitmq_client: RabbitMQClient = Depends(get_rabbitmq_client),
    _api_key=Depends(require_api_key),
):
    """Dipicu mesin POS, bukan dashboard — karena itu tetap pakai API key outlet.

    Group yang dipublish dibaca dari `product_group_mappings` yang aktif.
    Gagal di tengah tetap seperti sebelumnya: 500, event yang sudah terkirim
    tidak ditarik kembali (TODO 3.4).
    """
    outlet = request.state.outlet_code

    try:
        groups = product_group_service.get_active_groups(db)

        if not groups:
            logger.warning(f"[PUBLISH] outlet={outlet} date={body.date} tidak ada product group aktif")
            return PublishResponse(
                message="No active product groups to publish",
                outlet=outlet,
                date=body.date,
                published=0,
            )

        sales = SalesService.get_sales_by_product_groups(
            db=db,
            product_groups=groups,
            outlet=outlet,
            start_date=body.date,
            end_date=body.date,
        )

        if not sales:
            return PublishResponse(
                message="No sales data to publish",
                outlet=outlet,
                date=body.date,
                published=0,
            )

        logger.info(f"[PUBLISH] outlet={outlet} date={body.date} groups={','.join(groups)} total={len(sales)}")

        total = 0
        for sale in sales:
            event = {
                "event": body.routing_key,
                "data": build_event_data(sale),
                "meta": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "sync-sales-service",
                    "version": "1.0",
                },
            }

            logger.info(f"EVENT TO PUBLISH: {json.dumps(event)}")

            rabbitmq_client.publish(
                exchange=body.exchange,
                routing_key=body.routing_key,
                payload=event,
            )
            total += 1

        return PublishResponse(
            message=f"{total} event(s) published",
            outlet=outlet,
            date=body.date,
            published=total,
        )

    except Exception as e:
        logger.error(f"[RABBITMQ][PUBLISH_ERROR] {str(e)}", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to publish sales data",
                "error": str(e),
            },
        )
