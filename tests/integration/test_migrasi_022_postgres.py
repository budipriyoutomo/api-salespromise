"""Migrasi 022 (index sync-status, TODO 9.14) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test` — modul ini menjalankan `drop_all`.

Yang diuji:
- `CREATE INDEX CONCURRENTLY` jalan lewat migrate.py (di luar transaksi),
  tercatat, dan idempoten;
- jumlah baris sebelum dan sesudah migrasi sama persis;
- index valid;
- `get_sync_status` memberi angka yang sama dengan query GROUP BY yang
  menghitungnya langsung, dan planner memakai index per outlet — bukan
  memindai seluruh ordertransaction.
"""

import os
from datetime import date, datetime, timedelta

import psycopg2
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import migrate
from app.database import Base
from app.services.sales_service import SalesService
from tests.conftest import make_sale_row

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRASI_022 = migrate.MIGRATIONS_DIR / "022_ordertransaction_sync_status_index.sql"
INDEX_BARU = "ix_ordertransaction_outlet_updated"
# Dibuat migrasi 002; model tidak mendefinisikannya, jadi dipasang di fixture.
INDEX_002 = "idx_ordertransaction_outlet_saledate"

HARI_INI = date(2026, 11, 20)
OUTLET = ["STJWB", "STP23", "STTSM", "STMATI"]

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
    with engine.begin() as conn:
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS {INDEX_002} ON ordertransaction (outlet_code, "SaleDate")'))

    yield engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def data(engine):
    """120 hari ke belakang. STMATI berhenti mengirim 60 hari lalu."""
    db = sessionmaker(bind=engine)()
    tid = 0
    for h in range(120):
        hari = HARI_INI - timedelta(days=h)
        for i, outlet in enumerate(OUTLET):
            if outlet == "STMATI" and h < 60:
                continue
            for k in range(1 + (h + i) % 3):
                tid += 1
                db.add(
                    make_sale_row(
                        transaction_id=tid,
                        outlet_code=outlet,
                        sale_date=hari,
                        updated_at=datetime(hari.year, hari.month, hari.day, 8 + k, i),
                        deleted=1 if tid % 13 == 0 else 0,
                    )
                )
    db.commit()
    db.close()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("ANALYZE ordertransaction")


def _koneksi_psycopg2():
    url = make_url(TEST_DATABASE_URL)
    return psycopg2.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    )


def _jumlah_baris(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM ordertransaction")).scalar()


@pytest.fixture(scope="module")
def migrasi(engine, data):
    sebelum = _jumlah_baris(engine)
    conn = _koneksi_psycopg2()
    try:
        dijalankan = migrate.jalankan(conn, [MIGRASI_022])
        kedua = migrate.jalankan(conn, [MIGRASI_022])
    finally:
        conn.close()
    return {"sebelum": sebelum, "sesudah": _jumlah_baris(engine), "dijalankan": dijalankan, "kedua": kedua}


def test_file_ditandai_tanpa_transaksi():
    assert migrate.tanpa_transaksi(MIGRASI_022.read_text(encoding="utf-8"))


def test_migrasi_jalan_sekali_dan_tercatat(migrasi):
    assert migrasi["dijalankan"] == [MIGRASI_022.name]
    assert migrasi["kedua"] == []


def test_tidak_ada_baris_yang_berubah(migrasi):
    assert migrasi["sebelum"] == migrasi["sesudah"] > 0


def test_index_baru_ada_dan_valid(engine, migrasi):
    with engine.connect() as c:
        rows = dict(
            c.execute(
                text(
                    "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE i.indrelid = 'ordertransaction'::regclass"
                )
            ).all()
        )

    assert rows.get(INDEX_BARU) is True


def test_tidak_membuat_index_ganda_untuk_saledate(engine, migrasi):
    """(outlet_code, "SaleDate") sudah ada sejak 002 — 022 tidak boleh menduplikasinya."""
    with engine.connect() as c:
        definisi = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'ordertransaction'")
        ).scalars().all()

    assert sum('(outlet_code, "SaleDate")' in d for d in definisi) == 1


def test_statement_ulang_tanpa_catatan_tetap_aman(engine, migrasi):
    conn = _koneksi_psycopg2()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for statement in migrate.pecah_statement(MIGRASI_022.read_text(encoding="utf-8")):
                cur.execute(statement)
    finally:
        conn.close()

    assert _jumlah_baris(engine) == migrasi["sebelum"]


def test_angka_sama_dengan_group_by_langsung(engine, migrasi):
    awal = HARI_INI - timedelta(days=29)
    with engine.connect() as c:
        harapan = {
            r.outlet_code: (r.last_sale_date, r.last_synced_at, r.n)
            for r in c.execute(
                text(
                    'SELECT outlet_code, max("SaleDate") AS last_sale_date, max(updated_at) AS last_synced_at, '
                    'count(*) FILTER (WHERE "SaleDate" >= :awal) AS n '
                    "FROM ordertransaction GROUP BY outlet_code"
                ),
                {"awal": awal},
            )
        }
    with Session(bind=engine) as db:
        hasil = {
            r.outlet_code: (r.last_sale_date, r.last_synced_at, r.transactions_last_30_days)
            for r in SalesService.get_sync_status(db, hari_ini=HARI_INI)
        }
        satu = SalesService.get_sync_status(db, outlet="STP23", hari_ini=HARI_INI)

    assert hasil == harapan
    assert hasil["STMATI"][2] == 0  # berhenti mengirim → tetap muncul, nol
    assert [(r.outlet_code, r.transactions_last_30_days) for r in satu] == [("STP23", harapan["STP23"][2])]


def _rencana(engine, **kwargs) -> str:
    with engine.connect() as conn:
        tertangkap = []

        def rekam(_c, _cur, statement, parameters, _ctx, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                tertangkap.append((statement, parameters))

        event.listen(conn, "before_cursor_execute", rekam)
        with Session(bind=conn) as s:
            SalesService.get_sync_status(s, hari_ini=HARI_INI, **kwargs)
        event.remove(conn, "before_cursor_execute", rekam)

        # Data uji kecil: tanpa ini planner memilih seq scan apa pun indexnya.
        conn.exec_driver_sql("SET enable_seqscan = off")
        (sql, params), = tertangkap
        return "\n".join(r[0] for r in conn.exec_driver_sql("EXPLAIN " + sql, params))


@pytest.mark.parametrize("kwargs", [{}, {"outlet": "STP23"}], ids=["semua_outlet", "satu_outlet"])
def test_planner_memakai_index_per_outlet(engine, migrasi, kwargs):
    rencana = _rencana(engine, **kwargs)

    assert INDEX_BARU in rencana, rencana
    assert INDEX_002 in rencana, rencana
    assert "Seq Scan on ordertransaction" not in rencana, rencana
