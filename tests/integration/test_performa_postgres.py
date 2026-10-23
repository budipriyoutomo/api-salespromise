"""Query hasil perbaikan performa terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test` — modul ini menjalankan `drop_all` dan
`TRUNCATE`. Lihat tests/README.md.

Yang hanya bisa diuji di sini:
- `row_number() OVER (...)` di `_info_terbaru_banyak` (nama produk terbaru);
- `list_product_groups` tanpa join, dengan `UPPER(TRIM(...))` Postgres;
- `statement_timeout` dari `engine_options` benar-benar membatalkan query
  dan dikenali handler sebagai query yang dibatalkan.
"""

import asyncio
import json
import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.core.errors import PESAN_QUERY_TERLALU_LAMA, database_operational_error
from app.database import Base, engine_options
from app.services import product_menu_service
from app.services.sales_service import SalesService
from tests.conftest import make_item_row, make_sale_row

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
    pytest.mark.skipif(
        bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).database != "sync_test",
        reason="hanya boleh dijalankan ke database sync_test (drop_all/TRUNCATE)",
    ),
]


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def pg(engine):
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        tabel = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        session.execute(text(f"TRUNCATE {tabel} RESTART IDENTITY CASCADE"))
        session.commit()
        session.close()


def _jual(db, transaction_id, product_id, nama, sale_date, outlet="OUTLET_001", group="FOOD"):
    db.add(make_sale_row(transaction_id=transaction_id, outlet_code=outlet, sale_date=sale_date))
    db.flush()
    db.add(
        make_item_row(
            order_detail_id=1,
            transaction_id=transaction_id,
            outlet_code=outlet,
            sale_date=sale_date,
            product_id=product_id,
            product_group=group,
            product_name=nama,
        )
    )
    db.commit()


def test_info_terbaru_banyak_memilih_penjualan_terakhir(pg):
    _jual(pg, 1, 100, "Lama", date(2026, 9, 1))
    _jual(pg, 2, 100, " Baru ", date(2026, 9, 5))
    # Tanggal sama: nomor transaksi lebih besar menang.
    _jual(pg, 3, 200, "Tuna A", date(2026, 9, 2))
    _jual(pg, 4, 200, "Tuna B", date(2026, 9, 2))

    hasil = product_menu_service._info_terbaru_banyak(pg, [100, 200, 300])

    assert {pid: r.product_name for pid, r in hasil.items()} == {100: "Baru", 200: "Tuna B"}
    assert hasil[100].product_name == product_menu_service._info_terbaru(pg, 100).product_name


def test_list_product_groups_rentang_dan_outlet(pg):
    _jual(pg, 1, 100, "A", date(2026, 9, 1), group=" food")
    _jual(pg, 2, 101, "B", date(2026, 9, 5), group="Drink")
    _jual(pg, 3, 102, "C", date(2026, 9, 5), outlet="OUTLET_002", group="COLORPLATE")

    assert SalesService.list_product_groups(pg) == ["COLORPLATE", "DRINK", "FOOD"]
    assert SalesService.list_product_groups(pg, start_date=date(2026, 9, 5)) == ["COLORPLATE", "DRINK"]
    assert SalesService.list_product_groups(pg, outlet="OUTLET_001", start_date=date(2026, 9, 5)) == ["DRINK"]


def test_statement_timeout_membatalkan_query_dan_jadi_503():
    s = Settings()
    s.DB_POOL_SIZE, s.DB_MAX_OVERFLOW, s.DB_POOL_TIMEOUT, s.DB_POOL_RECYCLE = 1, 0, 5, 1800
    s.DB_STATEMENT_TIMEOUT_MS = 100
    engine = create_engine(TEST_DATABASE_URL, **engine_options(s))
    try:
        with engine.connect() as conn:
            with pytest.raises(OperationalError) as exc:
                conn.execute(text("SELECT pg_sleep(2)"))
    finally:
        engine.dispose()

    class RequestPalsu:
        method = "GET"

        class url:
            path = "/api/sales/summary"

    response = asyncio.run(database_operational_error(RequestPalsu(), exc.value))

    assert response.status_code == 503
    assert json.loads(response.body)["detail"] == PESAN_QUERY_TERLALU_LAMA
