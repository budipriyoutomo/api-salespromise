"""Migrasi 019 (syarat closing per brand) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test`. Semua tabel dibuat di skema terpisah yang
dihapus lagi di akhir; tabel di skema public tidak disentuh.

Yang diuji:
- 009 → 019 dijalankan sungguhan; kolom baru sama dengan model
  (tipe, nullable, default);
- brand yang sudah ada sebelum migrasi tetap `requires_closing = TRUE` dan
  isinya tidak berubah, mapping outlet juga tidak berubah;
- idempoten: dijalankan ulang tidak gagal dan tidak mengubah apa pun.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import migrate
from app.models.brand import Brand

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SKEMA = "uji_migrasi_019"
MIGRASI = [migrate.MIGRATIONS_DIR / "009_brands.sql"]
MIGRASI_019 = migrate.MIGRATIONS_DIR / "019_brand_requires_closing.sql"

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
    # Cursor DBAPI tanpa parameter, seperti migrate.py.
    cur = c.connection.dbapi_connection.cursor()
    try:
        cur.execute(path.read_text(encoding="utf-8"))
    finally:
        cur.close()


def _jalankan_019(c):
    _sql_mentah(c, MIGRASI_019)
    c.commit()


def _kolom(c):
    return {
        r.column_name: (r.data_type, r.is_nullable, r.column_default)
        for r in c.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = :s AND table_name = 'brands'"
            ),
            {"s": SKEMA},
        )
    }


def _isi(c, sql):
    return [tuple(r) for r in c.execute(text(sql))]


BRAND_LAMA = "SELECT id, code, name, is_active, created_at, updated_at FROM brands ORDER BY id"
MAPPING = "SELECT id, outlet_code, brand_id, created_at, updated_at FROM outlet_brand_mappings ORDER BY id"


def test_kolom_sama_dengan_model(conn):
    _jalankan_019(conn)

    kolom = _kolom(conn)
    assert kolom["requires_closing"] == ("boolean", "NO", "true")

    tabel = Brand.__table__
    assert tabel.c["requires_closing"].nullable is False
    assert set(tabel.c.keys()) == set(kolom), "kolom model dan migrasi berbeda"


def test_brand_lama_tetap_wajib_closing_dan_tidak_berubah(conn):
    conn.execute(
        text("INSERT INTO brands (code, name, is_active) VALUES ('MHR', 'Maharasa', TRUE), ('OLD', 'Lama', FALSE)")
    )
    conn.execute(
        text(
            "INSERT INTO outlet_brand_mappings (outlet_code, brand_id) VALUES "
            "('OUTLET_001', (SELECT id FROM brands WHERE code = 'MHR')), ('OUTLET_002', NULL)"
        )
    )
    conn.commit()
    brand, mapping = _isi(conn, BRAND_LAMA), _isi(conn, MAPPING)

    _jalankan_019(conn)

    assert _isi(conn, BRAND_LAMA) == brand
    assert _isi(conn, MAPPING) == mapping
    assert _isi(conn, "SELECT requires_closing FROM brands ORDER BY id") == [(True,), (True,)]


def test_idempoten(conn):
    _jalankan_019(conn)
    conn.execute(text("INSERT INTO brands (code, name, requires_closing) VALUES ('NOC', 'Tanpa Closing', FALSE)"))
    conn.commit()
    kolom, brand = _kolom(conn), _isi(conn, "SELECT * FROM brands ORDER BY id")

    _jalankan_019(conn)

    assert (_kolom(conn), _isi(conn, "SELECT * FROM brands ORDER BY id")) == (kolom, brand)
