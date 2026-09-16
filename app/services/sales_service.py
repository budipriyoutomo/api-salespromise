import traceback

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services.product_group_service import normalize_product_group
from app.utils.logger import logger


class SalesService:

    @staticmethod
    def sync_sales(db: Session, outlet: str, sales_list):

        inserted_sales = 0
        inserted_items = 0

        try:
            for sale in sales_list:

                # 🔥 SALES UPSERT
                sales_stmt = insert(Sales).values(
                    TransactionID=sale.transaction_id,
                    outlet_code=outlet,
                    ShopID=sale.shop_id,
                    ReferenceNo=sale.reference_no,
                    QueueName=sale.queue_name,

                    SaleDate=sale.sale_date,
                    PaidTime=sale.paid_time,
                    CloseTime=sale.close_time,

                    TransactionStatusID=sale.transaction_status_id,
                    SaleMode=sale.sale_mode,
                    Deleted=sale.deleted,
                    NoCustomer=sale.no_customer,

                    OtherPercentDiscount=sale.other_percent_discount,
                    OtherAmountDiscount=sale.other_amount_discount,

                    ReceiptID=sale.receipt_id,
                    ReceiptMonth=sale.receipt_month,
                    ReceiptYear=sale.receipt_year,

                    ReceiptProductRetailPrice=sale.receipt_product_retail_price,
                    ReceiptSalePrice=sale.receipt_sale_price,
                    ReceiptPayPrice=sale.receipt_pay_price,
                    ReceiptDiscount=sale.receipt_discount,
                    ReceiptTotalAmount=sale.receipt_total_amount,

                    VATPercent=sale.vat_percent,
                    TransactionVAT=sale.transaction_vat,
                    TransactionExcludeVAT=sale.transaction_exclude_vat,
                    TransactionVATable=sale.transaction_vatable,

                    ServiceChargePercent=sale.service_charge_percent,
                    ServiceCharge=sale.service_charge,
                    ServiceChargeVAT=sale.service_charge_vat,

                    OtherIncome=sale.other_income,
                    OtherIncomeVAT=sale.other_income_vat,

                    VoidStaffID=sale.void_staff_id,
                    VoidReason=sale.void_reason,
                    VoidTime=sale.void_time,

                    TransactionNote=sale.transaction_note,

                    IsSplitTransaction=sale.is_split_transaction,
                    IsFromOtherTransaction=sale.is_from_other_transaction,

                    created_at=utcnow(),
                    updated_at=utcnow()
                )

                # 🔥 UPSERT FIX (multi outlet safe)
                sales_stmt = sales_stmt.on_conflict_do_update(
                    index_elements=["TransactionID", "outlet_code"],
                    set_={
                        "ShopID": sale.shop_id,
                        "SaleDate": sale.sale_date,
                        "PaidTime": sale.paid_time,
                        "CloseTime": sale.close_time,
                        "ReceiptID": sale.receipt_id,
                        "ReceiptMonth": sale.receipt_month,
                        "ReceiptYear": sale.receipt_year,
                        "ReceiptTotalAmount": sale.receipt_total_amount,
                        "ReceiptPayPrice": sale.receipt_pay_price,
                        "ReceiptDiscount": sale.receipt_discount,
                        "TransactionStatusID": sale.transaction_status_id,
                        "VoidStaffID": sale.void_staff_id,
                        "VoidReason": sale.void_reason,
                        "VoidTime": sale.void_time,
                        "updated_at": utcnow()
                    }
                )

                db.execute(sales_stmt)
                inserted_sales += 1

                # 🔥 ITEMS
                for item in sale.items:


                    item_stmt = insert(SalesItems).values(
                        OrderDetailID=item.order_detail_id,
                        TransactionID=sale.transaction_id,

                        # 🔥 NEW
                        SaleDate=item.sale_date,

                        ProductID=item.product_id,
                        Group=item.product_group,
                        Dept=item.product_dept,
                        Name=item.product_name,

                        ProductSetType=item.product_set_type,
                        OrderStatusID=item.order_status_id,
                        SaleMode=item.sale_mode,

                        Amount=item.qty,
                        Price=item.price,
                        RetailPrice=item.retail_price,
                        MinimumPrice=item.minimum_price,


                        Comment=item.comment,
                        OrderStaffID=item.order_staff_id,
                        OrderTableID=item.order_table_id,
                        VoidStaffID=item.void_staff_id
                    )

                    item_stmt = item_stmt.on_conflict_do_update(
                        index_elements=["OrderDetailID", "TransactionID","ProductID"],
                        set_={
                            "Amount": item.qty,
                            "Price": item.price,
                            "RetailPrice": item.retail_price,
                            "OrderStatusID": item.order_status_id,
                            "VoidStaffID": item.void_staff_id
                        }
                    )

                    db.execute(item_stmt)
                    inserted_items += 1

            db.commit()

            logger.info(
                f"SYNC SUCCESS outlet={outlet} "
                f"inserted_sales={inserted_sales} inserted_items={inserted_items}"
            )

            return {"sales": inserted_sales, "items": inserted_items}

        except Exception as e:

            db.rollback()


            logger.error(
                f"SYNC ERROR outlet={outlet} error={str(e)}\n{traceback.format_exc()}"
            )

            raise

    # ------------------------------------------------------------------
    # Query baca
    # ------------------------------------------------------------------

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 500

    @staticmethod
    def _normalize_paging(limit, offset):
        """Jaga limit/offset tetap masuk akal apa pun yang dikirim klien."""
        if not limit or limit < 1:
            limit = SalesService.DEFAULT_LIMIT
        limit = min(limit, SalesService.MAX_LIMIT)

        if not offset or offset < 0:
            offset = 0

        return limit, offset

    @staticmethod
    def _filter_sales(query, outlet=None, start_date=None, end_date=None):
        if outlet:
            query = query.filter(Sales.outlet_code == outlet)

        if start_date:
            query = query.filter(Sales.sale_date >= start_date)

        if end_date:
            query = query.filter(Sales.sale_date <= end_date)

        return query

    @staticmethod
    def get_sales(db, outlet=None, start_date=None, end_date=None, limit=None, offset=0):
        limit, offset = SalesService._normalize_paging(limit, offset)

        query = SalesService._filter_sales(
            db.query(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

        # urutan deterministik — tanpa ini pagination bisa melewatkan baris
        query = query.order_by(Sales.sale_date.desc(), Sales.transaction_id.desc())

        return query.limit(limit).offset(offset).all()

    @staticmethod
    def count_sales(db, outlet=None, start_date=None, end_date=None):
        query = SalesService._filter_sales(
            db.query(func.count()).select_from(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

        return query.scalar()

    # ------------------------------------------------------------------
    # Rekap per product group (Fase 6)
    # ------------------------------------------------------------------

    COLORPLATE = "COLORPLATE"

    @staticmethod
    def _normalized_product_group():
        """`UPPER(TRIM("Group"))` — pasangan SQL dari `normalize_product_group`.

        POS mengirim nama group apa adanya (`Colorplate `, ` PROMO BANDUNG`).
        Datanya tidak diubah; hanya cara membandingkannya.

        Ekspresi ini tidak bisa memakai index biasa di kolom "Group". Belum
        masalah di volume sekarang — lihat catatan performa di TODO Fase 6.
        """
        return func.upper(func.trim(SalesItems.product_group))

    @staticmethod
    def get_sales_by_product_groups(db, product_groups, outlet=None, start_date=None, end_date=None):
        """Qty terjual per group / produk / outlet / tanggal.

        `product_groups` kosong menghasilkan list kosong, BUKAN semua group —
        publish memakai fungsi ini, dan "tanpa filter" di sana berarti
        mengirim seluruh penjualan ke consumer.

        `product_group` ikut di GROUP BY supaya produk bernama sama di dua
        group tidak dijumlahkan jadi satu baris.

        Transaksi `Deleted=1` masih ikut terhitung, sama seperti rekap
        colorplate sebelum Fase 6 (TODO 4.5).
        """
        groups = sorted({normalize_product_group(g) for g in product_groups} - {""})

        if not groups:
            return []

        group_expr = SalesService._normalized_product_group()

        query = (
            db.query(
                group_expr.label("product_group"),
                SalesItems.product_name,
                Sales.outlet_code,
                Sales.sale_date,
                func.sum(SalesItems.qty).label("sold")
            )
            .join(Sales, Sales.transaction_id == SalesItems.transaction_id)
            .filter(group_expr.in_(groups))
        )

        query = SalesService._filter_sales(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

        query = query.group_by(
            group_expr,
            SalesItems.product_name,
            Sales.outlet_code,
            Sales.sale_date
        ).order_by(
            Sales.sale_date.desc(),
            group_expr,
            SalesItems.product_name
        )

        return query.all()

    @staticmethod
    def get_sales_by_product_group(db, product_group, outlet=None, start_date=None, end_date=None):
        return SalesService.get_sales_by_product_groups(
            db,
            [product_group],
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

    @staticmethod
    def get_sales_colorplate(db, outlet=None, start_date=None, end_date=None):
        """Alias `GET /api/sales/colorplate` — dipertahankan (Fase 6 A3)."""
        return SalesService.get_sales_by_product_group(
            db,
            SalesService.COLORPLATE,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )

    @staticmethod
    def list_product_groups(db, outlet=None):
        """Nama group (bentuk normal) yang pernah muncul di data penjualan.

        Untuk dropdown dashboard, dan untuk menemukan group baru dari POS yang
        belum dipetakan di `product_group_mappings`.
        """
        group_expr = SalesService._normalized_product_group()

        query = (
            db.query(group_expr.label("product_group"))
            .join(Sales, Sales.transaction_id == SalesItems.transaction_id)
            # TRIM(NULL) = NULL, dan NULL <> '' tidak bernilai benar —
            # jadi baris tanpa group ikut tersaring di sini.
            .filter(group_expr != "")
        )

        query = SalesService._filter_sales(query, outlet=outlet)

        # Diurutkan di Python: PostgreSQL rewel soal ORDER BY ekspresi pada
        # hasil GROUP BY / DISTINCT, dan daftarnya kecil.
        return sorted(row.product_group for row in query.group_by(group_expr).all())

    # ------------------------------------------------------------------
    # Query laporan (dashboard)
    # ------------------------------------------------------------------
    #
    # Berbeda dari `get_sales` / rekap per product group, semua query di bawah
    # ini MENGECUALIKAN transaksi `Deleted=1` secara default — transaksi yang
    # dibatalkan bukan pendapatan.
    #
    # Endpoint lama sengaja tidak ikut diubah supaya angka yang sudah dipublish
    # ke RabbitMQ tidak berubah diam-diam. Lihat TODO 4.5.

    TOP_PRODUCTS_DEFAULT_LIMIT = 10
    TOP_PRODUCTS_MAX_LIMIT = 100

    @staticmethod
    def _active_sales(query, include_deleted=False):
        if include_deleted:
            return query
        return query.filter(Sales.deleted == 0)

    @staticmethod
    def _report_query(query, outlet=None, start_date=None, end_date=None, include_deleted=False):
        query = SalesService._filter_sales(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )
        return SalesService._active_sales(query, include_deleted=include_deleted)

    @staticmethod
    def get_summary(db, outlet=None, start_date=None, end_date=None, include_deleted=False):
        """Angka ringkas untuk kartu di atas dashboard.

        Omzet diambil dari `ReceiptPayPrice` — jumlah yang benar-benar dibayar.

        JANGAN diganti ke `ReceiptTotalAmount` meski namanya terdengar seperti
        total rupiah: kolom itu berisi jumlah ITEM. Terbukti di database
        produksi `ReceiptTotalAmount == sum(orderdetail.Amount)` pada 14 dari
        14 baris. Memakainya membuat laporan omzet salah ribuan kali lipat
        tanpa memunculkan error sedikit pun. Dikunci oleh
        tests/unit/test_sales_service_reports.py::TestOmzetPakaiKolomUang.
        """
        query = SalesService._report_query(
            db.query(
                func.count(Sales.transaction_id).label("total_transactions"),
                func.coalesce(func.sum(Sales.receipt_pay_price), 0).label("total_amount"),
                func.coalesce(func.sum(Sales.receipt_discount), 0).label("total_discount"),
            ),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted
        )

        row = query.one()

        total_transactions = int(row.total_transactions or 0)
        total_amount = float(row.total_amount or 0)

        # Dihitung di Python, bukan AVG() SQL — supaya pembagian nol
        # menghasilkan 0.0, bukan NULL yang berubah jadi "NaN" di frontend.
        average = total_amount / total_transactions if total_transactions else 0.0

        return {
            "total_transactions": total_transactions,
            "total_amount": total_amount,
            "total_discount": float(row.total_discount or 0),
            "average_per_transaction": average,
        }

    @staticmethod
    def get_daily_sales(db, outlet=None, start_date=None, end_date=None, include_deleted=False):
        """Time series harian untuk grafik. Urutan kronologis menaik."""
        query = SalesService._report_query(
            db.query(
                Sales.sale_date.label("sale_date"),
                func.count(Sales.transaction_id).label("total_transactions"),
                func.coalesce(func.sum(Sales.receipt_pay_price), 0).label("total_amount"),
            ),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted
        )

        return query.group_by(Sales.sale_date).order_by(Sales.sale_date.asc()).all()

    @staticmethod
    def get_sales_by_outlet(db, start_date=None, end_date=None, include_deleted=False):
        """Perbandingan antar outlet, diurutkan dari omzet terbesar."""
        total_amount = func.coalesce(func.sum(Sales.receipt_pay_price), 0).label("total_amount")

        query = SalesService._report_query(
            db.query(
                Sales.outlet_code.label("outlet_code"),
                func.count(Sales.transaction_id).label("total_transactions"),
                total_amount,
            ),
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted
        )

        return query.group_by(Sales.outlet_code).order_by(total_amount.desc()).all()

    @staticmethod
    def get_top_products(
        db,
        outlet=None,
        start_date=None,
        end_date=None,
        product_group=None,
        limit=None,
        include_deleted=False
    ):
        """Ranking produk berdasarkan jumlah terjual.

        Nama group dinormalisasi sama seperti `/by-group` (Fase 6 A4): filter
        tidak peka kapitalisasi & spasi di ujung, dan varian ` Food` / `FOOD`
        untuk produk yang sama digabung jadi satu baris ber-group `FOOD`.
        Tanpa itu, nilai dari `/api/sales/product-groups` tidak cocok di sini.
        `product_group` yang kosong / spasi saja dianggap tanpa filter.
        """
        if not limit or limit < 1:
            limit = SalesService.TOP_PRODUCTS_DEFAULT_LIMIT
        limit = min(limit, SalesService.TOP_PRODUCTS_MAX_LIMIT)

        total_qty = func.coalesce(func.sum(SalesItems.qty), 0).label("total_qty")
        group_expr = SalesService._normalized_product_group()

        query = (
            db.query(
                SalesItems.product_id.label("product_id"),
                SalesItems.product_name.label("product_name"),
                group_expr.label("product_group"),
                total_qty,
                func.coalesce(func.sum(SalesItems.qty * SalesItems.price), 0).label("total_amount"),
            )
            .join(Sales, Sales.transaction_id == SalesItems.transaction_id)
        )

        product_group = normalize_product_group(product_group)
        if product_group:
            query = query.filter(group_expr == product_group)

        query = SalesService._report_query(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted
        )

        return (
            query.group_by(
                SalesItems.product_id,
                SalesItems.product_name,
                group_expr
            )
            .order_by(total_qty.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_sale_detail(db, transaction_id, outlet=None):
        """Satu transaksi beserta itemnya.

        `outlet` wajib dihormati: TransactionID unik per outlet, jadi tanpa
        filter ini user bisa membaca transaksi outlet lain hanya dengan menebak
        nomornya. `None` hanya untuk role yang memang berhak lintas outlet.
        """
        query = db.query(Sales).filter(Sales.transaction_id == transaction_id)

        if outlet:
            query = query.filter(Sales.outlet_code == outlet)

        sale = query.first()

        if not sale:
            return None, []

        items = (
            db.query(SalesItems)
            .filter(SalesItems.transaction_id == transaction_id)
            .order_by(SalesItems.order_detail_id)
            .all()
        )

        return sale, items

    @staticmethod
    def get_sync_status(db, outlet=None):
        """Kapan tiap outlet terakhir mengirim data.

        Transaksi terhapus IKUT dihitung di sini — yang diukur adalah aktivitas
        sinkronisasi, bukan pendapatan. Outlet yang berhenti mengirim data akan
        terlihat dari `last_synced_at` yang tertinggal jauh.
        """
        query = db.query(
            Sales.outlet_code.label("outlet_code"),
            func.max(Sales.sale_date).label("last_sale_date"),
            func.max(Sales.updated_at).label("last_synced_at"),
            func.count(Sales.transaction_id).label("total_transactions"),
        )

        if outlet:
            query = query.filter(Sales.outlet_code == outlet)

        return query.group_by(Sales.outlet_code).order_by(Sales.outlet_code).all()

    @staticmethod
    def get_sales_for_export(db, outlet=None, start_date=None, end_date=None, include_deleted=False):
        """Seluruh baris hasil filter, tanpa pagination — khusus export CSV.

        Sengaja terpisah dari `get_sales` supaya batas pagination di sana tidak
        perlu dilonggarkan hanya demi export.
        """
        query = SalesService._report_query(
            db.query(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted
        )

        return query.order_by(Sales.sale_date.desc(), Sales.transaction_id.desc()).all()
