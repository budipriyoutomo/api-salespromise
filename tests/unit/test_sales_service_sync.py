"""Test SalesService.sync_sales.

`sync_sales` memakai `on_conflict_do_update` (dialek PostgreSQL), jadi tidak
bisa dijalankan di SQLite. Pendekatan di sini: session di-mock, lalu statement
yang dikirim ke `db.execute()` diperiksa — di-compile ke dialek PostgreSQL untuk
membaca nilai bind dan klausa ON CONFLICT-nya.

Jalur eksekusi sungguhan diuji di tests/integration/test_sync_postgres.py.
"""

from datetime import date, datetime

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
        assert len(statements_for(db, "orderdetail")) == 5

    def test_banyak_sale_dengan_jumlah_item_berbeda(self):
        db = RecordingSession()
        sales = [
            build_sale(transaction_id=1, items=[build_item(transaction_id=1)]),
            build_sale(transaction_id=2, items=[]),
            build_sale(transaction_id=3, items=[build_item(order_detail_id=i, transaction_id=3) for i in (1, 2, 3)]),
        ]

        result = SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert result == {"sales": 3, "items": 4}

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

        assert params_of(db.statements[0])["outlet_code"] == "OUTLET_009"

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
        p = params_of(db.statements[0])

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
        p = params_of(db.statements[0])

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
        p = params_of(db.statements[0])

        assert p["VoidStaffID"] == 9
        assert p["VoidReason"] == "salah input"
        assert p["VoidTime"] == datetime(2026, 1, 15, 11, 0)

    def test_presisi_desimal_tidak_hilang(self):
        """Kolom DB NUMERIC(18,4) — nilai desimal harus lolos utuh."""
        db = RecordingSession()
        sale = build_sale(receipt_total_amount=150000.1234, transaction_vat=14850.5678)

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[sale])
        p = params_of(db.statements[0])

        assert p["ReceiptTotalAmount"] == 150000.1234
        assert p["TransactionVAT"] == 14850.5678

    @freeze_time("2026-03-01 08:00:00")
    def test_created_at_dan_updated_at_diisi_saat_insert(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale()])
        p = params_of(db.statements[0])

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

        outlets = [params_of(s)["outlet_code"] for s in statements_for(db, "ordertransaction")]
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
        p = params_of(statements_for(db, "orderdetail")[0])

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
        p = params_of(statements_for(db, "orderdetail")[0])

        assert p["TransactionID"] == 10001

    def test_sale_date_item_dipakai_apa_adanya(self):
        db = RecordingSession()
        item = build_item(sale_date=date(2026, 2, 1))

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[item])])

        assert params_of(statements_for(db, "orderdetail")[0])["SaleDate"] == date(2026, 2, 1)

    def test_konflik_item_berdasarkan_order_detail_transaction_product(self):
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])
        sql = sql_of(statements_for(db, "orderdetail")[0])

        assert 'ON CONFLICT ("OrderDetailID", "TransactionID", "ProductID")' in sql

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

    def test_item_tidak_membawa_outlet_code(self):
        """Penanda TODO 0.5 — orderdetail belum punya kolom outlet_code.

        Ubah test ini begitu kolom tersebut ditambahkan.
        """
        db = RecordingSession()

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=[build_sale(items=[build_item()])])

        assert "outlet_code" not in params_of(statements_for(db, "orderdetail")[0])


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

        assert [s.table.name for s in db.statements] == [
            "ordertransaction",
            "orderdetail",
            "ordertransaction",
            "orderdetail",
        ]

    def test_commit_sekali_di_akhir_bukan_per_baris(self):
        db = RecordingSession()
        sales = [build_sale(transaction_id=i, items=[build_item(transaction_id=i)]) for i in range(1, 4)]

        SalesService.sync_sales(db=db, outlet="OUTLET_001", sales_list=sales)

        assert db.committed == 1


class TestPenangananError:

    def test_rollback_saat_gagal_di_tengah(self):
        db = RecordingSession(fail_on_execute_call=3)
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
