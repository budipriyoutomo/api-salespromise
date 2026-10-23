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


def _tanpa_komentar(sql: str) -> str:
    return "\n".join(baris for baris in sql.splitlines() if not baris.strip().startswith("--")).upper()


@pytest.mark.parametrize("path", migrate.daftar_migrasi(), ids=lambda p: p.name)
def test_migrasi_tidak_pernah_menghapus_data(path):
    """Migrasi jalan otomatis saat container start, langsung ke database produksi.

    Menghapus data adalah keputusan manusia yang dijalankan sadar dan terpisah,
    bukan efek samping deploy. DROP CONSTRAINT / DROP INDEX tidak dilarang —
    keduanya tidak menghapus baris.
    """
    sql = _tanpa_komentar(path.read_text(encoding="utf-8-sig"))

    for terlarang in ("DELETE FROM", "TRUNCATE", "DROP TABLE", "DROP COLUMN", "DROP SCHEMA", "DROP DATABASE"):
        assert terlarang not in sql, f"{path.name} memuat {terlarang}"


def test_migrasi_006_idempoten_dan_seed_colorplate():
    """Tanpa seed, publish di produksi berhenti mengirim event colorplate begitu dideploy."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "006_product_group_mappings.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS PRODUCT_GROUP_MAPPINGS" in sql
    assert "'COLORPLATE'" in sql
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql


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

    lock = next(i for i, sql in enumerate(conn.log) if sql.startswith("SELECT pg_advisory_lock"))
    pertama = next(i for i, sql in enumerate(conn.log) if sql.startswith("-- 001"))
    assert lock < pertama


def test_migrasi_007_idempoten_tanpa_seed():
    """Tanpa seed: publish yang sudah berjalan tidak berubah sampai admin menambah menu."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "007_product_menu_mappings.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS PRODUCT_MENU_MAPPINGS" in sql
    assert "INSERT" not in sql


def test_migrasi_008_idempoten_tanpa_seed():
    """Tanpa seed: menu yang sudah ada tidak dipublish sampai admin memberi konversi warna."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "008_product_menu_colorplates.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS PRODUCT_MENU_COLORPLATES" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql
    assert "INSERT" not in sql
    assert "DROP" not in sql
    assert "DELETE" not in sql


def test_migrasi_009_hanya_membuat_tabel_brand():
    """Tanpa seed, dan tabel lama (api_keys, ordertransaction, orderdetail) tidak disentuh."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "009_brands.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS BRANDS" in sql
    assert "CREATE TABLE IF NOT EXISTS OUTLET_BRAND_MAPPINGS" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql
    for terlarang in ["INSERT", "DROP", "DELETE", "ALTER", "API_KEYS", "ORDERTRANSACTION", "ORDERDETAIL"]:
        assert terlarang not in sql, terlarang


def test_migrasi_011_hanya_membuat_tabel_closing_report():
    """Tanpa seed, tanpa ALTER, dan tabel lama tidak disentuh.

    Revisi closing report tidak menghapus item lama — setiap kiriman punya
    baris revisi + item sendiri, header cukup menunjuk revisi aktif.
    """
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "011_closing_reports.sql").read_text(encoding="utf-8"))

    for tabel in [
        "CLOSING_REPORTS",
        "CLOSING_REPORT_REVISIONS",
        "CLOSING_REPORT_ITEMS",
        "CLOSING_MENUS",
        "CLOSING_MENU_PRODUCTS",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {tabel} " in sql, tabel
    assert "CREATE UNIQUE INDEX IF NOT EXISTS UQ_CLOSING_REPORT_REVISIONS_CURRENT" in sql
    for terlarang in [
        "INSERT",
        "UPDATE ",
        "DROP",
        "DELETE",
        "ALTER",
        "API_KEYS",
        "ORDERTRANSACTION",
        "ORDERDETAIL",
        "PRODUCT_MENU_",
    ]:
        assert terlarang not in sql, terlarang


def test_migrasi_012_hanya_mengubah_tabel_closing_tanpa_hapus_data():
    """Jawaban pengirim (2026-10-05): kunci menu = menuId, menuCode/productionDate
    boleh null, dedup per messageId, compensation boleh negatif."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "012_closing_menu_id.sql").read_text(encoding="utf-8"))

    for harus in [
        "UQ_CLOSING_REPORT_REVISIONS_MESSAGE_ID",
        "UQ_CLOSING_MENUS_MENU_ID",
        "ALTER COLUMN MENU_CODE DROP NOT NULL",
        "ALTER COLUMN PRODUCTION_DATE DROP NOT NULL",
        "ADD COLUMN IF NOT EXISTS BRAND_CODE",
        "CHECK (SOLD >= 0 AND WASTE >= 0)",
        # Berhenti, bukan menghapus, kalau ada duplikat yang menghalangi constraint baru.
        "RAISE EXCEPTION",
    ]:
        assert harus in sql, harus
    for terlarang in ["INSERT", "UPDATE ", "DELETE", "TRUNCATE", "DROP TABLE", "DROP COLUMN", "API_KEYS", "ORDERTRANSACTION", "ORDERDETAIL"]:
        assert terlarang not in sql, terlarang


def test_migrasi_013_hanya_membuat_tabel_log_pesan_closing():
    """Log pesan RabbitMQ: CREATE saja, tabel lain tidak disentuh."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "013_closing_message_logs.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS CLOSING_MESSAGE_LOGS " in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql
    for terlarang in [
        "INSERT",
        "UPDATE ",
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "API_KEYS",
        "ORDERTRANSACTION",
        "ORDERDETAIL",
    ]:
        assert terlarang not in sql, terlarang


def test_migrasi_014_hanya_membuat_tabel_produk():
    """Master data product: CREATE saja, tanpa seed, tabel lama tidak disentuh."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "014_products.sql").read_text(encoding="utf-8"))

    assert "CREATE TABLE IF NOT EXISTS PRODUCTS " in sql
    assert "CREATE TABLE IF NOT EXISTS PRODUCT_POS_MAPPINGS " in sql
    assert "UNIQUE (OUTLET_CODE, POS_PRODUCT_ID)" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql
    for terlarang in [
        "INSERT",
        "UPDATE ",
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "API_KEYS",
        "ORDERTRANSACTION",
        "ORDERDETAIL",
    ]:
        assert terlarang not in sql, terlarang


def test_migrasi_015_hanya_menambah_kolom_produk():
    """Product Code & subkategori: ADD COLUMN saja, unit/price tidak dihapus."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "015_products_code_subcategory.sql").read_text(encoding="utf-8"))

    for harus in [
        "ADD COLUMN IF NOT EXISTS PRODUCT_CODE VARCHAR(50)",
        "ADD COLUMN IF NOT EXISTS SUBCATEGORY  VARCHAR(100)",
        "CK_PRODUCTS_PRODUCT_CODE_NORMAL",
        "CREATE UNIQUE INDEX IF NOT EXISTS UQ_PRODUCTS_PRODUCT_CODE",
    ]:
        assert harus in sql, harus
    for terlarang in [
        "INSERT",
        "UPDATE ",
        "DELETE",
        "TRUNCATE",
        "DROP",
        "NOT NULL",
        "API_KEYS",
        "ORDERTRANSACTION",
        "ORDERDETAIL",
    ]:
        assert terlarang not in sql, terlarang


def test_migrasi_016_hanya_membuat_tabel_log_kirim_closing():
    """Log kirim rekap closing ke API eksternal (Fase 8): CREATE saja, tabel lain tidak disentuh."""
    sql = _tanpa_komentar((migrate.MIGRATIONS_DIR / "016_closing_export_logs.sql").read_text(encoding="utf-8"))

    for harus in [
        "CREATE TABLE IF NOT EXISTS CLOSING_EXPORT_LOGS ",
        "UQ_CLOSING_EXPORT_LOGS_MESSAGE_ID",
        "UQ_CLOSING_EXPORT_LOGS_SEQUENCE",
        "CK_CLOSING_EXPORT_LOGS_STATUS",
        "CREATE INDEX IF NOT EXISTS",
    ]:
        assert harus in sql, harus
    for terlarang in [
        "INSERT",
        "UPDATE ",
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "API_KEYS",
        "ORDERTRANSACTION",
        "ORDERDETAIL",
        "CLOSING_REPORTS ",
    ]:
        assert terlarang not in sql, terlarang


def test_statement_timeout_dimatikan_sebelum_lock_dan_migrasi(folder):
    """Engine aplikasi memasang statement_timeout; migrasi (bangun index) dan
    menunggu advisory lock bisa jauh lebih lama dari itu."""
    conn = KoneksiPalsu()

    migrate.jalankan(conn, migrate.daftar_migrasi(folder))

    assert conn.log[0] == "SET statement_timeout = 0"


# ---------------------------------------------------------------------------
# File tanpa transaksi (CREATE INDEX CONCURRENTLY, migrasi 017)
# ---------------------------------------------------------------------------


class CursorTanpaTransaksi(CursorPalsu):
    def execute(self, sql, params=None):
        if sql.startswith("SELECT i.indisvalid"):
            self.db.log.append(sql)
            nama = params[0]
            self._hasil = [(False,)] if nama in self.db.invalid else ([(True,)] if nama in self.db.ada else [])
            return
        if "CONCURRENTLY" in sql:
            # Postgres menolak CONCURRENTLY di dalam blok transaksi.
            assert self.db.autocommit is True, "CONCURRENTLY dijalankan di dalam transaksi"
            self.db.ada.add(sql.split("IF NOT EXISTS")[1].split()[0])
        super().execute(sql, params)

    def fetchone(self):
        return self._hasil[0] if self._hasil else None


class KoneksiTanpaTransaksi(KoneksiPalsu):
    def __init__(self, invalid=(), **kw):
        super().__init__(**kw)
        self.autocommit = False
        self.invalid = set(invalid)
        self.ada = set()

    def cursor(self):
        return CursorTanpaTransaksi(self)


@pytest.fixture()
def folder_index(tmp_path):
    (tmp_path / "001_pertama.sql").write_text("-- 001\nSELECT 1;", encoding="utf-8")
    (tmp_path / "002_index.sql").write_text(
        "-- migrate:no-transaction\n"
        "-- komentar; dengan titik koma\n"
        'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_a ON t ("A");\n\n'
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_b\n    ON t (upper(trim(\"B\")));\n",
        encoding="utf-8",
    )
    return tmp_path


def test_file_tanpa_transaksi_dijalankan_per_statement_dalam_autocommit(folder_index):
    conn = KoneksiTanpaTransaksi()

    dijalankan = migrate.jalankan(conn, migrate.daftar_migrasi(folder_index))

    assert dijalankan == ["001_pertama.sql", "002_index.sql"]
    concurrently = [sql for sql in conn.log if "CONCURRENTLY" in sql]
    assert len(concurrently) == 2
    assert conn.ada == {"ix_a", "ix_b"}
    assert conn.tercatat == ["001_pertama.sql", "002_index.sql"]
    # Kembali ke mode transaksi biasa untuk file berikutnya.
    assert conn.autocommit is False


def test_index_invalid_sisa_kegagalan_tidak_dilewati_diam_diam(folder_index):
    """`IF NOT EXISTS` akan melewati index INVALID — padahal index itu tidak dipakai planner."""
    conn = KoneksiTanpaTransaksi(invalid={"ix_b"})

    with pytest.raises(RuntimeError, match="ix_b"):
        migrate.jalankan(conn, migrate.daftar_migrasi(folder_index))

    assert "002_index.sql" not in conn.tercatat
    assert conn.autocommit is False


def test_statement_gagal_tidak_dicatat(folder_index):
    conn = KoneksiTanpaTransaksi(gagal_pada="ix_b")

    with pytest.raises(RuntimeError):
        migrate.jalankan(conn, migrate.daftar_migrasi(folder_index))

    assert "002_index.sql" not in conn.tercatat
    assert conn.autocommit is False


def test_pecah_statement_mengabaikan_komentar():
    sql = "-- migrate:no-transaction\n-- a; b\nCREATE INDEX x ON t (a);\n\n-- c\nCREATE INDEX y ON t (b);\n"

    assert migrate.pecah_statement(sql) == ["CREATE INDEX x ON t (a)", "CREATE INDEX y ON t (b)"]


def test_migrasi_017_hanya_menambah_index_tanpa_mengunci_tabel():
    """Index orderdetail untuk query dashboard (TODO 9.1). Tidak ada baris yang disentuh."""
    path = migrate.MIGRATIONS_DIR / "017_orderdetail_report_indexes.sql"
    teks = path.read_text(encoding="utf-8")
    sql = _tanpa_komentar(teks)
    statements = migrate.pecah_statement(teks)

    assert migrate.tanpa_transaksi(teks)
    assert len(statements) == 4
    for s in statements:
        assert s.upper().startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS "), s
        assert " ON ORDERDETAIL " in s.upper().replace("\n", " ")
    for terlarang in ["INSERT", "UPDATE ", "DROP", "DELETE", "TRUNCATE", "ALTER", "UNIQUE"]:
        assert terlarang not in sql, terlarang
