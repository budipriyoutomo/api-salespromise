"""Runner migrasi: pemilihan file dan urutan eksekusi, dengan koneksi palsu."""

import pytest

import migrate


class CursorPalsu:
    def __init__(self, db):
        self.db = db
        self._hasil = []

    def execute(self, sql, params=None):
        if self.db.gagal_pada and self.db.gagal_pada in sql:
            raise RuntimeError("sql error")

        self.db.log.append(sql)
        if sql.startswith("SELECT filename FROM schema_migrations"):
            self._hasil = [(n,) for n in self.db.tercatat]
        elif sql.startswith("INSERT INTO schema_migrations"):
            self.db.pending.append(params[0])

    def fetchall(self):
        return self._hasil

    def close(self):
        pass


class KoneksiPalsu:
    def __init__(self, tercatat=(), gagal_pada=None):
        self.tercatat = list(tercatat)
        self.gagal_pada = gagal_pada
        self.log = []
        self.pending = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return CursorPalsu(self)

    def commit(self):
        self.commits += 1
        self.tercatat.extend(self.pending)
        self.pending = []

    def rollback(self):
        self.rollbacks += 1
        self.pending = []


@pytest.fixture()
def folder(tmp_path):
    (tmp_path / "002_kedua.sql").write_text("-- 002\nSELECT 2;", encoding="utf-8")
    (tmp_path / "001_pertama.sql").write_text("-- 001\nSELECT 1;", encoding="utf-8")
    (tmp_path / "003_ketiga.sql").write_text("-- 003\nSELECT 3;", encoding="utf-8")
    # Bukan migrasi: dump MySQL lama dan query diagnosis.
    (tmp_path / "orderdetail.sql").write_text("DROP TABLE IF EXISTS `orderdetail`;", encoding="utf-8")
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks" / "004_cek.sql").write_text("SELECT 4;", encoding="utf-8")
    return tmp_path


def test_daftar_migrasi_hanya_file_bernomor_dan_terurut(folder):
    assert [p.name for p in migrate.daftar_migrasi(folder)] == [
        "001_pertama.sql",
        "002_kedua.sql",
        "003_ketiga.sql",
    ]


def test_folder_asli_tidak_memuat_dump_mysql_lama():
    nama = [p.name for p in migrate.daftar_migrasi()]
    assert nama, "folder migrations/ kosong?"
    assert "orderdetail.sql" not in nama
    assert "ordertransaction.sql" not in nama


def test_jalankan_melewati_yang_sudah_tercatat(folder):
    conn = KoneksiPalsu(tercatat=["001_pertama.sql"])

    dijalankan = migrate.jalankan(conn, migrate.daftar_migrasi(folder))

    assert dijalankan == ["002_kedua.sql", "003_ketiga.sql"]
    assert conn.tercatat == ["001_pertama.sql", "002_kedua.sql", "003_ketiga.sql"]
    assert not any("-- 001" in sql for sql in conn.log)


def test_jalankan_ulang_tidak_melakukan_apa_pun(folder):
    conn = KoneksiPalsu()
    files = migrate.daftar_migrasi(folder)

    migrate.jalankan(conn, files)
    assert migrate.jalankan(conn, files) == []


def test_gagal_di_tengah_rollback_dan_berhenti(folder):
    conn = KoneksiPalsu(gagal_pada="-- 002")

    with pytest.raises(RuntimeError):
        migrate.jalankan(conn, migrate.daftar_migrasi(folder))

    assert conn.tercatat == ["001_pertama.sql"]
    assert conn.rollbacks == 1
    assert not any("-- 003" in sql for sql in conn.log)


def test_advisory_lock_diambil_sebelum_migrasi(folder):
    conn = KoneksiPalsu()

    migrate.jalankan(conn, migrate.daftar_migrasi(folder))

    assert conn.log[0].startswith("SELECT pg_advisory_lock")
