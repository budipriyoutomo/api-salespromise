"""Test SalesService.sync_sales.

`sync_sales` memakai `on_conflict_do_update` (dialek PostgreSQL), jadi tidak
bisa dijalankan di SQLite. Pendekatan di sini: session di-mock, lalu statement
yang dikirim ke `db.execute()` diperiksa — di-compile ke dialek PostgreSQL untuk
membaca nilai bind dan klausa ON CONFLICT-nya.

Jalur eksekusi sungguhan diuji di tests/integration/test_sync_postgres.py.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from freezegun import freeze_time
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

from app.schemas.sales_schema import SalesItemSchema, SalesSchema
from app.services.sales_service import SalesService


class RecordingSession:
    """Session palsu yang merekam statement, commit, dan rollback."""

    def __init__(self, fail_on_execute_call=None):
        self.statements = []
        self.committed = 0
        self.rolled_back = 0
        self._fail_on = fail_on_execute_call

    def execute(self, statement):
        self.statements.append(statement)
        if self._fail_on is not None and len(self.statements) == self._fail_on:
            raise RuntimeError("kegagalan database simulasi")
        return None

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def compiled(statement):
    return statement.compile(dialect=pg_dialect())


def params_of(statement):
    return compiled(statement).params


def sql_of(statement):
    return str(compiled(statement))


KOLOM_UPDATE_SALES = {
    "ShopID", "SaleDate", "PaidTime", "CloseTime", "ReceiptID", "ReceiptMonth", "ReceiptYear",
    "ReceiptTotalAmount", "ReceiptPayPrice", "ReceiptDiscount", "TransactionStatusID",
    "VoidStaffID", "VoidReason", "VoidTime", "updated_at",
}
KOLOM_UPDATE_ITEM = {"Amount", "Price", "RetailPrice", "OrderStatusID", "VoidStaffID"}


def kolom_set(statement):
    """Nama kolom yang di-assign di `DO UPDATE SET ...`."""
    import re

    bagian = do_update(statement).split("SET", 1)[1]
    return set(re.findall(r'(?:^|, )\s*"?(\w+)"? = ', bagian))


def baris(statement, i=0):
    """Nilai kolom baris ke-`i` dari INSERT multi-VALUES (bind `<kolom>_m<i>`)."""
    akhiran = f"_m{i}"
    return {k[: -len(akhiran)]: v for k, v in params_of(statement).items() if k.endswith(akhiran)}


def jumlah_baris(statement):
    """Jumlah baris VALUES dalam satu INSERT."""
    return len({k.rsplit("_m", 1)[1] for k in params_of(statement) if "_m" in k and k.rsplit("_m", 1)[1].isdigit()})


def do_update(statement):
    sql = sql_of(statement)
    return sql[sql.find("DO UPDATE"):]


def statements_for(session, table_name):
    return [s for s in session.statements if s.table.name == table_name]


def build_sale(transaction_id=10001, items=None, **overrides):
    payload = dict(
        transaction_id=transaction_id,
        shop_id=1,
        sale_date=date(2026, 1, 15),
        paid_time=datetime(2026, 1, 15, 10, 30),
        receipt_total_amount=150000.0,
        receipt_pay_price=150000.0,
        vat_percent=11.0,
        transaction_vat=14850.0,
        items=items or [],
    )
    payload.update(overrides)
    return SalesSchema(**payload)


def build_item(order_detail_id=1, transaction_id=10001, **overrides):
    payload = dict(
        order_detail_id=order_detail_id,
        transaction_id=transaction_id,
        sale_date=date(2026, 1, 15),
        product_id=101,
        product_group="COLORPLATE",
        product_name="RED",
        qty=2.0,
        price=75000.0,
        retail_price=75000.0,
    )
    payload.update(overrides)
    return SalesItemSchema(**payload)


class TestHitunganHasil:

    def test_satu_sale_satu_item(self):
        db = RecordingSession()

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])

        assert result == {"sales": 1, "items": 1}

    def test_sale_tanpa_item(self):
        db = RecordingSession()

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert result == {"sales": 1, "items": 0}
        assert statements_for(db, "orderdetail") == []

    def test_sale_dengan_banyak_item(self):
        db = RecordingSession()
        items = [build_item(order_detail_id=i) for i in range(1, 6)]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=items)])

        assert result == {"sales": 1, "items": 5}
        # Bulk (TODO 3.5): satu INSERT untuk semua item, bukan satu per item.
        (stmt,) = statements_for(db, "orderdetail")
        assert jumlah_baris(stmt) == 5

    def test_banyak_sale_dengan_jumlah_item_berbeda(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, items=[build_item(transaction_id=1)]),
            build_sale(transaction_id=2, items=[]),
            build_sale(transaction_id=3, items=[build_item(order_detail_id=i, transaction_id=3) for i in (1, 2, 3)]),
        ]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert result == {"sales": 3, "items": 4}
        (header,) = statements_for(db, "ordertransaction")
        (items,) = statements_for(db, "orderdetail")
        assert (jumlah_baris(header), jumlah_baris(items)) == (3, 4)

    def test_list_kosong_tidak_menyentuh_database(self):
        db = RecordingSession()

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[])

        assert result == {"sales": 0, "items": 0}
        assert db.statements == []
        assert db.committed == 1  # tetap commit (transaksi kosong)


class TestPemetaanKolomSales:

    def test_outlet_code_diambil_dari_parameter_bukan_body(self):
        """Kontrak keamanan: outlet berasal dari API key, tidak bisa dipalsukan lewat payload."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_009", sales_list=[build_sale()])

        assert baris(db.statements[0])["outlet_code"] == "OUTLET_009"

    def test_kolom_utama_terpetakan(self):
        db = RecordingSession()
        sale = build_sale(
            transaction_id=777,
            shop_id=3,
            reference_no="REF-1",
            queue_name="A1",
            receipt_id=55,
            receipt_month=1,
            receipt_year=2026,
            transaction_status_id=2,
            no_customer=4,
        )

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        p = baris(db.statements[0])

        assert p["TransactionID"] == 777
        assert p["ShopID"] == 3
        assert p["ReferenceNo"] == "REF-1"
        assert p["QueueName"] == "A1"
        assert p["ReceiptID"] == 55
        assert p["ReceiptMonth"] == 1
        assert p["ReceiptYear"] == 2026
        assert p["TransactionStatusID"] == 2
        assert p["NoCustomer"] == 4
        assert p["SaleDate"] == date(2026, 1, 15)
        assert p["PaidTime"] == datetime(2026, 1, 15, 10, 30)

    def test_kolom_uang_dan_pajak_terpetakan(self):
        db = RecordingSession()
        sale = build_sale(
            receipt_product_retail_price=200000.0,
            receipt_sale_price=180000.0,
            receipt_pay_price=150000.0,
            receipt_discount=30000.0,
            receipt_total_amount=150000.0,
            vat_percent=11.0,
            transaction_vat=14850.0,
            transaction_exclude_vat=135150.0,
            transaction_vatable=135150.0,
            service_charge_percent=5.0,
            service_charge=7500.0,
            service_charge_vat=825.0,
            other_income=1000.0,
            other_income_vat=110.0,
        )

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        p = baris(db.statements[0])

        assert p["ReceiptProductRetailPrice"] == 200000.0
        assert p["ReceiptSalePrice"] == 180000.0
        assert p["ReceiptPayPrice"] == 150000.0
        assert p["ReceiptDiscount"] == 30000.0
        assert p["ReceiptTotalAmount"] == 150000.0
        assert p["VATPercent"] == 11.0
        assert p["TransactionVAT"] == 14850.0
        assert p["TransactionExcludeVAT"] == 135150.0
        assert p["TransactionVATable"] == 135150.0
        assert p["ServiceChargePercent"] == 5.0
        assert p["ServiceCharge"] == 7500.0
        assert p["ServiceChargeVAT"] == 825.0
        assert p["OtherIncome"] == 1000.0
        assert p["OtherIncomeVAT"] == 110.0

    def test_kolom_void_terpetakan(self):
        db = RecordingSession()
        sale = build_sale(
            void_staff_id=9,
            void_reason="salah input",
            void_time=datetime(2026, 1, 15, 11, 0),
        )

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        p = baris(db.statements[0])

        assert p["VoidStaffID"] == 9
        assert p["VoidReason"] == "salah input"
        assert p["VoidTime"] == datetime(2026, 1, 15, 11, 0)

    def test_presisi_desimal_tidak_hilang(self):
        """Kolom DB NUMERIC(18,4) — nilai desimal harus lolos utuh."""
        db = RecordingSession()
        sale = build_sale(receipt_total_amount=150000.1234, transaction_vat=14850.5678)

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        p = baris(db.statements[0])

        assert p["ReceiptTotalAmount"] == 150000.1234
        assert p["TransactionVAT"] == 14850.5678

    @freeze_time("2026-03-01 08:00:00")
    def test_created_at_dan_updated_at_diisi_saat_insert(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])
        p = baris(db.statements[0])

        assert p["created_at"] == datetime(2026, 3, 1, 8, 0)
        assert p["updated_at"] == datetime(2026, 3, 1, 8, 0)


class TestKlausaUpsertSales:
    """Konflik ditangani berdasarkan (TransactionID, outlet_code).

    Artinya TransactionID yang sama dari outlet berbeda adalah dua baris berbeda.
    Bentuk index ini sudah dipakai di produksi — jangan diubah tanpa migrasi.
    """

    def test_memakai_on_conflict_do_update(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert "ON CONFLICT" in sql_of(db.statements[0])
        assert "DO UPDATE" in sql_of(db.statements[0])

    def test_konflik_berdasarkan_transaction_id_dan_outlet_code(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert 'ON CONFLICT ("TransactionID", outlet_code)' in sql_of(db.statements[0])

    def test_transaction_id_sama_dari_dua_outlet_dikirim_terpisah(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=500)])
        SalesService.sync_sales(db=db, outlet="OUTLET_002", sales_list=[build_sale(transaction_id=500)])

        outlets = [baris(s)["outlet_code"] for s in statements_for(db, "ordertransaction")]
        assert outlets == ["OUTLET_001", "OUTLET_002"]

    def test_kolom_yang_di_update_saat_konflik(self):
        """Daftar ini menentukan data mana yang boleh berubah saat outlet kirim ulang."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])
        sql = sql_of(db.statements[0])
        do_update = sql[sql.find("DO UPDATE"):]

        for column in [
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
        ]:
            # kolom lowercase tidak di-quote oleh SQLAlchemy, kolom CamelCase di-quote
            assert f'"{column}" =' in do_update or f"{column} =" in do_update, (
                f"{column} hilang dari klausa DO UPDATE"
            )

    def test_daftar_kolom_update_persis_sama_dan_diambil_dari_excluded(self):
        """Bulk (TODO 3.5): satu SET untuk semua baris, jadi nilainya harus
        `excluded.<kolom>` — nilai baris itu sendiri — bukan literal satu sale.
        Daftarnya tidak boleh bertambah diam-diam (mis. Deleted, ReferenceNo)."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert kolom_set(db.statements[0]) == KOLOM_UPDATE_SALES | {"payments_received_at"}
        for kolom in KOLOM_UPDATE_SALES:
            q = kolom if kolom.islower() else f'"{kolom}"'
            assert f"{q} = excluded.{q}" in do_update(db.statements[0])

    def test_outlet_code_tidak_ikut_di_update_saat_konflik(self):
        """outlet_code bagian dari kunci konflik — tidak boleh ditimpa."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])
        sql = sql_of(db.statements[0])
        do_update = sql[sql.find("DO UPDATE"):]

        assert "outlet_code =" not in do_update

    def test_created_at_tidak_ditimpa_saat_konflik(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])
        sql = sql_of(db.statements[0])
        do_update = sql[sql.find("DO UPDATE"):]

        assert "created_at" not in do_update

    def test_kirim_ulang_payload_sama_menghasilkan_statement_identik(self):
        """Idempotensi di level statement: dua kali kirim → SQL sama persis."""
        db = RecordingSession()
        sale = build_sale(items=[build_item()])

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])

        first, second = statements_for(db, "ordertransaction")
        assert sql_of(first) == sql_of(second)


class TestPemetaanKolomItem:

    def test_kolom_item_terpetakan(self):
        db = RecordingSession()
        item = build_item(
            order_detail_id=42,
            product_id=202,
            product_group="COLORPLATE",
            product_dept="PLATE",
            product_name="BLUE",
            product_set_type=1,
            order_status_id=3,
            sale_mode=2,
            qty=2.5,
            price=75000.0,
            retail_price=80000.0,
            minimum_price=70000.0,
            comment="tanpa es",
            order_staff_id=7,
            order_table_id=12,
            void_staff_id=0,
        )

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[item])])
        p = baris(statements_for(db, "orderdetail")[0])

        assert p["OrderDetailID"] == 42
        assert p["ProductID"] == 202
        assert p["Group"] == "COLORPLATE"
        assert p["Dept"] == "PLATE"
        assert p["Name"] == "BLUE"
        assert p["ProductSetType"] == 1
        assert p["OrderStatusID"] == 3
        assert p["SaleMode"] == 2
        assert p["Amount"] == 2.5
        assert p["Price"] == 75000.0
        assert p["RetailPrice"] == 80000.0
        assert p["MinimumPrice"] == 70000.0
        assert p["Comment"] == "tanpa es"
        assert p["OrderStaffID"] == 7
        assert p["OrderTableID"] == 12

    def test_transaction_id_item_diambil_dari_sale_induk(self):
        """Bukan dari `item.transaction_id` — mencegah item nyasar ke transaksi lain."""
        db = RecordingSession()
        item = build_item(transaction_id=99999)  # sengaja beda dari induknya

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=10001, items=[item])])
        p = baris(statements_for(db, "orderdetail")[0])

        assert p["TransactionID"] == 10001

    def test_sale_date_item_dipakai_apa_adanya(self):
        db = RecordingSession()
        item = build_item(sale_date=date(2026, 2, 1))

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[item])])

        assert baris(statements_for(db, "orderdetail")[0])["SaleDate"] == date(2026, 2, 1)

    def test_konflik_item_berdasarkan_order_detail_transaction_product_outlet(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])
        sql = sql_of(statements_for(db, "orderdetail")[0])

        assert 'ON CONFLICT ("OrderDetailID", "TransactionID", "ProductID", outlet_code)' in sql

    def test_kolom_item_yang_di_update_saat_konflik(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])
        sql = sql_of(statements_for(db, "orderdetail")[0])
        do_update = sql[sql.find("DO UPDATE"):]

        for column in ["Amount", "Price", "RetailPrice", "OrderStatusID", "VoidStaffID"]:
            # kolom lowercase tidak di-quote oleh SQLAlchemy, kolom CamelCase di-quote
            assert f'"{column}" =' in do_update or f"{column} =" in do_update, (
                f"{column} hilang dari klausa DO UPDATE"
            )

    def test_daftar_kolom_update_item_persis_sama_dan_diambil_dari_excluded(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])
        (stmt,) = statements_for(db, "orderdetail")

        assert kolom_set(stmt) == KOLOM_UPDATE_ITEM
        for kolom in KOLOM_UPDATE_ITEM:
            assert f'"{kolom}" = excluded."{kolom}"' in do_update(stmt)

    def test_outlet_code_item_diambil_dari_parameter_bukan_body(self):
        """TODO 0.5: item ikut membawa outlet_code dari API key, sama seperti induknya."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_009", sales_list=[build_sale(items=[build_item()])])

        assert baris(statements_for(db, "orderdetail")[0])["outlet_code"] == "OUTLET_009"

    def test_outlet_code_item_tidak_ikut_di_update_saat_konflik(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])
        sql = sql_of(statements_for(db, "orderdetail")[0])
        do_update = sql[sql.find("DO UPDATE"):]

        assert "outlet_code =" not in do_update


class TestUrutanEksekusi:

    def test_sale_di_insert_sebelum_itemnya(self):
        """Foreign key orderdetail → ordertransaction menuntut urutan ini."""
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])

        assert [s.table.name for s in db.statements] == ["ordertransaction", "orderdetail"]

    def test_urutan_terjaga_untuk_banyak_sale(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, items=[build_item(transaction_id=1)]),
            build_sale(transaction_id=2, items=[build_item(transaction_id=2)]),
        ]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        # Bulk: semua header dulu, baru semua item — bukan selang-seling per sale.
        assert [s.table.name for s in db.statements] == ["ordertransaction", "orderdetail"]

    def test_urutan_header_item_lalu_pembayaran(self):
        """FK orderdetail & orderpaydetail → ordertransaction: header harus ada lebih dulu."""
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, items=[build_item(transaction_id=1)], payments=[build_payment()]),
            build_sale(transaction_id=2, items=[build_item(transaction_id=2)], payments=[build_payment()]),
        ]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert [s.table.name for s in db.statements] == [
            "ordertransaction",
            "orderdetail",
            "orderpaydetail",  # DELETE massal
            "orderpaydetail",  # INSERT massal
        ]

    def test_commit_sekali_di_akhir_bukan_per_baris(self):
        db = RecordingSession()
        sales = [build_sale(transaction_id=i, items=[build_item(transaction_id=i)]) for i in range(1, 4)]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert db.committed == 1


class TestPenangananError:

    def test_rollback_saat_gagal_di_tengah(self):
        # Statement ke-2 = INSERT item massal, sesudah header masuk.
        db = RecordingSession(fail_on_execute_call=2)
        sales = [build_sale(transaction_id=i, items=[build_item(transaction_id=i)]) for i in range(1, 4)]

        with pytest.raises(RuntimeError):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert db.rolled_back == 1

    def test_tidak_commit_saat_gagal(self):
        db = RecordingSession(fail_on_execute_call=1)

        with pytest.raises(RuntimeError):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert db.committed == 0

    def test_exception_diteruskan_ke_pemanggil(self):
        """Route mengandalkan ini untuk mengembalikan 500 — jangan ditelan."""
        db = RecordingSession(fail_on_execute_call=1)

        with pytest.raises(RuntimeError, match="kegagalan database simulasi"):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

    def test_gagal_di_item_juga_rollback_seluruh_batch(self):
        """Satu batch = satu transaksi: sale yang sudah masuk pun harus ikut batal."""
        db = RecordingSession(fail_on_execute_call=2)

        with pytest.raises(RuntimeError):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])

        assert db.rolled_back == 1
        assert db.committed == 0


class TestLogging:

    def test_log_sukses_memuat_outlet_dan_jumlah(self, caplog):
        db = RecordingSession()

        with caplog.at_level("INFO", logger="sync-api"):
            SalesService.sync_sales(db=db, outlet="OUTLET_007", sales_list=[build_sale(items=[build_item()])])

        assert "OUTLET_007" in caplog.text
        assert "inserted_sales=1" in caplog.text
        assert "inserted_items=1" in caplog.text

    def test_log_error_memuat_outlet_dan_pesan(self, caplog):
        db = RecordingSession(fail_on_execute_call=1)

        with caplog.at_level("ERROR", logger="sync-api"):
            with pytest.raises(RuntimeError):
                SalesService.sync_sales(db=db, outlet="OUTLET_007", sales_list=[build_sale()])

        assert "OUTLET_007" in caplog.text
        assert "kegagalan database simulasi" in caplog.text


# ---------------------------------------------------------------------------
# payments (docs/handoff-sync-api-payments.md)
# ---------------------------------------------------------------------------


def build_payment(pay_detail_id=1, **overrides):
    payload = dict(
        pay_detail_id=pay_detail_id,
        computer_id=793,
        pay_type_id=1,
        pay_type_code="1",
        pay_type_name="Cash",
        pay_type_display_name="Cash",
        amount=150000,
    )
    payload.update(overrides)
    return payload


def sale_upsert(db):
    (stmt,) = statements_for(db, "ordertransaction")
    return stmt


class TestPembayaran:

    def test_tanpa_key_payments_tidak_menyentuh_pembayaran(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])

        assert statements_for(db, "orderpaydetail") == []
        stmt = sale_upsert(db)
        assert baris(stmt)["payments_received_at"] is None
        # Kiriman ulang dari agen lama tidak menghapus tanda "sudah diketahui":
        # SET-nya satu untuk semua baris bulk, jadi NULL dari baris ini jatuh ke
        # nilai yang sudah tersimpan.
        assert (
            "payments_received_at = coalesce(excluded.payments_received_at, ordertransaction.payments_received_at)"
            in do_update(stmt)
        )

    @freeze_time("2026-11-18 09:00:00")
    def test_payments_kosong_hapus_baris_lama_dan_tandai_diketahui(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(payments=[])])

        (hapus,) = statements_for(db, "orderpaydetail")
        assert sql_of(hapus).startswith("DELETE FROM orderpaydetail")
        assert params_of(hapus) == {"outlet_code_1": "OUTLET_001", "TransactionID_1": [10001]}
        stmt = sale_upsert(db)
        assert baris(stmt)["payments_received_at"] == datetime(2026, 11, 18, 9, 0)

    def test_payments_diganti_utuh_dalam_satu_transaksi(self):
        db = RecordingSession()
        sale = build_sale(
            payments=[
                build_payment(1, pay_type_id=149, pay_type_name="REEDEM POINT", amount=26030),
                build_payment(2, amount=123970, cash_change=30000),
            ]
        )

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])

        hapus, tambah = statements_for(db, "orderpaydetail")
        assert sql_of(hapus).startswith("DELETE")
        p = params_of(tambah)
        assert (p["outlet_code_m0"], p["TransactionID_m0"], p["ComputerID_m0"], p["PayDetailID_m0"]) == (
            "OUTLET_001",
            10001,
            793,
            1,
        )
        assert (p["PayTypeID_m0"], p["Amount_m0"]) == (149, Decimal("26030"))
        assert (p["PayDetailID_m1"], p["Amount_m1"], p["CashChange_m1"]) == (2, Decimal("123970"), Decimal("30000"))
        assert p["SaleDate_m1"] == date(2026, 1, 15)
        assert db.committed == 1

    def test_hasil_tetap_sales_dan_items(self):
        """Respons ke agen tidak berubah."""
        db = RecordingSession()

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(payments=[build_payment()])])

        assert result == {"sales": 1, "items": 0}

    def test_selisih_dicatat_tetapi_data_tetap_disimpan(self, caplog):
        db = RecordingSession()
        sale = build_sale(receipt_id=5, payments=[build_payment(amount=149000)])

        with caplog.at_level("WARNING", logger="sync-api"):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])

        assert "SYNC PAYMENTS MISMATCH" in caplog.text
        assert "10001" in caplog.text
        assert len(statements_for(db, "orderpaydetail")) == 2

    def test_cocok_dalam_toleransi_dan_void_tidak_dicatat(self, caplog):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, receipt_id=5, payments=[build_payment(amount="150000.5")]),
            build_sale(transaction_id=2, receipt_id=6, deleted=1, payments=[]),
            build_sale(transaction_id=3, receipt_id=0, payments=[]),
        ]

        with caplog.at_level("WARNING", logger="sync-api"):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert "SYNC PAYMENTS MISMATCH" not in caplog.text


# ---------------------------------------------------------------------------
# Bulk upsert (TODO 3.5 / 9.11)
# ---------------------------------------------------------------------------


class TestPotonganBatch:
    """Batas parameter bind Postgres 65.535: header ±40 kolom × 500 = ±20 rb."""

    def test_header_item_dan_pembayaran_dipotong_per_500_baris(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=i, items=[build_item(transaction_id=i)], payments=[build_payment()])
            for i in range(1, 1202)
        ]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert result == {"sales": 1201, "items": 1201}
        header = statements_for(db, "ordertransaction")
        items = statements_for(db, "orderdetail")
        bayar = statements_for(db, "orderpaydetail")
        assert [jumlah_baris(s) for s in header] == [500, 500, 201]
        assert [jumlah_baris(s) for s in items] == [500, 500, 201]
        hapus = [s for s in bayar if sql_of(s).startswith("DELETE")]
        tambah = [s for s in bayar if sql_of(s).startswith("INSERT")]
        assert [len(params_of(s)["TransactionID_1"]) for s in hapus] == [500, 500, 201]
        assert [jumlah_baris(s) for s in tambah] == [500, 500, 201]
        assert db.committed == 1

    def test_tepat_500_satu_statement(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=i) for i in range(500)])

        assert [jumlah_baris(s) for s in statements_for(db, "ordertransaction")] == [500]


class TestDuplikatDalamBatch:
    """Satu INSERT ... ON CONFLICT tidak boleh menyentuh baris yang sama dua
    kali. Duplikat digabung supaya hasil akhirnya sama dengan upsert per baris
    (lihat test integrasi TestDuplikatDalamSatuBatch)."""

    def test_satu_baris_header_kolom_update_dari_terakhir_kolom_insert_dari_pertama(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, reference_no="PERTAMA", receipt_pay_price=100),
            build_sale(transaction_id=2),
            build_sale(transaction_id=1, reference_no="KEDUA", receipt_pay_price=200),
        ]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert result == {"sales": 3, "items": 0}  # tetap menghitung kiriman, seperti dulu
        (stmt,) = statements_for(db, "ordertransaction")
        assert jumlah_baris(stmt) == 2
        pertama = baris(stmt, 0)
        assert (pertama["TransactionID"], pertama["ReferenceNo"], pertama["ReceiptPayPrice"]) == (1, "PERTAMA", 200)

    def test_item_digabung_per_kunci_konflik(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, items=[build_item(order_detail_id=1, qty=1, comment="awal"), build_item(order_detail_id=2)]),
            build_sale(transaction_id=1, items=[build_item(order_detail_id=1, qty=5, comment="akhir")]),
        ]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert result == {"sales": 2, "items": 3}
        (stmt,) = statements_for(db, "orderdetail")
        assert jumlah_baris(stmt) == 2
        satu = baris(stmt, 0)
        # Amount di-update saat konflik → terakhir; Comment tidak → pertama.
        assert (satu["OrderDetailID"], satu["Amount"], satu["Comment"]) == (1, 5.0, "awal")

    def test_payments_dari_kemunculan_terakhir_yang_membawa_key_payments(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, payments=[build_payment(1, amount=100), build_payment(2, amount=50)]),
            build_sale(transaction_id=1, payments=[build_payment(1, amount=150)]),
            build_sale(transaction_id=1),
        ]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        hapus, tambah = statements_for(db, "orderpaydetail")
        assert params_of(hapus)["TransactionID_1"] == [1]
        assert jumlah_baris(tambah) == 1
        assert baris(tambah)["Amount"] == Decimal("150")
        # Sudah diketahui sejak kemunculan kedua — kemunculan ketiga tidak menghapusnya.
        assert baris(sale_upsert(db))["payments_received_at"] is not None


class TestPembayaranMassal:

    def test_transaksi_tanpa_key_payments_tidak_ikut_dihapus(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, payments=[build_payment()]),
            build_sale(transaction_id=2),
            build_sale(transaction_id=3, payments=[]),
        ]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        hapus, tambah = statements_for(db, "orderpaydetail")
        assert params_of(hapus) == {"outlet_code_1": "OUTLET_001", "TransactionID_1": [1, 3]}
        assert [baris(tambah, i)["TransactionID"] for i in range(jumlah_baris(tambah))] == [1]
        header = sale_upsert(db)
        assert [baris(header, i)["payments_received_at"] is not None for i in range(3)] == [True, False, True]

    def test_semua_payments_kosong_hanya_delete(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(payments=[])])

        (hapus,) = statements_for(db, "orderpaydetail")
        assert sql_of(hapus).startswith("DELETE")

    def test_log_sukses_menghitung_payments_seperti_dulu(self, caplog):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, payments=[build_payment(1), build_payment(2)]),
            build_sale(transaction_id=1, payments=[build_payment(1)]),
            build_sale(transaction_id=2, items=[build_item(transaction_id=2)]),
        ]

        with caplog.at_level("INFO", logger="sync-api"):
            SalesService.sync_sales(db=db, outlet="OUTLET_007", sales_list=sales)

        assert "SYNC SUCCESS outlet=OUTLET_007 inserted_sales=3 inserted_items=1 inserted_payments=3" in caplog.text

    def test_log_mismatch_per_kiriman_seperti_dulu(self, caplog):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=7, receipt_id=5, payments=[build_payment(amount=1)]),
            build_sale(transaction_id=8, receipt_id=6, payments=[build_payment(amount=150000)]),
        ]

        with caplog.at_level("WARNING", logger="sync-api"):
            SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert "SYNC PAYMENTS MISMATCH outlet=OUTLET_001 count=1 transaction_ids=[7]" in caplog.text
