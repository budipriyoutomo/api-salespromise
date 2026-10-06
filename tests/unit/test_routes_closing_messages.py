"""Test endpoint log pesan closing report dari RabbitMQ (`/api/closing-messages`).

Admin saja — payload berisi data semua outlet, termasuk pesan yang ditolak.
"""

import uuid
from datetime import date, datetime

import pytest

from app.models.closing_report import ClosingMessageLog
from tests.conftest import bearer


def catat(db, status="baru", received_at=datetime(2026, 10, 2, 5, 0), **lain):
    nilai = {
        "status": status,
        "received_at": received_at,
        "message_id": str(uuid.uuid4()),
        "outlet_code": "STTSM",
        "body_bytes": 10,
        "payload": {"messageId": "x"},
    }
    nilai.update(lain)
    log = ClosingMessageLog(**nilai)
    db.add(log)
    db.commit()
    return log


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


class TestDaftarPesan:

    def test_butuh_login(self, client):
        assert client.get("/api/closing-messages").status_code == 401

    def test_hanya_admin(self, client, manager_headers):
        assert client.get("/api/closing-messages", headers=manager_headers).status_code == 403

    def test_terbaru_dulu_tanpa_payload(self, client, app_db, admin_headers):
        lama = catat(app_db, received_at=datetime(2026, 10, 2, 1, 0))
        baru = catat(app_db, received_at=datetime(2026, 10, 2, 9, 0))

        res = client.get("/api/closing-messages", headers=admin_headers)

        assert res.status_code == 200
        data = res.json()["data"]
        assert [d["id"] for d in data] == [baru.id, lama.id]
        assert "payload" not in data[0]
        assert "body_text" not in data[0]
        assert data[0]["received_at"] == "2026-10-02T09:00:00"

    def test_filter_status_dan_jumlah_per_status(self, client, app_db, admin_headers):
        catat(app_db, status="baru")
        catat(app_db, status="duplikat")
        ditolak = catat(app_db, status="ditolak", reason="gagal validasi", errors=[{"loc": ["version"]}])

        res = client.get("/api/closing-messages", params={"status": "ditolak"}, headers=admin_headers).json()

        assert [d["id"] for d in res["data"]] == [ditolak.id]
        assert res["data"][0]["reason"] == "gagal validasi"
        assert res["pagination"]["total"] == 1
        # Jumlah per status tidak ikut tersaring status, supaya tab lain tetap terlihat.
        assert res["counts"] == {"baru": 1, "revisi": 0, "revisi_lama": 0, "duplikat": 1, "ditolak": 1}

    def test_status_tidak_dikenal_ditolak(self, client, admin_headers):
        res = client.get("/api/closing-messages", params={"status": "hilang"}, headers=admin_headers)

        assert res.status_code == 422

    def test_cari_message_id_atau_outlet(self, client, app_db, admin_headers):
        a = catat(app_db, message_id="abc-123", outlet_code="STTSM")
        b = catat(app_db, message_id="zzz", outlet_code="PIK01")

        def cari(q):
            res = client.get("/api/closing-messages", params={"q": q}, headers=admin_headers)
            return [d["id"] for d in res.json()["data"]]

        assert cari("ABC") == [a.id]
        assert cari("pik") == [b.id]

    def test_filter_tanggal_terima_dalam_wib(self, client, app_db, admin_headers):
        """02:00 WIB tanggal 3 = 19:00 UTC tanggal 2 — masuk tanggal 3."""
        dini_hari = catat(app_db, received_at=datetime(2026, 10, 2, 19, 0))
        catat(app_db, received_at=datetime(2026, 10, 2, 16, 59))  # 23:59 WIB tanggal 2
        catat(app_db, received_at=datetime(2026, 10, 3, 17, 0))  # 00:00 WIB tanggal 4

        res = client.get(
            "/api/closing-messages",
            params={"start_date": "2026-10-03", "end_date": "2026-10-03"},
            headers=admin_headers,
        ).json()

        assert [d["id"] for d in res["data"]] == [dini_hari.id]
        assert res["counts"]["baru"] == 1

    def test_paginasi(self, client, app_db, admin_headers):
        for jam in range(3):
            catat(app_db, received_at=datetime(2026, 10, 2, jam, 0))

        res = client.get("/api/closing-messages", params={"limit": 2, "offset": 2}, headers=admin_headers).json()

        assert len(res["data"]) == 1
        assert res["pagination"] == {"limit": 2, "offset": 2, "total": 3, "has_more": False}


class TestDetailPesan:

    def test_payload_dan_error(self, client, app_db, admin_headers):
        rid = uuid.uuid4()
        log = catat(
            app_db,
            status="ditolak",
            reason="gagal validasi",
            errors=[{"loc": ["version"], "msg": "Input should be 1", "type": "literal_error"}],
            warnings=None,
            payload={"version": 2},
            closing_report_id=rid,
            report_date=date(2026, 10, 2),
            item_count=3,
        )

        res = client.get(f"/api/closing-messages/{log.id}", headers=admin_headers)

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["payload"] == {"version": 2}
        assert data["errors"][0]["msg"] == "Input should be 1"
        assert data["closing_report_id"] == str(rid)
        assert data["report_date"] == "2026-10-02"
        assert data["item_count"] == 3

    def test_body_bukan_json(self, client, app_db, admin_headers):
        log = catat(app_db, status="ditolak", reason="bukan JSON", payload=None, body_text="bukan json")

        data = client.get(f"/api/closing-messages/{log.id}", headers=admin_headers).json()["data"]

        assert data["payload"] is None
        assert data["body_text"] == "bukan json"

    def test_tidak_ada_404(self, client, admin_headers):
        assert client.get("/api/closing-messages/999", headers=admin_headers).status_code == 404

    def test_hanya_admin(self, client, app_db, manager_headers):
        log = catat(app_db)

        assert client.get(f"/api/closing-messages/{log.id}", headers=manager_headers).status_code == 403
