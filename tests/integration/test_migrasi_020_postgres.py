"""Migrasi 020 (warna piring di closing_menus) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test`. Semua tabel dibuat di skema terpisah yang
dihapus lagi di akhir; tabel di skema public tidak disentuh.

Yang diuji:
- 011 → 012 → 018 → 020 dijalankan sungguhan; kolom closing_menus sama
  dengan model (tipe, panjang, nullable);
- menu yang sudah ada sebelum migrasi tetap tanpa warna dan isinya tidak
  berubah;
- idempoten: dijalankan ulang tidak gagal dan tidak mengubah apa pun.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import migrate
from app.models.closing_report import ClosingMenu

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SKEMA = "uji_migrasi_020"
MIGRASI = [
    migrate.MIGRATIONS_DIR / "011_closing_reports.sql",
    migrate.MIGRATIONS_DIR / "012_closing_menu_id.sql",
    migrate.MIGRATIONS_DIR / "018_closing_menu_not_in_pos.sql",
]
MIGRASI_020 = migrate.MIGRATIONS_DIR / "020_closing_menu_platecolor.sql"
KOLOM_BARU = ("platecolor", "platecolor_by", "platecolor_at")
KOLOM_LAMA = "id, menu_id, menu_code, menu_name, brand_code, not_in_pos, not_in_pos_by, first_seen_at, last_seen_at"

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


def _jalankan_020(c):
    _sql_mentah(c, MIGRASI_020)
    c.commit()


def _kolom(c):
    return {
        r.column_name: (r.data_type, r.character_maximum_length, r.is_nullable, r.column_default)
        for r in c.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = :s AND table_name = 'closing_menus'"
            ),
            {"s": SKEMA},
        )
    }


def _isi(c, kolom):
    return [tuple(r) for r in c.execute(text(f"SELECT {kolom} FROM closing_menus ORDER BY id"))]


def test_kolom_sama_dengan_model(conn):
    _jalankan_020(conn)

    kolom = _kolom(conn)
    assert kolom["platecolor"][:3] == ("character varying", 255, "YES")
    assert kolom["platecolor_by"][:3] == ("character varying", 255, "YES")
    assert kolom["platecolor_at"][:3] == ("timestamp without time zone", None, "YES")

    tabel = ClosingMenu.__table__
    for nama in KOLOM_BARU:
        assert (kolom[nama][2] == "YES") == tabel.c[nama].nullable, nama
    assert tabel.c["platecolor"].type.length == 255
    assert tabel.c["platecolor_by"].type.length == 255
    assert set(tabel.c.keys()) == set(kolom), "kolom model dan migrasi berbeda"


def test_menu_lama_tetap_tanpa_warna_dan_tidak_berubah(conn):
    conn.execute(
        text(
            "INSERT INTO closing_menus (menu_code, menu_id, menu_name, brand_code, not_in_pos, not_in_pos_by) VALUES "
            "('SU-001', '0b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f', 'Salmon', 'MHR', FALSE, NULL), "
            "(NULL, '1b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f', 'Piring', NULL, TRUE, 'admin@maharasa.id')"
        )
    )
    conn.commit()
    sebelum = _isi(conn, KOLOM_LAMA)

    _jalankan_020(conn)

    assert _isi(conn, KOLOM_LAMA) == sebelum
    assert _isi(conn, ", ".join(KOLOM_BARU)) == [(None, None, None), (None, None, None)]


def test_idempoten(conn):
    _jalankan_020(conn)
    conn.execute(
        text(
            "INSERT INTO closing_menus (menu_code, menu_id, menu_name, platecolor, platecolor_by) "
            "VALUES ('SU-002', '2b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f', 'Tuna', 'RED', 'admin@maharasa.id')"
        )
    )
    conn.commit()
    kolom, isi = _kolom(conn), _isi(conn, f"{KOLOM_LAMA}, {', '.join(KOLOM_BARU)}")

    _jalankan_020(conn)

    assert (_kolom(conn), _isi(conn, f"{KOLOM_LAMA}, {', '.join(KOLOM_BARU)}")) == (kolom, isi)
