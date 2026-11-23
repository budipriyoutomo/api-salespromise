"""Migrasi 023 (harga v3 di closing_report_items) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test`. Semua tabel dibuat di skema terpisah yang
dihapus lagi di akhir; tabel di skema public tidak disentuh.

Yang diuji:
- 011 → 012 → 023 dijalankan sungguhan; kolom closing_report_items sama
  dengan model (tipe, presisi, nullable);
- item yang sudah ada sebelum migrasi tetap tanpa harga dan isinya tidak
  berubah;
- idempoten: dijalankan ulang tidak gagal dan tidak mengubah apa pun.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import migrate
from app.models.closing_report import ClosingReportItem

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SKEMA = "uji_migrasi_023"
MIGRASI = [
    migrate.MIGRATIONS_DIR / "011_closing_reports.sql",
    migrate.MIGRATIONS_DIR / "012_closing_menu_id.sql",
]
MIGRASI_023 = migrate.MIGRATIONS_DIR / "023_closing_report_item_prices.sql"
KOLOM_BARU = ("unit_price", "sold_amount", "waste_amount", "adjustment_amount", "compensation_amount")
KOLOM_LAMA = "id, revision_id, menu_id, menu_code, menu_name, production_date, sold, waste, adjustment, compensation"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
    pytest.mark.skipif(
        bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).database != "sync_test",
        reason="hanya boleh dijalankan ke database sync_test",
    ),
]


@pytest.fixture()
def conn():
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {SKEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {SKEMA}"))
        c.execute(text(f"SET search_path TO {SKEMA}"))
        c.commit()
        for path in MIGRASI:
            _sql_mentah(c, path)
        c.commit()
        try:
            yield c
        finally:
            c.rollback()
            c.execute(text(f"DROP SCHEMA IF EXISTS {SKEMA} CASCADE"))
            c.commit()
    engine.dispose()


def _sql_mentah(c, path):
    # Cursor DBAPI tanpa parameter, seperti migrate.py: 012 memuat `%` di
    # RAISE EXCEPTION, yang dianggap placeholder kalau lewat exec_driver_sql.
    cur = c.connection.dbapi_connection.cursor()
    try:
        cur.execute(path.read_text(encoding="utf-8"))
    finally:
        cur.close()


def _jalankan_023(c):
    _sql_mentah(c, MIGRASI_023)
    c.commit()


def _kolom(c):
    return {
        r.column_name: (r.data_type, r.numeric_precision, r.numeric_scale, r.is_nullable, r.column_default)
        for r in c.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = :s AND table_name = 'closing_report_items'"
            ),
            {"s": SKEMA},
        )
    }


def _isi(c, kolom):
    return [tuple(r) for r in c.execute(text(f"SELECT {kolom} FROM closing_report_items ORDER BY id"))]


def _isi_laporan(c):
    c.execute(
        text(
            "INSERT INTO closing_reports (closing_report_id, report_date, outlet_code, outlet_name, brand_code, brand_name) "
            "VALUES ('6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b', '2026-10-02', 'STTSM', 'PIK', 'MHR', 'Maharasa')"
        )
    )
    c.execute(
        text(
            "INSERT INTO closing_report_revisions (report_id, message_id, version, sent_at, received_at, is_current, raw_payload) "
            "SELECT id, 'm1', 1, '2026-10-02 15:15', '2026-10-02 15:16', TRUE, '{}'::jsonb FROM closing_reports"
        )
    )
    c.execute(
        text(
            "INSERT INTO closing_report_items (revision_id, menu_id, menu_code, menu_name, production_date, "
            "sold, waste, adjustment, compensation) "
            "SELECT id, '0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d', 'SU-001', 'Salmon', '2026-10-02', 42, 3, 1, 0 "
            "FROM closing_report_revisions"
        )
    )
    c.commit()


def test_kolom_sama_dengan_model(conn):
    _jalankan_023(conn)

    kolom = _kolom(conn)
    tabel = ClosingReportItem.__table__
    for nama in KOLOM_BARU:
        assert kolom[nama][:4] == ("numeric", 14, 2, "YES"), nama
        assert (tabel.c[nama].type.precision, tabel.c[nama].type.scale) == (14, 2), nama
        assert tabel.c[nama].nullable is True, nama
    assert set(tabel.c.keys()) == set(kolom), "kolom model dan migrasi berbeda"


def test_item_lama_tetap_tanpa_harga_dan_tidak_berubah(conn):
    _isi_laporan(conn)
    sebelum = _isi(conn, KOLOM_LAMA)

    _jalankan_023(conn)

    assert _isi(conn, KOLOM_LAMA) == sebelum
    assert _isi(conn, ", ".join(KOLOM_BARU)) == [(None,) * 5]


def test_idempoten(conn):
    _isi_laporan(conn)
    _jalankan_023(conn)
    conn.execute(text("UPDATE closing_report_items SET unit_price = 12500.5, sold_amount = 525021"))
    conn.commit()
    kolom, isi = _kolom(conn), _isi(conn, f"{KOLOM_LAMA}, {', '.join(KOLOM_BARU)}")

    _jalankan_023(conn)

    assert (_kolom(conn), _isi(conn, f"{KOLOM_LAMA}, {', '.join(KOLOM_BARU)}")) == (kolom, isi)
