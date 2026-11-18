"""Migrasi 021 (orderpaydetail + ordertransaction.payments_received_at) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test`. Semua tabel dibuat di skema terpisah yang
dihapus lagi di akhir; tabel di skema public tidak disentuh.

`ordertransaction` dibuat minimal (PK komposit seperti migrasi 010) supaya
ADD COLUMN benar-benar diuji, bukan dilewati karena kolomnya sudah ada.

Yang diuji:
- kolom orderpaydetail sama dengan model (nama, tipe, nullable), PK dan FK;
- transaksi yang sudah ada tetap utuh dan `payments_received_at`-nya NULL;
- FK menolak pembayaran tanpa header di outlet yang sama;
- idempoten: dijalankan ulang tidak gagal dan tidak mengubah apa pun.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

import migrate
from app.models.sales_payments import SalesPayments

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SKEMA = "uji_migrasi_021"
MIGRASI_021 = migrate.MIGRATIONS_DIR / "021_orderpaydetail.sql"

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
        c.execute(
            text(
                'CREATE TABLE ordertransaction ("TransactionID" INTEGER NOT NULL, outlet_code VARCHAR(20) NOT NULL, '
                '"SaleDate" DATE, "ReceiptPayPrice" NUMERIC(18,4) NOT NULL DEFAULT 0, '
                'CONSTRAINT ordertransaction_pkey PRIMARY KEY ("TransactionID", outlet_code))'
            )
        )
        c.execute(
            text(
                'INSERT INTO ordertransaction ("TransactionID", outlet_code, "SaleDate", "ReceiptPayPrice") VALUES '
                "(120354, 'OUTLET_001', '2026-11-17', 924715), (120354, 'OUTLET_002', '2026-11-17', 5000)"
            )
        )
        c.commit()
        try:
            yield c
        finally:
            c.rollback()
            c.execute(text(f"DROP SCHEMA IF EXISTS {SKEMA} CASCADE"))
            c.commit()
    engine.dispose()


def _jalankan_021(c):
    cur = c.connection.dbapi_connection.cursor()
    try:
        cur.execute(MIGRASI_021.read_text(encoding="utf-8"))
    finally:
        cur.close()
    c.commit()


def _kolom(c, tabel):
    return {
        r.column_name: (r.data_type, r.is_nullable)
        for r in c.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": SKEMA, "t": tabel},
        )
    }


def _header(c, kolom='"TransactionID", outlet_code, "SaleDate", "ReceiptPayPrice", payments_received_at'):
    return [tuple(r) for r in c.execute(text(f"SELECT {kolom} FROM ordertransaction ORDER BY outlet_code"))]


def test_kolom_sama_dengan_model(conn):
    _jalankan_021(conn)

    kolom = _kolom(conn, "orderpaydetail")
    tabel = SalesPayments.__table__
    assert set(kolom) == {c.name for c in tabel.c}, "kolom model dan migrasi berbeda"
    for c in tabel.c:
        assert (kolom[c.name][1] == "YES") == c.nullable, c.name
    assert kolom["Amount"][0] == "numeric"

    pk = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
                "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                f"WHERE i.indrelid = '{SKEMA}.orderpaydetail'::regclass AND i.indisprimary"
            )
        )
    ]
    assert set(pk) == {c.name for c in tabel.primary_key.columns}
    assert _kolom(conn, "ordertransaction")["payments_received_at"] == ("timestamp without time zone", "YES")


def test_transaksi_lama_tidak_berubah_dan_belum_diketahui(conn):
    sebelum = _header(conn, '"TransactionID", outlet_code, "SaleDate", "ReceiptPayPrice"')

    _jalankan_021(conn)

    assert [r[:4] for r in _header(conn)] == sebelum
    assert [r[4] for r in _header(conn)] == [None, None]


def test_fk_ke_header_outlet_yang_sama(conn):
    _jalankan_021(conn)
    sisip = (
        'INSERT INTO orderpaydetail (outlet_code, "TransactionID", "ComputerID", "PayDetailID", "PayTypeID", '
        '"Amount", received_at) VALUES (:o, :t, 793, 1, 1, 100, NOW())'
    )

    conn.execute(text(sisip), {"o": "OUTLET_001", "t": 120354})
    conn.commit()
    with pytest.raises(IntegrityError):
        conn.execute(text(sisip), {"o": "OUTLET_003", "t": 120354})
    conn.rollback()


def test_idempoten(conn):
    _jalankan_021(conn)
    conn.execute(
        text(
            'INSERT INTO orderpaydetail (outlet_code, "TransactionID", "ComputerID", "PayDetailID", "PayTypeID", '
            "\"Amount\", received_at) VALUES ('OUTLET_001', 120354, 793, 1, 1, 924715, NOW())"
        )
    )
    conn.execute(text("UPDATE ordertransaction SET payments_received_at = NOW() WHERE outlet_code = 'OUTLET_001'"))
    conn.commit()
    keadaan = (_kolom(conn, "orderpaydetail"), _header(conn), conn.execute(text("SELECT * FROM orderpaydetail")).all())

    _jalankan_021(conn)

    assert (
        _kolom(conn, "orderpaydetail"),
        _header(conn),
        conn.execute(text("SELECT * FROM orderpaydetail")).all(),
    ) == keadaan
