import traceback
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, delete, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.core.time import hari_ini_wib, utcnow
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.models.sales_payments import SalesPayments
from app.services.brand_service import outlet_codes_subquery
from app.services.product_group_service import normalize_product_group
from app.utils.logger import logger

# Warna dibandingkan dengan aturan yang sama seperti nama group:
# "Blue " dan "BLUE" adalah warna yang sama.
color_key = normalize_product_group

# Item milik transaksi lewat (TransactionID, outlet_code). TransactionID saja
# tidak cukup: nomornya unik per outlet, bukan global (TODO 0.5).
item_join = and_(
    Sales.transaction_id == SalesItems.transaction_id,
    Sales.outlet_code == SalesItems.outlet_code,
)


# Toleransi Σ payments.amount terhadap ReceiptPayPrice, sama dengan agen POS.
TOLERANSI_PEMBAYARAN = Decimal("0.5")


def pembayaran_cocok(sale) -> bool:
    """Σ amount = receipt_pay_price (± 0,5) untuk transaksi lunas yang tidak dihapus.

    Transaksi yang dihapus atau belum punya struk (`receipt_id` 0) selalu
    dianggap cocok. Status transaksi tidak diperiksa: kode status lunas
    berbeda antar POS. Lihat docs/handoff-sync-api-payments.md bagian 3.5.
    """
    if sale.payments is None or sale.deleted or not sale.receipt_id:
        return True
    total = sum((p.amount for p in sale.payments), Decimal(0))
    return abs(total - Decimal(str(sale.receipt_pay_price))) <= TOLERANSI_PEMBAYARAN


class SalesService:

    @staticmethod
    def sync_sales(db: Session, outlet: str, sales_list):
        """Upsert satu batch dari mesin POS dalam SATU transaksi DB.

        Bulk (TODO 3.5): satu INSERT ... ON CONFLICT DO UPDATE untuk semua
        header, satu untuk semua item, lalu DELETE + INSERT massal pembayaran —
        masing-masing dipotong per `UKURAN_POTONGAN` baris. Satu baris gagal =
        seluruh batch di-rollback, sama seperti versi per baris.

        Duplikat dalam satu batch digabung lebih dulu, karena Postgres menolak
        ON CONFLICT yang menyentuh baris yang sama dua kali dalam satu
        statement. Hasil akhirnya dibuat SAMA dengan upsert per baris yang lama:
        - header/item: kolom yang di-update saat konflik dari kemunculan
          terakhir, kolom lain dari kemunculan pertama (yang dulu di-insert);
        - pembayaran: dari kemunculan terakhir yang membawa key `payments`.
        Hitungan hasil & log tetap per kiriman, termasuk duplikat.
        """
        inserted_sales = 0
        inserted_items = 0
        inserted_payments = 0
        tidak_cocok: list[int] = []

        try:
            sekarang = utcnow()
            header: dict = {}
            items: dict = {}
            bayar: dict = {}

            for sale in sales_list:
                SalesService._gabung(
                    header,
                    sale.transaction_id,
                    SalesService._baris_header(outlet, sale, sekarang),
                    SalesService.KOLOM_UPDATE_HEADER,
                )
                inserted_sales += 1

                for item in sale.items:
                    baris = SalesService._baris_item(outlet, sale, item)
                    kunci = tuple(baris[k] for k in SalesService.KOLOM_KONFLIK_ITEM)
                    SalesService._gabung(items, kunci, baris, SalesService.KOLOM_UPDATE_ITEM)
                    inserted_items += 1

                if sale.payments is not None:
                    # Cukup satu kemunculan ber-payments untuk menandai "diketahui";
                    # kemunculan sesudahnya tanpa key payments tidak menghapusnya.
                    header[sale.transaction_id]["payments_received_at"] = sekarang
                    bayar[sale.transaction_id] = sale
                    inserted_payments += len(sale.payments)
                    if not pembayaran_cocok(sale):
                        tidak_cocok.append(sale.transaction_id)

            # Urutan wajib: header dulu — FK orderdetail & orderpaydetail.
            SalesService._upsert_header(db, list(header.values()))
            SalesService._upsert_item(db, list(items.values()))
            SalesService._ganti_pembayaran(db, outlet, list(bayar.values()), sekarang)

            db.commit()

            logger.info(
                f"SYNC SUCCESS outlet={outlet} "
                f"inserted_sales={inserted_sales} inserted_items={inserted_items} "
                f"inserted_payments={inserted_payments}"
            )
            if tidak_cocok:
                # Data tetap disimpan apa adanya; rekap closing yang memblokir.
                logger.warning(
                    f"SYNC PAYMENTS MISMATCH outlet={outlet} count={len(tidak_cocok)} "
                    f"transaction_ids={tidak_cocok[:20]}"
                )

            return {"sales": inserted_sales, "items": inserted_items}

        except Exception as e:

            db.rollback()

            logger.error(
                f"SYNC ERROR outlet={outlet} error={str(e)}\n{traceback.format_exc()}"
            )

            raise

    # Baris per INSERT/DELETE massal. Batas bind parameter Postgres 65.535;
    # header ±40 kolom × 500 = ±20 rb — jauh di bawahnya.
    UKURAN_POTONGAN = 500

    # Kolom yang ditimpa saat (TransactionID, outlet_code) sudah ada. Kolom lain
    # (ReferenceNo, Deleted, VAT, ...) hanya diisi saat insert pertama.
    KOLOM_UPDATE_HEADER = (
        "ShopID",
        "SaleDate",
        "PaidTime",
        "CloseTime",
        "ReceiptID",
        "ReceiptMonth",
        "ReceiptYear",
        "ReceiptTotalAmount",
        "ReceiptPayPrice",
        "ReceiptDiscount",
        "TransactionStatusID",
        "VoidStaffID",
        "VoidReason",
        "VoidTime",
        "updated_at",
    )
    KOLOM_KONFLIK_HEADER = ("TransactionID", "outlet_code")

    KOLOM_UPDATE_ITEM = ("Amount", "Price", "RetailPrice", "OrderStatusID", "VoidStaffID")
    KOLOM_KONFLIK_ITEM = ("OrderDetailID", "TransactionID", "ProductID", "outlet_code")

    @staticmethod
    def _gabung(tujuan: dict, kunci, baris: dict, kolom_update):
        """Kemunculan pertama disimpan utuh; berikutnya hanya menimpa kolom update."""
        ada = tujuan.get(kunci)
        if ada is None:
            tujuan[kunci] = baris
        else:
            ada.update({k: baris[k] for k in kolom_update})

    @staticmethod
    def _potong(baris: list):
        n = SalesService.UKURAN_POTONGAN
        for i in range(0, len(baris), n):
            yield baris[i:i + n]

    @staticmethod
    def _baris_header(outlet: str, sale, sekarang) -> dict:
        return dict(
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

            created_at=sekarang,
            updated_at=sekarang,
            # Diisi di sync_sales kalau ada kemunculan yang membawa key payments.
            payments_received_at=None,
        )

    @staticmethod
    def _baris_item(outlet: str, sale, item) -> dict:
        return dict(
            OrderDetailID=item.order_detail_id,
            # Dari sale induk, bukan item.transaction_id — item tidak bisa nyasar.
            TransactionID=sale.transaction_id,
            outlet_code=outlet,

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
            VoidStaffID=item.void_staff_id,
        )

    @staticmethod
    def _upsert_header(db: Session, rows: list):
        for potongan in SalesService._potong(rows):
            stmt = insert(Sales).values(potongan)
            stmt = stmt.on_conflict_do_update(
                index_elements=list(SalesService.KOLOM_KONFLIK_HEADER),
                set_={
                    # Satu SET untuk semua baris → nilai dari baris itu sendiri.
                    **{k: stmt.excluded[k] for k in SalesService.KOLOM_UPDATE_HEADER},
                    # NULL = kiriman tanpa key payments → tanda lama dipertahankan.
                    "payments_received_at": func.coalesce(
                        stmt.excluded.payments_received_at, Sales.__table__.c.payments_received_at
                    ),
                },
            )
            db.execute(stmt)

    @staticmethod
    def _upsert_item(db: Session, rows: list):
        for potongan in SalesService._potong(rows):
            stmt = insert(SalesItems).values(potongan)
            stmt = stmt.on_conflict_do_update(
                index_elements=list(SalesService.KOLOM_KONFLIK_ITEM),
                set_={k: stmt.excluded[k] for k in SalesService.KOLOM_UPDATE_ITEM},
            )
            db.execute(stmt)

    @staticmethod
    def _ganti_pembayaran(db: Session, outlet: str, sales: list, sekarang) -> None:
        """Ganti seluruh baris pembayaran transaksi-transaksi ini dengan isi `payments`-nya.

        Upsert per baris tidak cukup: baris yang sudah hilang di POS (metode
        bayar diganti, jumlah baris berkurang) akan tertinggal. Jadi baris lama
        dihapus dulu, di dalam transaksi DB yang sama dengan upsert header.
        Hanya transaksi yang membawa key `payments` (termasuk `[]`) yang
        disentuh. Dikunci (outlet, TransactionID) seperti header.
        """
        if not sales:
            return

        for potongan in SalesService._potong([s.transaction_id for s in sales]):
            db.execute(
                delete(SalesPayments).where(
                    SalesPayments.outlet_code == outlet,
                    SalesPayments.transaction_id.in_(potongan),
                )
            )

        rows = [
            dict(
                outlet_code=outlet,
                TransactionID=sale.transaction_id,
                ComputerID=p.computer_id,
                PayDetailID=p.pay_detail_id,
                SaleDate=sale.sale_date,
                PayTypeID=p.pay_type_id,
                PayTypeCode=p.pay_type_code,
                PayTypeName=p.pay_type_name,
                PayTypeDisplayName=p.pay_type_display_name,
                Amount=p.amount,
                CashChange=p.cash_change,
                IsFromEDC=p.is_from_edc,
                IsSale=p.is_sale,
                IsOtherReceipt=p.is_other_receipt,
                received_at=sekarang,
            )
            for sale in sales
            for p in sale.payments
        ]
        for potongan in SalesService._potong(rows):
            db.execute(insert(SalesPayments).values(potongan))

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
    def _filter_sales(query, outlet=None, start_date=None, end_date=None, brand=None):
        if outlet:
            query = query.filter(Sales.outlet_code == outlet)

        # Digabung AND dengan `outlet`: user role outlet yang memfilter brand
        # lain mendapat hasil kosong, bukan data outlet lain.
        if brand:
            query = query.filter(Sales.outlet_code.in_(outlet_codes_subquery(brand)))

        if start_date:
            query = query.filter(Sales.sale_date >= start_date)

        if end_date:
            query = query.filter(Sales.sale_date <= end_date)

        return query

    @staticmethod
    def _filter_tanggal_item(query, start_date=None, end_date=None):
        """Rentang yang sama di `orderdetail."SaleDate"` — redundan, untuk planner.

        Query yang join item → transaksi memfilter tanggal di `ordertransaction`.
        Tanpa kondisi di sisi `orderdetail`, Postgres tidak bisa memakai
        `ix_orderdetail_saledate_outlet` (migrasi 017) dan membaca item jauh di
        luar rentang — di salinan produksi 883 ribu baris, `top_products` 30
        hari memindai seluruh tabel (TODO 9.13).

        Hanya benar selama tanggal item = tanggal transaksinya: 0 selisih di
        salinan produksi 2026-11-20 (`migrations/checks/saledate_konsisten.sql`).
        Item yang tanggalnya berbeda dari transaksinya TIDAK ikut terhitung.
        """
        if start_date:
            query = query.filter(SalesItems.sale_date >= start_date)

        if end_date:
            query = query.filter(SalesItems.sale_date <= end_date)

        return query

    @staticmethod
    def get_sales(db, outlet=None, start_date=None, end_date=None, limit=None, offset=0, brand=None):
        limit, offset = SalesService._normalize_paging(limit, offset)

        query = SalesService._filter_sales(
            db.query(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand
        )

        # urutan deterministik — tanpa ini pagination bisa melewatkan baris
        query = query.order_by(Sales.sale_date.desc(), Sales.transaction_id.desc())

        return query.limit(limit).offset(offset).all()

    @staticmethod
    def count_sales(db, outlet=None, start_date=None, end_date=None, brand=None):
        query = SalesService._filter_sales(
            db.query(func.count()).select_from(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand
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
    def get_sales_by_product_groups(
        db, product_groups, outlet=None, start_date=None, end_date=None, product_ids=None, brand=None
    ):
        """Qty terjual per group / produk / outlet / tanggal.

        `product_ids` menambah menu satu per satu di luar `product_groups`
        (mapping per menu). Filternya OR per baris orderdetail, jadi menu yang
        cocok lewat group dan lewat ProductID sekaligus tetap terhitung sekali.

        `product_groups` dan `product_ids` sama-sama kosong menghasilkan list
        kosong, BUKAN semua penjualan — publish memakai fungsi ini, dan "tanpa
        filter" di sana berarti mengirim seluruh penjualan ke consumer.

        `product_group` ikut di GROUP BY supaya produk bernama sama di dua
        group tidak dijumlahkan jadi satu baris.

        Transaksi `Deleted=1` (void) tidak dihitung — sama dengan laporan
        dashboard (diputuskan 2026-10-05, TODO 4.5 / A5). Fungsi ini juga
        sumber angka publish colorplate.
        """
        groups = sorted({normalize_product_group(g) for g in product_groups} - {""})
        ids = sorted({int(i) for i in (product_ids or []) if i is not None and int(i) > 0})

        if not groups and not ids:
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
            .join(Sales, item_join)
        )

        syarat = []
        if groups:
            syarat.append(group_expr.in_(groups))
        if ids:
            syarat.append(SalesItems.product_id.in_(ids))
        query = query.filter(or_(*syarat))

        query = SalesService._filter_sales(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand
        )
        query = SalesService._filter_tanggal_item(query, start_date=start_date, end_date=end_date)
        query = SalesService._active_sales(query)

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
    def get_sales_by_product_ids(db, product_ids, outlet=None, start_date=None, end_date=None, exclude_groups=None):
        """Qty terjual per ProductID / outlet / tanggal — bahan konversi menu ke warna.

        Dikelompokkan per ProductID, bukan nama: konversi warna menempel di
        ProductID, dan nama menu bisa berubah di POS.

        `exclude_groups` membuang baris dari group yang sudah dihitung langsung
        (COLORPLATE), supaya satu baris orderdetail tidak terhitung dua kali.

        Transaksi `Deleted=1` (void) tidak dihitung, sama dengan
        `get_sales_by_product_groups`.
        """
        ids = sorted({int(i) for i in (product_ids or []) if i is not None and int(i) > 0})
        if not ids:
            return []

        group_expr = SalesService._normalized_product_group()

        query = (
            db.query(
                SalesItems.product_id,
                Sales.outlet_code,
                Sales.sale_date,
                func.sum(SalesItems.qty).label("sold")
            )
            .join(Sales, item_join)
            .filter(SalesItems.product_id.in_(ids))
        )

        excluded = sorted({normalize_product_group(g) for g in (exclude_groups or [])} - {""})
        if excluded:
            # NULL group tetap ikut — `NOT IN` saja akan membuangnya.
            query = query.filter(or_(SalesItems.product_group.is_(None), group_expr.notin_(excluded)))

        query = SalesService._filter_sales(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date
        )
        query = SalesService._filter_tanggal_item(query, start_date=start_date, end_date=end_date)
        query = SalesService._active_sales(query)

        return query.group_by(
            SalesItems.product_id,
            Sales.outlet_code,
            Sales.sale_date
        ).all()

    @staticmethod
    def list_colorplate_colors(db):
        """Nama menu COLORPLATE yang pernah terjual — pilihan warna untuk konversi menu."""
        name_expr = func.trim(SalesItems.product_name)

        rows = (
            db.query(name_expr.label("platecolor"))
            .filter(SalesService._normalized_product_group() == SalesService.COLORPLATE)
            .filter(name_expr != "")
            .distinct()
            .all()
        )

        # Nama yang sama dengan kapitalisasi berbeda ("Blue" / "BLUE") dianggap
        # satu warna; yang pertama ditemukan dipakai.
        warna: dict = {}
        for row in rows:
            warna.setdefault(color_key(row.platecolor), row.platecolor)

        return sorted(warna.values(), key=color_key)

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
    def list_product_groups(db, outlet=None, start_date=None, end_date=None):
        """Nama group (bentuk normal) yang pernah muncul di data penjualan.

        Untuk dropdown dashboard, dan untuk menemukan group baru dari POS yang
        belum dipetakan di `product_group_mappings`.

        Dibaca dari `orderdetail` saja — tabel itu punya `outlet_code` dan
        `SaleDate` sendiri, jadi join ke `ordertransaction` tidak perlu.
        Dashboard mengirim rentang filternya; tanpa rentang (halaman admin)
        seluruh tabel dipindai.
        """
        group_expr = SalesService._normalized_product_group()

        # TRIM(NULL) = NULL, dan NULL <> '' tidak bernilai benar —
        # jadi baris tanpa group ikut tersaring di sini.
        query = db.query(group_expr.label("product_group")).filter(group_expr != "")

        if outlet:
            query = query.filter(SalesItems.outlet_code == outlet)
        if start_date:
            query = query.filter(SalesItems.sale_date >= start_date)
        if end_date:
            query = query.filter(SalesItems.sale_date <= end_date)

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

    # Jendela jumlah transaksi di status sync (hari ini WIB + 29 hari sebelumnya).
    SYNC_STATUS_HARI = 30

    @staticmethod
    def _active_sales(query, include_deleted=False):
        if include_deleted:
            return query
        return query.filter(Sales.deleted == 0)

    @staticmethod
    def _report_query(query, outlet=None, start_date=None, end_date=None, include_deleted=False, brand=None):
        query = SalesService._filter_sales(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand
        )
        return SalesService._active_sales(query, include_deleted=include_deleted)

    @staticmethod
    def get_summary(db, outlet=None, start_date=None, end_date=None, include_deleted=False, brand=None):
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
            include_deleted=include_deleted,
            brand=brand
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
    def get_daily_sales(db, outlet=None, start_date=None, end_date=None, include_deleted=False, brand=None):
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
            include_deleted=include_deleted,
            brand=brand
        )

        return query.group_by(Sales.sale_date).order_by(Sales.sale_date.asc()).all()

    @staticmethod
    def get_sales_by_outlet(db, start_date=None, end_date=None, include_deleted=False, brand=None):
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
            include_deleted=include_deleted,
            brand=brand
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
        include_deleted=False,
        brand=None
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
            .join(Sales, item_join)
        )

        product_group = normalize_product_group(product_group)
        if product_group:
            query = query.filter(group_expr == product_group)

        query = SalesService._report_query(
            query,
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted,
            brand=brand
        )
        query = SalesService._filter_tanggal_item(query, start_date=start_date, end_date=end_date)

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

        # Outlet diambil dari transaksi yang ketemu, bukan dari parameter:
        # tanpa filter outlet, item outlet lain dengan nomor sama ikut terbawa.
        items = (
            db.query(SalesItems)
            .filter(SalesItems.transaction_id == transaction_id)
            .filter(SalesItems.outlet_code == sale.outlet_code)
            .order_by(SalesItems.order_detail_id)
            .all()
        )

        return sale, items

    @staticmethod
    def get_sale_payments(db, sale):
        """Baris pembayaran satu transaksi, atau `None` bila belum diketahui.

        `None` (bukan `[]`) saat `payments_received_at` kosong: agen lama atau
        view pembayaran belum dipasang di outlet. `[]` berarti POS memang
        melaporkan transaksi ini tanpa pembayaran. Frontend membedakan keduanya.
        """
        if sale.payments_received_at is None:
            return None

        return (
            db.query(SalesPayments)
            .filter(SalesPayments.transaction_id == sale.transaction_id)
            .filter(SalesPayments.outlet_code == sale.outlet_code)
            .order_by(SalesPayments.computer_id, SalesPayments.pay_detail_id)
            .all()
        )

    @staticmethod
    def get_payment_summary(db, outlet=None, start_date=None, end_date=None, brand=None):
        """Total pembayaran per outlet + jenis bayar, untuk rentang tanggal.

        Jenis bayar dikelompokkan per (outlet_code, PayTypeID): ID dan nama
        jenis bayar milik POS masing-masing outlet, jadi tidak digabung antar
        outlet berdasarkan nama. Transaksi terhapus tidak dihitung.

        `transactions_without_payments` = transaksi aktif yang pembayarannya
        belum diketahui (`payments_received_at` NULL), supaya total di sini
        tidak dikira lengkap padahal sebagian outlet belum mengirim.
        """
        nama = func.max(
            func.coalesce(
                SalesPayments.pay_type_display_name,
                SalesPayments.pay_type_name,
                SalesPayments.pay_type_code,
            )
        ).label("pay_type_name")
        total_amount = func.coalesce(func.sum(SalesPayments.amount), 0).label("total_amount")

        query = SalesService._report_query(
            db.query(
                Sales.outlet_code.label("outlet_code"),
                SalesPayments.pay_type_id.label("pay_type_id"),
                nama,
                func.count(func.distinct(Sales.transaction_id)).label("total_transactions"),
                total_amount,
            ).join(
                SalesPayments,
                and_(
                    SalesPayments.transaction_id == Sales.transaction_id,
                    SalesPayments.outlet_code == Sales.outlet_code,
                ),
            ),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand,
        )
        rows = (
            query.group_by(Sales.outlet_code, SalesPayments.pay_type_id)
            .order_by(Sales.outlet_code, total_amount.desc())
            .all()
        )

        tanpa = SalesService._report_query(
            db.query(func.count(Sales.transaction_id)).filter(Sales.payments_received_at.is_(None)),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            brand=brand,
        ).scalar()

        data = [
            {
                "outlet_code": r.outlet_code,
                "pay_type_id": int(r.pay_type_id),
                "pay_type_name": r.pay_type_name,
                "total_transactions": int(r.total_transactions or 0),
                "total_amount": float(r.total_amount or 0),
            }
            for r in rows
        ]
        return {
            "rows": data,
            "total_amount": sum(r["total_amount"] for r in data),
            "transactions_without_payments": int(tanpa or 0),
        }

    @staticmethod
    def get_sync_status(db, outlet=None, hari_ini=None):
        """Kapan tiap outlet terakhir mengirim data.

        Transaksi terhapus IKUT dihitung di sini — yang diukur adalah aktivitas
        sinkronisasi, bukan pendapatan. Outlet yang berhenti mengirim data akan
        terlihat dari `last_synced_at` yang tertinggal jauh, dan tetap muncul
        dengan `transactions_last_30_days` = 0.

        Jumlah transaksi hanya `SYNC_STATUS_HARI` terakhir (hari ini WIB dan 29
        hari sebelumnya), bukan sepanjang masa — COUNT seluruh tabel makin berat
        seiring data bertambah (TODO 9.14).

        Bentuk query sengaja bukan GROUP BY: Postgres tidak bisa melompat per
        outlet di index untuk GROUP BY + MAX, jadi seluruh tabel dipindai.
        Sebagai gantinya daftar outlet diambil dengan recursive CTE (satu lookup
        index per outlet), lalu tiap angka dicari lewat subquery per outlet yang
        memakai `idx_ordertransaction_outlet_saledate` (002) dan
        `ix_ordertransaction_outlet_updated` (022). Biayanya mengikuti jumlah
        outlet dan transaksi 30 hari, bukan ukuran tabel.
        """
        awal = (hari_ini or hari_ini_wib()) - timedelta(days=SalesService.SYNC_STATUS_HARI - 1)

        if outlet:
            # Hanya outlet yang punya transaksi — outlet tanpa data tidak ada barisnya.
            outlets = (
                select(literal(outlet).label("kode"))
                .where(select(Sales.transaction_id).where(Sales.outlet_code == outlet).exists())
                .cte("outlets")
            )
        else:
            # "Loose index scan": outlet berikutnya = MIN(outlet_code) > outlet sebelumnya.
            berikut = aliased(Sales)
            outlets = select(func.min(Sales.outlet_code).label("kode")).cte("outlets", recursive=True)
            outlets = outlets.union_all(
                select(
                    select(func.min(berikut.outlet_code))
                    .where(berikut.outlet_code > outlets.c.kode)
                    .scalar_subquery()
                ).where(outlets.c.kode.isnot(None))
            )

        def per_outlet(kolom, *syarat):
            return select(kolom).where(Sales.outlet_code == outlets.c.kode, *syarat).scalar_subquery()

        query = (
            select(
                outlets.c.kode.label("outlet_code"),
                per_outlet(func.max(Sales.sale_date)).label("last_sale_date"),
                per_outlet(func.max(Sales.updated_at)).label("last_synced_at"),
                per_outlet(func.count(), Sales.sale_date >= awal).label("transactions_last_30_days"),
            )
            .where(outlets.c.kode.isnot(None))
            .order_by(outlets.c.kode)
        )

        return db.execute(query).all()

    @staticmethod
    def get_sales_for_export(
        db, outlet=None, start_date=None, end_date=None, include_deleted=False, brand=None, kolom=None
    ):
        """Seluruh baris hasil filter, tanpa pagination — khusus export CSV.

        Sengaja terpisah dari `get_sales` supaya batas pagination di sana tidak
        perlu dilonggarkan hanya demi export.

        `kolom` (atribut `Sales`) membatasi kolom yang diambil — export hanya
        butuh beberapa kolom, dan objek ORM penuh untuk ratusan ribu baris
        memakan memori dan waktu. Tanpa `kolom`, objek `Sales` dikembalikan.
        """
        query = SalesService._report_query(
            db.query(*kolom) if kolom else db.query(Sales),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            include_deleted=include_deleted,
            brand=brand
        )

        return query.order_by(Sales.sale_date.desc(), Sales.transaction_id.desc()).all()
