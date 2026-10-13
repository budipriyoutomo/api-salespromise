"""Test integrasi kirim rekap closing (TODO Fase 8.7) terhadap PostgreSQL sungguhan.

Dilewati kalau `TEST_DATABASE_URL` tidak diset, dan **menolak jalan** kalau
database-nya bukan `sync_test` — modul ini menjalankan `drop_all` dan
`TRUNCATE`. Lihat tests/README.md.

Yang hanya bisa diuji di sini:
- migrasi 016 dijalankan sungguhan dan skemanya sama dengan model
  (kolom, tipe, nullable, nama constraint & index);
- qty POS dari kolom NUMERIC dibaca sebagai Decimal lalu tersimpan di JSONB;
- pelanggaran unique `sequence` di Postgres → `SedangDikirim`, dan session
  tetap bisa dipakai sesudahnya.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.closing_report import ClosingExportLog
from app.services import closing_export_client, closing_export_service
from app.services.closing_export_client import HasilKirim
from tests.unit.test_routes_closing import HARI_INI, item, jual, kirim_closing, petakan

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRASI_016 = Path(__file__).resolve().parents[2] / "migrations" / "016_closing_export_logs.sql"
SKEMA_MIGRASI = "uji_migrasi_016"
TABEL = "closing_export_logs"
ADMIN = "admin@maharasa.id"

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

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SKEMA_MIGRASI} CASCADE"))
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


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "https://api.contoh.id/closing-totals")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "token-uji")
    panggilan = []

    def tiruan(payload, **opsi):
        panggilan.append(payload)
        return HasilKirim(status="terkirim", http_status=201, response_body="{}", error=None, attempts=1)

    monkeypatch.setattr(closing_export_client, "kirim", tiruan)
    return panggilan


def siapkan(db):
    kirim_closing(db, items=[item(sold=10)])
    petakan(db, "SU-001", 200104)
    jual(db, 1, 200104, 3)


# ---------------------------------------------------------------------------
# Migrasi 016 vs model
# ---------------------------------------------------------------------------


def _jalankan_migrasi(conn):
    conn.execute(text(f"SET LOCAL search_path TO {SKEMA_MIGRASI}"))
    conn.exec_driver_sql(MIGRASI_016.read_text(encoding="utf-8"))


def _kolom(conn, skema):
    return {
        r.column_name: (r.data_type, r.character_maximum_length, r.is_nullable)
        for r in conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": skema, "t": TABEL},
        )
    }


def _constraint(conn, skema):
    return {
        (r.conname, r.contype)
        for r in conn.execute(
            text(
                "SELECT c.conname, c.contype FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = :s AND t.relname = :t"
            ),
            {"s": skema, "t": TABEL},
        )
    }


def _index(conn, skema):
    return {
        r.indexname
        for r in conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :t"),
            {"s": skema, "t": TABEL},
        )
    }


class TestMigrasi016:

    @pytest.fixture(autouse=True)
    def skema_migrasi(self, engine):
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SKEMA_MIGRASI} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {SKEMA_MIGRASI}"))
            _jalankan_migrasi(conn)

    def test_kolom_sama_dengan_model(self, engine):
        with engine.connect() as conn:
            assert _kolom(conn, SKEMA_MIGRASI) == _kolom(conn, "public")

    def test_constraint_dan_index_sama_dengan_model(self, engine):
        with engine.connect() as conn:
            assert _constraint(conn, SKEMA_MIGRASI) == _constraint(conn, "public")
            assert _index(conn, SKEMA_MIGRASI) == _index(conn, "public")

    def test_idempoten(self, engine):
        with engine.begin() as conn:
            _jalankan_migrasi(conn)

    def test_constraint_berlaku(self, engine):
        with engine.connect() as conn:
            conn.execute(text(f"SET search_path TO {SKEMA_MIGRASI}"))
            sisip = text(
                f"INSERT INTO {TABEL} (outlet_code, production_date, sequence, message_id, content_hash, "
                "item_count, payload, status, sent_by) VALUES ('STTSM', '2026-10-02', :seq, "
                "gen_random_uuid(), :hash, 1, '{}', :status, 'admin')"
            )
            conn.execute(sisip, {"seq": 1, "hash": "a" * 64, "status": "terkirim"})
            for nilai, constraint in [
                ({"seq": 1, "hash": "b" * 64, "status": "gagal"}, "uq_closing_export_logs_sequence"),
                ({"seq": 2, "hash": "b" * 64, "status": "selesai"}, "ck_closing_export_logs_status"),
                ({"seq": 0, "hash": "b" * 64, "status": "gagal"}, "ck_closing_export_logs_sequence"),
            ]:
                with pytest.raises(Exception, match=constraint):
                    with conn.begin_nested():
                        conn.execute(sisip, nilai)
            conn.rollback()


# ---------------------------------------------------------------------------
# Service di Postgres
# ---------------------------------------------------------------------------


class TestKirimDiPostgres:

    def test_payload_tersimpan_di_jsonb_dan_qty_numeric_jadi_angka(self, pg, api):
        kirim_closing(pg, items=[item(sold=10), item("SU-002", "Tuna", sold=1)])
        petakan(pg, "SU-001", 200104)
        petakan(pg, "SU-002", 200105)
        jual(pg, 1, 200104, 3)
        jual(pg, 2, 200105, 1.5, nama="Tuna HR")

        log = closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)

        pg.expire_all()
        tersimpan = pg.get(ClosingExportLog, log.id)
        assert tersimpan.payload == api[0]
        qty = {i["menuCode"]: (i["posQty"], i["totalSold"]) for i in tersimpan.payload["items"]}
        assert qty == {"SU-001": (3, 13), "SU-002": (1.5, 2.5)}
        assert type(qty["SU-001"][0]) is int
        jenis = pg.execute(
            text("SELECT jsonb_typeof(payload->'items'->0->'posQty') FROM closing_export_logs")
        ).scalar()
        assert jenis == "number"

    def test_status_perlu_kirim_ulang_setelah_penjualan_berubah(self, pg, api):
        siapkan(pg)
        closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)
        (s,) = closing_export_service.status_pasangan(pg)
        assert s.status == "terkirim"

        jual(pg, 2, 200104, 1)

        (s,) = closing_export_service.status_pasangan(pg)
        assert s.status == "perlu_kirim_ulang"

    def test_sequence_bentrok_jadi_sedang_dikirim_dan_session_tetap_hidup(self, pg, api, monkeypatch):
        siapkan(pg)
        closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)
        # Meniru dua admin menekan kirim bersamaan: keduanya mengira sequence 1.
        asli = closing_export_service._log_terakhir
        monkeypatch.setattr(closing_export_service, "_log_terakhir", lambda *a: None)

        with pytest.raises(closing_export_service.SedangDikirim):
            closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)

        monkeypatch.setattr(closing_export_service, "_log_terakhir", asli)
        assert pg.query(ClosingExportLog).count() == 1
        berikutnya = closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)
        assert berikutnya.sequence == 2

    def test_kirim_ulang_memakai_baris_dan_message_id_yang_sama(self, pg, api, monkeypatch):
        siapkan(pg)
        monkeypatch.setattr(
            closing_export_client,
            "kirim",
            lambda payload, **o: HasilKirim(
                status="gagal", http_status=503, response_body="x", error="HTTP 503", attempts=3
            ),
        )
        gagal = closing_export_service.kirim(pg, "OUTLET_001", HARI_INI, ADMIN)
        monkeypatch.setattr(
            closing_export_client,
            "kirim",
            lambda payload, **o: HasilKirim(status="terkirim", http_status=201, response_body=None, error=None, attempts=1),
        )

        hasil = closing_export_service.kirim_ulang(pg, gagal.id)

        assert (hasil.id, hasil.message_id, hasil.status, hasil.attempts) == (gagal.id, gagal.message_id, "terkirim", 4)
        assert pg.query(ClosingExportLog).count() == 1
