"""Test integrasi sync_sales terhadap PostgreSQL sungguhan.

Dilewati otomatis kalau env `TEST_DATABASE_URL` tidak diset:

    TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/sync_test \
        pytest tests/integration -v

Hanya di sini `on_conflict_do_update` benar-benar dieksekusi. Test unit
(tests/unit/test_sales_service_sync.py) hanya memeriksa bentuk statement-nya.

CATATAN SKEMA
-------------
Unique index di bawah ini sama dengan `migrations/002_unique_indexes.sql`.
Dibuat ulang di sini (bukan menjalankan file .sql-nya) supaya test tidak
bergantung pada urutan migrasi, dan supaya ketidakcocokan antara kode dan
skema langsung terlihat sebagai kegagalan test.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.sales_service import SalesService
from tests.unit.test_sales_service_sync import build_item, build_sale

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
]


UNIQUE_INDEXES = (
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_ordertransaction_txn_outlet '
    'ON ordertransaction ("TransactionID", outlet_code)',
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_orderdetail_detail_txn_product '
    'ON orderdetail ("OrderDetailID", "TransactionID", "ProductID")',
)


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for ddl in UNIQUE_INDEXES:
            conn.execute(text(ddl))

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def pg_session(engine):
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text('TRUNCATE orderdetail, ordertransaction CASCADE'))
        session.commit()
        session.close()


def fetch_sale(session, transaction_id, outlet_code):
    row = session.execute(
        text(
            'SELECT "ReceiptTotalAmount", "TransactionStatusID", created_at, updated_at '
            'FROM ordertransaction WHERE "TransactionID" = :tid AND outlet_code = :outlet'
        ),
        {"tid": transaction_id, "outlet": outlet_code},
    ).fetchone()
    return row


def count(session, table):
    return session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


class TestUpsertSungguhan:

    def test_insert_pertama_kali(self, pg_session):
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, items=[build_item(transaction_id=1)])],
        )

        assert count(pg_session, "ordertransaction") == 1
        assert count(pg_session, "orderdetail") == 1

    def test_kirim_ulang_tidak_menduplikasi(self, pg_session):
        sale = build_sale(transaction_id=1, items=[build_item(transaction_id=1)])

        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[sale])
        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[sale])
        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[sale])

        assert count(pg_session, "ordertransaction") == 1
        assert count(pg_session, "orderdetail") == 1

    def test_nilai_ter_update_saat_kirim_ulang(self, pg_session):
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, receipt_total_amount=100000.0)],
        )
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, receipt_total_amount=250000.0, transaction_status_id=3)],
        )

        row = fetch_sale(pg_session, 1, "OUTLET_001")
        assert float(row[0]) == 250000.0
        assert row[1] == 3

    def test_created_at_tidak_berubah_updated_at_berubah(self, pg_session):
        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=1)])
        created_awal, updated_awal = fetch_sale(pg_session, 1, "OUTLET_001")[2:]

        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=1)])
        created_akhir, updated_akhir = fetch_sale(pg_session, 1, "OUTLET_001")[2:]

        assert created_akhir == created_awal
        assert updated_akhir >= updated_awal

    def test_transaction_id_sama_dari_dua_outlet_tersimpan_terpisah(self, pg_session):
        """Inti dari index (TransactionID, outlet_code)."""
        SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=[build_sale(transaction_id=500)])
        SalesService.sync_sales(db=pg_session, outlet="OUTLET_002", sales_list=[build_sale(transaction_id=500)])

        assert count(pg_session, "ordertransaction") == 2
        assert fetch_sale(pg_session, 500, "OUTLET_001") is not None
        assert fetch_sale(pg_session, 500, "OUTLET_002") is not None

    def test_item_ter_update_saat_kirim_ulang(self, pg_session):
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, items=[build_item(transaction_id=1, qty=2.0)])],
        )
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, items=[build_item(transaction_id=1, qty=9.0)])],
        )

        qty = pg_session.execute(text('SELECT "Amount" FROM orderdetail')).scalar()
        assert float(qty) == 9.0
        assert count(pg_session, "orderdetail") == 1

    def test_presisi_numeric_terjaga(self, pg_session):
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, receipt_total_amount=150000.1234)],
        )

        assert float(fetch_sale(pg_session, 1, "OUTLET_001")[0]) == 150000.1234


class TestTransaksional:

    def test_rollback_membatalkan_seluruh_batch(self, pg_session):
        """Sale kedua punya item dengan ProductID null → gagal; sale pertama ikut batal."""
        sales = [
            build_sale(transaction_id=1, items=[build_item(transaction_id=1)]),
            build_sale(transaction_id=2, items=[build_item(transaction_id=2, product_id=None)]),
        ]

        with pytest.raises(Exception):
            SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=sales)

        pg_session.rollback()
        assert count(pg_session, "ordertransaction") == 0

    def test_item_tanpa_transaksi_induk_ditolak_foreign_key(self, pg_session):
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            pg_session.execute(
                text(
                    'INSERT INTO orderdetail ("SaleDate", "OrderDetailID", "TransactionID", "ProductID") '
                    "VALUES (:d, 1, 999999, 1)"
                ),
                {"d": date(2026, 1, 15)},
            )
            pg_session.commit()


class TestQueryBaca:

    def test_alur_sync_lalu_baca_colorplate(self, pg_session):
        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[
                build_sale(
                    transaction_id=1,
                    sale_date=date(2026, 1, 15),
                    items=[
                        build_item(order_detail_id=1, transaction_id=1, product_name="RED", qty=2.0),
                        build_item(order_detail_id=2, transaction_id=1, product_id=102, product_name="RED", qty=3.0),
                        build_item(
                            order_detail_id=3,
                            transaction_id=1,
                            product_id=103,
                            product_group="FOOD",
                            product_name="NASI",
                            qty=10.0,
                        ),
                    ],
                )
            ],
        )

        result = SalesService.get_sales_colorplate(
            db=pg_session,
            outlet="OUTLET_001",
            start_date=date(2026, 1, 15),
            end_date=date(2026, 1, 15),
        )

        assert len(result) == 1
        assert result[0].product_name == "RED"
        assert float(result[0].sold) == 5.0

    def test_sold_bertipe_decimal_dari_postgres(self, pg_session):
        """Route publish membungkusnya dengan `int()` — pastikan tipenya memang Decimal."""
        from decimal import Decimal

        SalesService.sync_sales(
            db=pg_session,
            outlet="OUTLET_001",
            sales_list=[build_sale(transaction_id=1, items=[build_item(transaction_id=1, qty=2.0)])],
        )

        result = SalesService.get_sales_colorplate(db=pg_session, outlet="OUTLET_001")

        assert isinstance(result[0].sold, Decimal)


class TestPerforma:

    @pytest.mark.slow
    def test_payload_besar_masih_wajar(self, pg_session):
        """1.000 transaksi × 3 item — penanda TODO 3.5 (bulk upsert)."""
        import time

        sales = [
            build_sale(
                transaction_id=i,
                items=[build_item(order_detail_id=j, transaction_id=i, product_id=100 + j) for j in range(1, 4)],
            )
            for i in range(1, 1001)
        ]

        mulai = time.monotonic()
        result = SalesService.sync_sales(db=pg_session, outlet="OUTLET_001", sales_list=sales)
        durasi = time.monotonic() - mulai

        assert result == {"sales": 1000, "items": 3000}
        assert durasi < 60, f"sync 1.000 transaksi butuh {durasi:.1f} detik"
