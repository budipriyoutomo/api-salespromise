"""Test endpoint kirim rekap closing ke API eksternal (TODO Fase 8.6).

`/api/closing-exports` — admin saja. HTTP ke API tujuan diganti tiruan.
"""

import pytest

from app.config import settings
from app.services import closing_export_client
from app.services.closing_export_client import HasilKirim
from tests.conftest import bearer
from tests.unit.test_routes_closing import item, jual, kirim_closing, petakan

URL = "/api/closing-exports"


@pytest.fixture(autouse=True)
def konfigurasi(monkeypatch):
    monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "https://api.contoh.id/closing-totals")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "token-uji")


@pytest.fixture()
def hasil_api(monkeypatch):
    """Daftar hasil berikutnya dari API tujuan; kosong = 201 sukses."""
    antrean = []

    def tiruan(payload, **opsi):
        if antrean:
            return antrean.pop(0)
        return HasilKirim(status="terkirim", http_status=201, response_body="{}", error=None, attempts=1)

    monkeypatch.setattr(closing_export_client, "kirim", tiruan)
    return antrean


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


def siapkan(db):
    kirim_closing(db, items=[item(sold=10)])
    petakan(db, "SU-001", 200104)
    jual(db, 1, 200104, 3)


def kirim(client, headers, outlet="OUTLET_001", tanggal="2026-10-02"):
    return client.post(URL, json={"outlet_code": outlet, "production_date": tanggal}, headers=headers)


GAGAL = HasilKirim(status="gagal", http_status=500, response_body="error", error="HTTP 500", attempts=3)


class TestAkses:

    @pytest.mark.parametrize(
        "method, path",
        [("get", "/status"), ("get", ""), ("post", ""), ("get", "/1"), ("post", "/1/retry")],
    )
    def test_hanya_admin(self, client, manager_headers, method, path):
        assert getattr(client, method)(URL + path).status_code == 401
        assert getattr(client, method)(URL + path, headers=manager_headers).status_code == 403


class TestKirim:

    def test_terkirim(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)

        res = kirim(client, admin_headers)

        assert res.status_code == 201, res.text
        data = res.json()["data"]
        assert (data["outlet_code"], data["production_date"], data["sequence"]) == ("OUTLET_001", "2026-10-02", 1)
        assert (data["status"], data["http_status"], data["attempts"], data["item_count"]) == ("terkirim", 201, 1, 1)
        assert data["sent_by"] == "admin@maharasa.id"
        assert data["payload"]["items"][0]["totalSold"] == 13
        assert data["response_body"] == "{}"

    def test_gagal_tetap_201_dengan_status_gagal(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)
        hasil_api.append(GAGAL)

        res = kirim(client, admin_headers)

        assert res.status_code == 201
        assert (res.json()["data"]["status"], res.json()["data"]["error"]) == ("gagal", "HTTP 500")

    def test_belum_dikonfigurasi_503(self, client, app_db, admin_headers, hasil_api, monkeypatch):
        siapkan(app_db)
        monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "")

        assert kirim(client, admin_headers).status_code == 503

    def test_tanpa_closing_404(self, client, admin_headers, hasil_api):
        assert kirim(client, admin_headers).status_code == 404

    def test_diblokir_422_dengan_alasan(self, client, app_db, admin_headers, hasil_api):
        kirim_closing(app_db, items=[item(), item("SU-002", "Tuna")])
        petakan(app_db, "SU-001", 200104)
        petakan(app_db, "SU-002", 200104)
        kirim_closing(app_db, outlet="OUTLET_001", items=[item("SU-003", "Ebi")])

        res = kirim(client, admin_headers)

        assert res.status_code == 422
        detail = res.json()["detail"]
        assert "message" in detail
        assert [m["menu_code"] for m in detail["menu_belum_dipetakan"]] == ["SU-003"]
        assert [(p["product_id"], p["menus"]) for p in detail["produk_dobel"]] == [(200104, ["SU-001", "SU-002"])]

    def test_sedang_dikirim_409(self, client, app_db, admin_headers, hasil_api):
        from app.models.closing_report import ClosingExportLog

        siapkan(app_db)
        log_id = kirim(client, admin_headers).json()["data"]["id"]
        app_db.get(ClosingExportLog, log_id).status = "mengirim"
        app_db.commit()

        assert kirim(client, admin_headers).status_code == 409

    @pytest.mark.parametrize(
        "body",
        [{}, {"outlet_code": "OUTLET_001"}, {"outlet_code": "", "production_date": "2026-10-02"}, {"outlet_code": "X", "production_date": "bukan"}],
    )
    def test_body_tidak_valid(self, client, admin_headers, hasil_api, body):
        assert client.post(URL, json=body, headers=admin_headers).status_code == 422


class TestStatus:

    def test_status_per_outlet_tanggal(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)
        kirim(client, admin_headers)

        res = client.get(f"{URL}/status", params={"start_date": "2026-10-02", "end_date": "2026-10-02"}, headers=admin_headers)

        assert res.status_code == 200, res.text
        (s,) = res.json()["data"]
        assert (s["outlet_code"], s["production_date"], s["status"], s["can_send"]) == (
            "OUTLET_001",
            "2026-10-02",
            "terkirim",
            True,
        )
        assert (s["item_count"], s["total_sold"]) == (1, 13)
        assert s["last_sent"]["status"] == "terkirim"
        assert s["menu_belum_dipetakan"] == [] and s["produk_dobel"] == []

    def test_menu_belum_dipetakan(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item()])

        (s,) = client.get(f"{URL}/status", headers=admin_headers).json()["data"]

        assert (s["status"], s["can_send"], s["last_attempt"]) == ("belum_dikirim", False, None)
        assert s["menu_belum_dipetakan"][0]["menu_name"] == "Salmon Nigiri"


class TestRiwayat:

    def test_daftar_tanpa_payload_dan_detail_dengan_payload(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)
        hasil_api.append(GAGAL)
        gagal_id = kirim(client, admin_headers).json()["data"]["id"]
        ok_id = kirim(client, admin_headers).json()["data"]["id"]

        res = client.get(URL, headers=admin_headers)
        assert res.status_code == 200
        body = res.json()
        assert [r["id"] for r in body["data"]] == [ok_id, gagal_id]
        assert "payload" not in body["data"][0]
        assert body["pagination"] == {"limit": 50, "offset": 0, "total": 2, "has_more": False}

        res = client.get(URL, params={"status": "gagal", "outlet": "OUTLET_001"}, headers=admin_headers)
        assert [r["id"] for r in res.json()["data"]] == [gagal_id]

        detail = client.get(f"{URL}/{gagal_id}", headers=admin_headers).json()["data"]
        assert detail["payload"]["sequence"] == 1
        assert detail["response_body"] == "error"

    def test_status_tidak_dikenal_ditolak(self, client, admin_headers):
        assert client.get(URL, params={"status": "selesai"}, headers=admin_headers).status_code == 422

    def test_detail_tidak_ada(self, client, admin_headers):
        assert client.get(f"{URL}/999", headers=admin_headers).status_code == 404


class TestKirimUlang:

    def test_ulang_yang_gagal(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)
        hasil_api.append(GAGAL)
        log_id = kirim(client, admin_headers).json()["data"]["id"]

        res = client.post(f"{URL}/{log_id}/retry", headers=admin_headers)

        assert res.status_code == 200, res.text
        assert (res.json()["data"]["id"], res.json()["data"]["status"], res.json()["data"]["attempts"]) == (log_id, "terkirim", 4)

    def test_yang_sudah_terkirim_409(self, client, app_db, admin_headers, hasil_api):
        siapkan(app_db)
        log_id = kirim(client, admin_headers).json()["data"]["id"]

        assert client.post(f"{URL}/{log_id}/retry", headers=admin_headers).status_code == 409

    def test_tidak_ada_404(self, client, admin_headers, hasil_api):
        assert client.post(f"{URL}/999/retry", headers=admin_headers).status_code == 404

    def test_yang_masih_berjalan_409(self, client, app_db, admin_headers, hasil_api):
        from app.models.closing_report import ClosingExportLog

        siapkan(app_db)
        hasil_api.append(GAGAL)
        log_id = kirim(client, admin_headers).json()["data"]["id"]
        app_db.get(ClosingExportLog, log_id).status = "mengirim"
        app_db.commit()

        res = client.post(f"{URL}/{log_id}/retry", headers=admin_headers)

        assert res.status_code == 409
        assert "sedang berjalan" in res.json()["detail"]

    def test_belum_dikonfigurasi_503(self, client, app_db, admin_headers, hasil_api, monkeypatch):
        siapkan(app_db)
        hasil_api.append(GAGAL)
        log_id = kirim(client, admin_headers).json()["data"]["id"]
        monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "")

        assert client.post(f"{URL}/{log_id}/retry", headers=admin_headers).status_code == 503
