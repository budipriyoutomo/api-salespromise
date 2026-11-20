"""Filter tanggal redundan di orderdetail (TODO 9.13) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test` — modul ini menjalankan `drop_all`.

Yang dibuktikan:
- angka hasil query SAMA PERSIS dengan versi lama (filter dimatikan lewat
  monkeypatch `_filter_tanggal_item`), untuk data yang tanggal itemnya sama
  dengan transaksinya — kondisi yang berlaku di produksi;
- planner memakai `ix_orderdetail_saledate_outlet` (migrasi 017) di ketiga
  query; versi lama tidak bisa, karena tidak ada kondisi di kolom itu.
"""

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import migrate
from app.database import Base
from app.services.sales_service import SalesService
from tests.conftest import make_item_row, make_sale_row

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRASI_017 = migrate.MIGRATIONS_DIR / "017_orderdetail_report_indexes.sql"
INDEX_TANGGAL = "ix_orderdetail_saledate_outlet"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
    pytest.mark.skipif(
        bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).database != "sync_test",
        reason="hanya boleh dijalankan ke database sync_test (drop_all)",
    ),
]

AWAL_DATA = date(2026, 7, 1)
HARI_DATA = 120
GROUPS = ["COLORPLATE", " food", "Drink", None]


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Index 017 tidak didefinisikan di model — pasang dari file migrasinya
    # supaya yang diuji adalah index produksi yang sama persis.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for statement in migrate.pecah_statement(MIGRASI_017.read_text(encoding="utf-8")):
            conn.exec_driver_sql(statement)

    _seed(engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed(engine):
    """120 hari, dua outlet, beberapa transaksi per hari, sebagian void.

    Tanggal item selalu = tanggal transaksinya (seperti produksi).
    """
    with Session(bind=engine) as db:
        tid = 0
        for h in range(HARI_DATA):
            hari = AWAL_DATA + timedelta(days=h)
            for outlet in ("OUTLET_001", "OUTLET_002"):
                for k in range(3):
                    tid += 1
                    db.add(
                        make_sale_row(
                            transaction_id=tid,
                            outlet_code=outlet,
                            sale_date=hari,
                            deleted=1 if tid % 11 == 0 else 0,
                        )
                    )
                    for d in range(1, 4):
                        pid = 100 + (tid * d) % 9
                        db.add(
                            make_item_row(
                                order_detail_id=d,
                                transaction_id=tid,
                                outlet_code=outlet,
                                sale_date=hari,
                                product_id=pid,
                                product_group=GROUPS[pid % len(GROUPS)],
                                product_name=f"Menu {pid}",
                                qty=1 + (tid + d) % 4,
                                price=1000 * (1 + pid % 5),
                            )
                        )
            db.flush()
        db.commit()

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("ANALYZE ordertransaction")
        conn.exec_driver_sql("ANALYZE orderdetail")


@pytest.fixture()
def db(engine):
    with Session(bind=engine) as session:
        yield session
        session.rollback()


def _tanpa_filter_item(monkeypatch):
    """Versi lama: filter tanggal hanya di ordertransaction."""
    monkeypatch.setattr(SalesService, "_filter_tanggal_item", staticmethod(lambda query, **_: query))


RENTANG = [
    dict(start_date=date(2026, 8, 1), end_date=date(2026, 8, 30)),
    dict(start_date=date(2026, 10, 15)),
    dict(end_date=date(2026, 7, 10)),
    dict(start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), outlet="OUTLET_002"),
    dict(start_date=date(2026, 9, 5), end_date=date(2026, 9, 5)),
]
ID_RENTANG = ["30_hari", "hanya_awal", "hanya_akhir", "satu_outlet", "satu_hari"]

QUERY = {
    "top_products": lambda db, f: SalesService.get_top_products(db, limit=50, **f),
    "top_products_group": lambda db, f: SalesService.get_top_products(db, product_group="food", limit=50, **f),
    "by_product_groups": lambda db, f: SalesService.get_sales_by_product_groups(db, ["COLORPLATE", "DRINK"], **f),
    "by_product_groups_ids": lambda db, f: SalesService.get_sales_by_product_groups(
        db, ["COLORPLATE"], product_ids=[101, 105], **f
    ),
    "by_product_ids": lambda db, f: SalesService.get_sales_by_product_ids(
        db, list(range(100, 109)), exclude_groups=["COLORPLATE"], **f
    ),
}


def _hasil(rows):
    return sorted(tuple(r) for r in rows)


@pytest.mark.parametrize("rentang", RENTANG, ids=ID_RENTANG)
@pytest.mark.parametrize("nama", list(QUERY))
def test_angka_identik_dengan_versi_lama(db, monkeypatch, nama, rentang):
    baru = _hasil(QUERY[nama](db, rentang))

    with monkeypatch.context() as m:
        _tanpa_filter_item(m)
        lama = _hasil(QUERY[nama](db, rentang))

    assert baru, "data uji harus menghasilkan baris — perbandingan kosong tidak membuktikan apa pun"
    assert baru == lama


def _rencana(engine, panggil) -> str:
    """Jalankan query aplikasi, tangkap SQL-nya, lalu EXPLAIN dengan parameter yang sama."""
    with engine.connect() as conn:
        tertangkap = []

        def rekam(_c, _cur, statement, parameters, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                tertangkap.append((statement, parameters))

        event.listen(conn, "before_cursor_execute", rekam)
        with Session(bind=conn) as s:
            panggil(s)
        event.remove(conn, "before_cursor_execute", rekam)

        # Data uji jauh lebih kecil dari produksi; tanpa ini planner memilih
        # seq scan apa pun indexnya. Yang diuji: index BISA dipakai.
        conn.exec_driver_sql("SET enable_seqscan = off")
        (sql, params), = tertangkap
        return "\n".join(r[0] for r in conn.exec_driver_sql("EXPLAIN " + sql, params))


@pytest.mark.parametrize("nama", ["top_products", "by_product_groups", "by_product_ids"])
def test_planner_memakai_index_tanggal_orderdetail(engine, nama):
    rencana = _rencana(engine, lambda s: QUERY[nama](s, RENTANG[0]))

    assert INDEX_TANGGAL in rencana, rencana


@pytest.mark.parametrize("nama", ["top_products", "by_product_groups", "by_product_ids"])
def test_versi_lama_tidak_bisa_memakai_index_tanggal(engine, monkeypatch, nama):
    """Pembanding: membuktikan index di test sebelumnya muncul KARENA filter baru."""
    _tanpa_filter_item(monkeypatch)

    rencana = _rencana(engine, lambda s: QUERY[nama](s, RENTANG[0]))

    assert INDEX_TANGGAL not in rencana
