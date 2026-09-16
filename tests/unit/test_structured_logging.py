"""Test item 3.7 — structured logging JSON + `request_id`.

Tujuannya: satu request bisa ditelusuri dari awal sampai akhir di log, dan
log bisa dibaca mesin (Loki/ELK/CloudWatch) tanpa regex rapuh.

Mencakup:
- `LOG_FORMAT` di konfigurasi
- formatter JSON dan format teks
- `request_id` di contextvar, ikut ke thread pool endpoint `def` biasa
- middleware yang menerima / membuat `X-Request-ID` dan menulis access log
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.request_context import (
    get_request_id,
    new_request_id,
    request_id_var,
    sanitize_request_id,
)
from app.core.request_logging import RequestIdMiddleware
from app.utils.logger import (
    JsonFormatter,
    RequestIdFilter,
    build_formatter,
    configure_logging,
)


def make_record(message="halo", level=logging.INFO, name="sync-api", exc_info=None, **extra):
    record = logging.LogRecord(name, level, __file__, 1, message, None, exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.fixture()
def dengan_request_id():
    """Set `request_id` untuk satu test, lalu kembalikan seperti semula."""
    tokens = []

    def _set(value):
        tokens.append(request_id_var.set(value))

    yield _set

    for token in reversed(tokens):
        request_id_var.reset(token)


# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------


class TestLogFormatConfig:

    def test_default_json(self, monkeypatch):
        monkeypatch.delenv("LOG_FORMAT", raising=False)

        assert Settings().LOG_FORMAT == "json"

    def test_dibaca_dari_env_dan_dinormalisasi(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", " TEXT ")

        assert Settings().LOG_FORMAT == "text"

    def test_default_file_log(self, monkeypatch):
        monkeypatch.delenv("LOG_FILE", raising=False)

        assert Settings().LOG_FILE == "logs/api.log"

    def test_nilai_tidak_dikenal_ditolak_validate(self, monkeypatch):
        """Salah ketik `jsn` harus gagal saat start, bukan diam-diam jatuh ke format lain."""
        monkeypatch.setenv("LOG_FORMAT", "jsn")

        with pytest.raises(ValueError, match="LOG_FORMAT"):
            Settings().validate()


# ---------------------------------------------------------------------------
# request_id
# ---------------------------------------------------------------------------


class TestRequestContext:

    def test_default_none_di_luar_request(self):
        assert get_request_id() is None

    def test_membaca_nilai_contextvar(self, dengan_request_id):
        dengan_request_id("abc123")

        assert get_request_id() == "abc123"

    def test_id_baru_32_hex_dan_unik(self):
        a, b = new_request_id(), new_request_id()

        assert len(a) == 32
        assert int(a, 16) >= 0
        assert a != b

    @pytest.mark.parametrize("nilai", ["abc-123", "a.b_c", "0f" * 16, "x" * 128])
    def test_id_dari_klien_yang_wajar_diterima(self, nilai):
        assert sanitize_request_id(nilai) == nilai

    @pytest.mark.parametrize(
        "nilai",
        [
            None,
            "",
            "x" * 129,
            "ada spasi",
            "baris\nbaru",  # log injection: memalsukan baris log berikutnya
            'kutip"ganda',
            "<script>",
        ],
    )
    def test_id_dari_klien_yang_mencurigakan_ditolak(self, nilai):
        assert sanitize_request_id(nilai) is None


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:

    def test_menghasilkan_satu_baris_json_valid(self):
        keluaran = JsonFormatter().format(make_record("pesan\nberbaris"))

        assert "\n" not in keluaran
        data = json.loads(keluaran)
        assert data["message"] == "pesan\nberbaris"

    def test_field_inti(self):
        data = json.loads(JsonFormatter().format(make_record("halo", level=logging.WARNING)))

        assert data["level"] == "WARNING"
        assert data["logger"] == "sync-api"
        assert data["message"] == "halo"
        # ISO-8601 UTC, supaya urutan antar worker/container bisa dibandingkan
        assert data["timestamp"].endswith("+00:00")

    def test_request_id_dari_contextvar(self, dengan_request_id):
        dengan_request_id("req-1")

        data = json.loads(JsonFormatter().format(make_record()))

        assert data["request_id"] == "req-1"

    def test_request_id_yang_sudah_tertempel_di_record_diutamakan(self, dengan_request_id):
        """Record bisa diformat belakangan (handler async/antrian) setelah request selesai."""
        dengan_request_id("sekarang")

        data = json.loads(JsonFormatter().format(make_record(request_id="saat-dicatat")))

        assert data["request_id"] == "saat-dicatat"

    def test_request_id_null_di_luar_request(self):
        data = json.loads(JsonFormatter().format(make_record()))

        assert data["request_id"] is None

    def test_field_extra_ikut_sebagai_key(self):
        data = json.loads(JsonFormatter().format(make_record(outlet="OUTLET_001", total=3)))

        assert data["outlet"] == "OUTLET_001"
        assert data["total"] == 3

    def test_extra_tidak_bisa_menimpa_field_inti(self):
        data = json.loads(JsonFormatter().format(make_record("asli", level="x", logger="palsu", timestamp="palsu")))

        assert data["logger"] == "sync-api"
        assert data["timestamp"] != "palsu"

    def test_nilai_yang_tidak_bisa_diserialisasi_jadi_string(self):
        from datetime import date

        data = json.loads(JsonFormatter().format(make_record(tanggal=date(2026, 1, 15), objek=object())))

        assert data["tanggal"] == "2026-01-15"
        assert isinstance(data["objek"], str)

    def test_traceback_exception_disertakan(self):
        try:
            raise RuntimeError("db mati")
        except RuntimeError:
            import sys

            record = make_record("gagal", level=logging.ERROR, exc_info=sys.exc_info())

        data = json.loads(JsonFormatter().format(record))

        assert "RuntimeError: db mati" in data["exc_info"]

    def test_atribut_bawaan_logrecord_tidak_bocor(self):
        data = json.loads(JsonFormatter().format(make_record()))

        for bawaan in ("args", "msg", "levelno", "pathname", "thread", "processName"):
            assert bawaan not in data

    def test_karakter_non_ascii_tetap_terbaca(self):
        keluaran = JsonFormatter().format(make_record("omzet naik — bagus"))

        assert "omzet naik — bagus" in keluaran


class TestTextFormat:

    def test_memuat_request_id(self, dengan_request_id):
        dengan_request_id("req-teks")
        record = make_record("halo")
        RequestIdFilter().filter(record)

        keluaran = build_formatter("text").format(record)

        assert "req-teks" in keluaran
        assert "halo" in keluaran

    def test_tanda_strip_di_luar_request(self):
        """`%(request_id)s` tidak boleh meledak untuk log di luar request (startup, CLI)."""
        record = make_record("startup")
        RequestIdFilter().filter(record)

        assert "| - |" in build_formatter("text").format(record)

    def test_build_formatter_json(self):
        assert isinstance(build_formatter("json"), JsonFormatter)


class TestRequestIdFilter:

    def test_menempelkan_request_id(self, dengan_request_id):
        dengan_request_id("req-filter")
        record = make_record()

        assert RequestIdFilter().filter(record) is True
        assert record.request_id == "req-filter"

    def test_tidak_menimpa_yang_sudah_ada(self, dengan_request_id):
        dengan_request_id("baru")
        record = make_record(request_id="lama")

        RequestIdFilter().filter(record)

        assert record.request_id == "lama"


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


@pytest.fixture()
def root_bersih():
    """Kembalikan handler & level root logger setelah test mengubahnya."""
    root = logging.getLogger()
    handler_awal = list(root.handlers)
    level_awal = root.level
    app_logger = logging.getLogger("sync-api")
    level_app_awal = app_logger.level

    yield root

    app_logger.setLevel(level_app_awal)
    for handler in list(root.handlers):
        if handler not in handler_awal:
            root.removeHandler(handler)
            handler.close()
    for handler in handler_awal:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level_awal)


class TestConfigureLogging:

    def test_menulis_json_ke_file(self, tmp_path, root_bersih, dengan_request_id):
        berkas = tmp_path / "api.log"
        configure_logging(level="INFO", fmt="json", filename=str(berkas))
        dengan_request_id("req-file")

        logging.getLogger("sync-api").info("tersimpan", extra={"outlet": "OUTLET_001"})

        baris = berkas.read_text(encoding="utf-8").strip().splitlines()
        data = json.loads(baris[-1])
        assert data["message"] == "tersimpan"
        assert data["request_id"] == "req-file"
        assert data["outlet"] == "OUTLET_001"

    def test_format_teks(self, tmp_path, root_bersih, dengan_request_id):
        berkas = tmp_path / "api.log"
        configure_logging(level="INFO", fmt="text", filename=str(berkas))
        dengan_request_id("req-teks")

        logging.getLogger("sync-api").info("halo teks")

        isi = berkas.read_text(encoding="utf-8")
        assert "req-teks" in isi
        assert "halo teks" in isi

    def test_dipanggil_dua_kali_tidak_menggandakan_baris(self, tmp_path, root_bersih):
        """Import ulang / reload tidak boleh membuat setiap log tercatat dua kali."""
        berkas = tmp_path / "api.log"
        configure_logging(level="INFO", fmt="json", filename=str(berkas))
        configure_logging(level="INFO", fmt="json", filename=str(berkas))

        logging.getLogger("sync-api").info("sekali")

        assert berkas.read_text(encoding="utf-8").count("sekali") == 1

    def test_level_dihormati(self, tmp_path, root_bersih):
        berkas = tmp_path / "api.log"
        configure_logging(level="WARNING", fmt="json", filename=str(berkas))

        logging.getLogger("sync-api").info("tidak tercatat")
        logging.getLogger("sync-api").warning("tercatat")

        isi = berkas.read_text(encoding="utf-8")
        assert "tidak tercatat" not in isi
        assert "tercatat" in isi

    def test_membuat_folder_log_kalau_belum_ada(self, tmp_path, root_bersih):
        berkas = tmp_path / "belum" / "ada" / "api.log"

        configure_logging(level="INFO", fmt="json", filename=str(berkas))
        logging.getLogger("sync-api").warning("x")

        assert berkas.exists()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@pytest.fixture()
def mini_app():
    """App kecil supaya perilaku middleware diuji tanpa DB & auth."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/sync")
    def endpoint_sync():
        # `def` biasa dijalankan FastAPI di thread pool — contextvar harus ikut.
        logging.getLogger("sync-api").warning("dari endpoint sync")
        return {"request_id": get_request_id()}

    @app.get("/async")
    async def endpoint_async():
        return {"request_id": get_request_id()}

    @app.get("/meledak")
    def meledak():
        raise RuntimeError("tidak tertangani")

    @app.get("/tidak-ditemukan")
    def tidak_ditemukan():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="x")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


def access_logs(caplog):
    return [r for r in caplog.records if getattr(r, "event", None) == "http_request"]


class TestRequestIdMiddleware:

    def test_membuat_request_id_dan_mengembalikannya_di_header(self, mini_app):
        response = mini_app.get("/async")

        rid = response.headers["X-Request-ID"]
        assert len(rid) == 32
        assert response.json()["request_id"] == rid

    def test_setiap_request_mendapat_id_berbeda(self, mini_app):
        a = mini_app.get("/async").headers["X-Request-ID"]
        b = mini_app.get("/async").headers["X-Request-ID"]

        assert a != b

    def test_memakai_id_dari_klien_yang_valid(self, mini_app):
        """BFF Next / load balancer bisa meneruskan id-nya sendiri — satu jejak lintas layanan."""
        response = mini_app.get("/async", headers={"X-Request-ID": "dari-bff-123"})

        assert response.headers["X-Request-ID"] == "dari-bff-123"
        assert response.json()["request_id"] == "dari-bff-123"

    def test_id_klien_yang_tidak_valid_diganti(self, mini_app):
        response = mini_app.get("/async", headers={"X-Request-ID": "x" * 500})

        rid = response.headers["X-Request-ID"]
        assert rid != "x" * 500
        assert len(rid) == 32

    def test_contextvar_ikut_ke_thread_pool(self, mini_app):
        response = mini_app.get("/sync")

        assert response.json()["request_id"] == response.headers["X-Request-ID"]

    def test_log_di_dalam_request_membawa_request_id(self, mini_app, caplog):
        with caplog.at_level("WARNING", logger="sync-api"):
            response = mini_app.get("/sync")

        record = next(r for r in caplog.records if r.getMessage() == "dari endpoint sync")
        assert record.request_id == response.headers["X-Request-ID"]

    def test_contextvar_dibersihkan_setelah_request(self, mini_app):
        mini_app.get("/async")

        assert get_request_id() is None

    def test_header_tetap_ada_pada_respons_error(self, mini_app):
        assert "X-Request-ID" in mini_app.get("/tidak-ditemukan").headers

    def test_access_log_satu_baris_per_request(self, mini_app, caplog):
        with caplog.at_level("INFO", logger="sync-api"):
            response = mini_app.get("/async?outlet=OUTLET_001")

        logs = access_logs(caplog)
        assert len(logs) == 1
        log = logs[0]
        assert log.method == "GET"
        assert log.path == "/async"
        assert log.status_code == 200
        assert log.duration_ms >= 0
        assert log.request_id == response.headers["X-Request-ID"]
        assert log.levelno == logging.INFO

    def test_query_string_tidak_dicatat(self, mini_app, caplog):
        """Query bisa memuat data yang tidak perlu menumpuk di log."""
        with caplog.at_level("INFO", logger="sync-api"):
            mini_app.get("/async?email=budi@maharasa.id")

        log = access_logs(caplog)[0]
        assert "budi@maharasa.id" not in JsonFormatter().format(log)

    def test_status_4xx_tercatat_warning(self, mini_app, caplog):
        with caplog.at_level("INFO", logger="sync-api"):
            mini_app.get("/tidak-ditemukan")

        log = access_logs(caplog)[0]
        assert log.status_code == 404
        assert log.levelno == logging.WARNING

    def test_exception_tak_tertangani_tercatat_500_dengan_traceback(self, mini_app, caplog):
        with caplog.at_level("INFO", logger="sync-api"):
            response = mini_app.get("/meledak")

        assert response.status_code == 500
        log = access_logs(caplog)[0]
        assert log.status_code == 500
        assert log.levelno == logging.ERROR
        assert log.exc_info is not None

    def test_health_probe_tidak_membanjiri_access_log(self, mini_app, caplog):
        """Orchestrator memanggil /health tiap beberapa detik."""
        with caplog.at_level("INFO", logger="sync-api"):
            response = mini_app.get("/health")

        assert access_logs(caplog) == []
        assert "X-Request-ID" in response.headers


class TestTerpasangDiAplikasi:

    def test_middleware_terpasang(self):
        from app.main import app

        assert any(m.cls is RequestIdMiddleware for m in app.user_middleware)

    def test_middleware_paling_luar(self):
        """Paling luar supaya waktu yang diukur mencakup GZip/CORS, dan id sudah ada sebelum apa pun mencatat log."""
        from app.main import app

        # Starlette: middleware yang ditambahkan terakhir berada di urutan pertama (paling luar).
        assert app.user_middleware[0].cls is RequestIdMiddleware

    def test_header_ada_di_endpoint_sungguhan(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

    def test_login_gagal_tercatat_dengan_request_id(self, client, caplog):
        from app.routes.auth_routes import login_limiter

        # Limiter hidup di memori proses — jangan sampai sisa test lain membuat ini 429.
        login_limiter.reset("testclient")

        with caplog.at_level("WARNING", logger="sync-api"):
            response = client.post(
                "/api/auth/login",
                json={"email": "tidak-ada@maharasa.id", "password": "salah12345"},
                headers={"X-Request-ID": "jejak-login-1"},
            )

        assert response.headers["X-Request-ID"] == "jejak-login-1"
        record = next(r for r in caplog.records if "LOGIN GAGAL" in r.getMessage())
        assert record.request_id == "jejak-login-1"
