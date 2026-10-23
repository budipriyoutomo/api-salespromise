"""Migrasi 017 (index orderdetail, TODO 9.1) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test` — modul ini menjalankan `drop_all`.

Yang diuji:
- `CREATE INDEX CONCURRENTLY` benar-benar jalan lewat migrate.py (di luar
  transaksi) dan idempoten;
- jumlah baris sebelum dan sesudah migrasi sama persis;
- semua index valid, dan query aplikasi (ekspresi `upper(trim("Group"))`,
  join item → transaksi) bisa memakainya.
"""

import os
from datetime import date

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import migrate
from app.database import Base
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services.sales_service import SalesService, item_join
from tests.conftest import make_item_row, make_sale_row

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRASI_017 = migrate.MIGRATIONS_DIR / "017_orderdetail_report_indexes.sql"
INDEX_BARU = {
    "ix_orderdetail_txn_outlet",
    "ix_orderdetail_saledate_outlet",
    "ix_orderdetail_group_norm",
    "ix_orderdetail_product_terbaru",
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
    pytest.mark.skipif(
        bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).database != "sync_test",
        reason="hanya boleh dijalankan ke database sync_test (drop_all)",
    ),
]


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def data(engine):
    db = sessionmaker(bind=engine)()
    for i in range(1, 51):
        outlet = "OUTLET_001" if i % 2 else "OUTLET_002"
        db.add(make_sale_row(transaction_id=i, outlet_code=outlet, sale_date=date(2026, 9, 1 + i % 28)))
    db.flush()
    for i in range(1, 51):
        outlet = "OUTLET_001" if i % 2 else "OUTLET_002"
        for d in range(1, 4):
            db.add(
                make_item_row(
                    order_detail_id=d,
                    transaction_id=i,
                    outlet_code=outlet,
                    sale_date=date(2026, 9, 1 + i % 28),
                    product_id=100 + d,
                    product_group=[" food", "Drink", "COLORPLATE"][d - 1],
                    product_name=f"Menu {d}",
                )
            )
    db.commit()
    db.close()


def _koneksi_psycopg2():
    url = make_url(TEST_DATABASE_URL)
    return psycopg2.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    )


def _jumlah_baris(engine):
    with engine.connect() as c:
        return (
            c.execute(text("SELECT count(*) FROM ordertransaction")).scalar(),
            c.execute(text("SELECT count(*) FROM orderdetail")).scalar(),
        )


@pytest.fixture(scope="module")
def migrasi(engine, data):
    sebelum = _jumlah_baris(engine)
    conn = _koneksi_psycopg2()
    try:
        dijalankan = migrate.jalankan(conn, [MIGRASI_017])
        # Kedua kali: sudah tercatat, tidak dijalankan lagi.
        kedua = migrate.jalankan(conn, [MIGRASI_017])
    finally:
        conn.close()
    return {"sebelum": sebelum, "sesudah": _jumlah_baris(engine), "dijalankan": dijalankan, "kedua": kedua}


def test_migrasi_jalan_sekali_dan_tercatat(migrasi):
    assert migrasi["dijalankan"] == [MIGRASI_017.name]
    assert migrasi["kedua"] == []


def test_tidak_ada_baris_yang_berubah(migrasi):
    assert migrasi["sebelum"] == migrasi["sesudah"] == (50, 150)


def test_semua_index_baru_ada_dan_valid(engine, migrasi):
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE i.indrelid = 'orderdetail'::regclass"
            )
        ).all()

    status = dict(rows)
    assert INDEX_BARU <= set(status)
    assert all(status[n] for n in INDEX_BARU)


def test_statement_ulang_tanpa_catatan_tetap_aman(engine, migrasi):
    """Kalau schema_migrations hilang, file diulang — IF NOT EXISTS melewati semuanya."""
    conn = _koneksi_psycopg2()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for statement in migrate.pecah_statement(MIGRASI_017.read_text(encoding="utf-8")):
                cur.execute(statement)
    finally:
        conn.close()

    assert _jumlah_baris(engine) == (50, 150)


def _rencana(engine, query) -> str:
    sql = str(query.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    with engine.connect() as c:
        # Data uji kecil: tanpa ini planner selalu memilih seq scan.
        c.execute(text("SET enable_seqscan = off"))
        return "\n".join(r[0] for r in c.execute(text(f"EXPLAIN {sql}")))


def test_filter_group_ternormalisasi_memakai_index_ekspresi(engine, migrasi):
    db = sessionmaker(bind=engine)()
    try:
        group_expr = SalesService._normalized_product_group()
        query = db.query(SalesItems.product_id).filter(group_expr == "FOOD")
        assert "ix_orderdetail_group_norm" in _rencana(engine, query)
    finally:
        db.close()


def test_join_item_ke_transaksi_bisa_memakai_index(engine, migrasi):
    db = sessionmaker(bind=engine)()
    try:
        query = (
            db.query(SalesItems.product_id)
            .join(Sales, item_join)
            .filter(Sales.transaction_id == 7, Sales.outlet_code == "OUTLET_001")
        )
        assert "ix_orderdetail_txn_outlet" in _rencana(engine, query)
    finally:
        db.close()
