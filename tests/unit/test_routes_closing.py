"""Test endpoint closing report (TODO Fase 7.6).

- `/api/closing-menus`    admin: mapping menuCode → ProductID × pengali
- `/api/closing-reports`  user dashboard, ter-scope per outlet: daftar,
                          detail, dan perbandingan closing vs POS
"""

import copy
import uuid
from datetime import date

import pytest

from app.models.closing_report import ClosingMenu, ClosingMenuProduct
from app.schemas.closing_report_event import ClosingReportSubmitted
from app.services.closing_report_service import simpan_closing_report
from tests.conftest import bearer, make_item_row, make_sale_row

HARI_INI = date(2026, 10, 2)
KEMARIN = date(2026, 10, 1)


def item(menu_code="SU-001", menu_name="Salmon Nigiri", production_date=HARI_INI, sold=42, **lain):
    nilai = {
        "menuId": str(uuid.uuid5(uuid.NAMESPACE_URL, menu_code)),
        "menuCode": menu_code,
        "menuName": menu_name,
        "productionDate": production_date.isoformat() if production_date else None,
        "sold": sold,
        "waste": 3,
        "adjustment": 0,
        "compensation": 0,
    }
    nilai.update(lain)
    return nilai


def kirim_closing(
    db,
    outlet="OUTLET_001",
    items=None,
    report_id=None,
    sent_at="2026-10-02T22:15:00+07:00",
    tanggal=HARI_INI,
    message_id=None,
):
    report_id = report_id or str(uuid.uuid4())
    raw = {
        "event": "closingreport.submitted",
        "version": 1,
        "messageId": message_id or report_id,
        "sentAt": sent_at,
        "data": {
            "closingReportId": report_id,
            "date": tanggal.isoformat(),
            "outlet": {"code": outlet, "name": f"Outlet {outlet}"},
            "brand": {"code": "MHR", "name": "Maharasa"},
            "items": items or [item()],
        },
    }
    simpan_closing_report(db, ClosingReportSubmitted.model_validate(raw), copy.deepcopy(raw))
    return report_id


def jual(db, transaction_id, product_id, qty, outlet="OUTLET_001", sale_date=HARI_INI, deleted=0, nama="Salmon HR"):
    db.add(make_sale_row(transaction_id=transaction_id, outlet_code=outlet, sale_date=sale_date, deleted=deleted))
    db.add(
        make_item_row(
            order_detail_id=1,
            transaction_id=transaction_id,
            outlet_code=outlet,
            sale_date=sale_date,
            product_id=product_id,
            product_group="FOOD",
            product_name=nama,
            qty=qty,
        )
    )
    db.commit()


def petakan(db, menu_code, product_id, multiplier=1, is_active=True):
    menu = db.query(ClosingMenu).filter_by(menu_code=menu_code).one()
    db.add(ClosingMenuProduct(closing_menu_id=menu.id, product_id=product_id, multiplier=multiplier, is_active=is_active))
    db.commit()
    return menu


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    return bearer(token_for(make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")))


# ---------------------------------------------------------------------------
# /api/closing-menus (admin)
# ---------------------------------------------------------------------------


class TestDaftarMenu:

    def test_hanya_admin(self, client, manager_headers):
        assert client.get("/api/closing-menus").status_code == 401
        assert client.get("/api/closing-menus", headers=manager_headers).status_code == 403

    def test_menu_dari_pesan_tampil_belum_dipetakan(self, client, app_db, admin_headers):
        kirim_closing(app_db)

        res = client.get("/api/closing-menus", headers=admin_headers)

        assert res.status_code == 200
        [menu] = res.json()["data"]
        assert (menu["menu_code"], menu["menu_name"], menu["is_mapped"], menu["products"]) == (
            "SU-001",
            "Salmon Nigiri",
            False,
            [],
        )

    def test_filter_status_dan_cari(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(), item("SU-002", "Tuna Nigiri"), item("DR-001", "Ocha")])
        petakan(app_db, "SU-001", 200104)
        petakan(app_db, "DR-001", 300001, is_active=False)  # mapping nonaktif = belum dipetakan

        def kode(**params):
            res = client.get("/api/closing-menus", params=params, headers=admin_headers)
            return [m["menu_code"] for m in res.json()["data"]]

        assert kode() == ["DR-001", "SU-001", "SU-002"]
        assert kode(status="mapped") == ["SU-001"]
        assert kode(status="unmapped") == ["DR-001", "SU-002"]
        assert kode(q="nigiri") == ["SU-001", "SU-002"]
        assert kode(q="dr-0") == ["DR-001"]

    def test_status_tidak_dikenal_ditolak(self, client, admin_headers):
        assert client.get("/api/closing-menus", params={"status": "x"}, headers=admin_headers).status_code == 422


class TestMappingMenu:

    @pytest.fixture()
    def menu_id(self, app_db):
        kirim_closing(app_db)
        jual(app_db, 1, 200104, 2, nama=" Salmon HR ")
        return app_db.query(ClosingMenu).one().id

    def test_tambah_product_nama_dari_data_penjualan(self, client, menu_id, admin_headers):
        res = client.post(
            f"/api/closing-menus/{menu_id}/products", json={"product_id": 200104, "multiplier": 2}, headers=admin_headers
        )

        assert res.status_code == 201
        data = res.json()["data"]
        assert (data["product_id"], data["product_name"], data["multiplier"], data["is_active"]) == (
            200104,
            "Salmon HR",
            2,
            True,
        )
        menu = client.get("/api/closing-menus", headers=admin_headers).json()["data"][0]
        assert menu["is_mapped"] is True

    def test_product_tidak_ada_di_penjualan_ditolak(self, client, menu_id, admin_headers):
        res = client.post(f"/api/closing-menus/{menu_id}/products", json={"product_id": 999}, headers=admin_headers)

        assert res.status_code == 422

    def test_product_yang_sama_dua_kali_ditolak(self, client, menu_id, admin_headers):
        url = f"/api/closing-menus/{menu_id}/products"
        client.post(url, json={"product_id": 200104}, headers=admin_headers)

        assert client.post(url, json={"product_id": 200104}, headers=admin_headers).status_code == 409

    def test_menu_tidak_ada(self, client, menu_id, admin_headers):
        res = client.post("/api/closing-menus/999/products", json={"product_id": 200104}, headers=admin_headers)

        assert res.status_code == 404

    @pytest.mark.parametrize("body", [{"product_id": 0}, {"product_id": 200104, "multiplier": 0}, {}])
    def test_body_tidak_valid(self, client, menu_id, admin_headers, body):
        res = client.post(f"/api/closing-menus/{menu_id}/products", json=body, headers=admin_headers)

        assert res.status_code == 422

    def test_hanya_admin(self, client, menu_id, manager_headers):
        res = client.post(f"/api/closing-menus/{menu_id}/products", json={"product_id": 200104}, headers=manager_headers)

        assert res.status_code == 403

    def test_ubah_pengali_dan_nonaktifkan(self, client, menu_id, admin_headers):
        dibuat = client.post(
            f"/api/closing-menus/{menu_id}/products", json={"product_id": 200104}, headers=admin_headers
        ).json()["data"]
        url = f"/api/closing-menus/{menu_id}/products/{dibuat['id']}"

        res = client.patch(url, json={"multiplier": 3}, headers=admin_headers)
        assert (res.status_code, res.json()["data"]["multiplier"]) == (200, 3)

        res = client.patch(url, json={"is_active": False}, headers=admin_headers)
        assert res.json()["data"]["is_active"] is False
        assert res.json()["data"]["multiplier"] == 3
        assert res.json()["data"]["updated_at"] is not None

    def test_ubah_mapping_milik_menu_lain_404(self, client, app_db, menu_id, admin_headers):
        dibuat = client.post(
            f"/api/closing-menus/{menu_id}/products", json={"product_id": 200104}, headers=admin_headers
        ).json()["data"]

        res = client.patch(f"/api/closing-menus/{menu_id + 1}/products/{dibuat['id']}", json={"is_active": False}, headers=admin_headers)

        assert res.status_code == 404

    def test_ubah_tanpa_field_ditolak(self, client, menu_id, admin_headers):
        dibuat = client.post(
            f"/api/closing-menus/{menu_id}/products", json={"product_id": 200104}, headers=admin_headers
        ).json()["data"]

        res = client.patch(f"/api/closing-menus/{menu_id}/products/{dibuat['id']}", json={}, headers=admin_headers)

        assert res.status_code == 422


# ---------------------------------------------------------------------------
# /api/closing-reports (user, ter-scope outlet)
# ---------------------------------------------------------------------------


class TestDaftarLaporan:

    def test_butuh_login(self, client):
        assert client.get("/api/closing-reports").status_code == 401

    def test_user_outlet_hanya_melihat_outletnya(self, client, app_db, outlet_headers, admin_headers):
        kirim_closing(app_db, outlet="OUTLET_001")
        kirim_closing(app_db, outlet="OUTLET_002")

        milik_outlet = client.get("/api/closing-reports", headers=outlet_headers).json()
        semua = client.get("/api/closing-reports", headers=admin_headers).json()

        assert [r["outlet_code"] for r in milik_outlet["data"]] == ["OUTLET_001"]
        assert milik_outlet["pagination"]["total"] == 1
        assert sorted(r["outlet_code"] for r in semua["data"]) == ["OUTLET_001", "OUTLET_002"]

    def test_user_outlet_minta_outlet_lain_403(self, client, outlet_headers):
        res = client.get("/api/closing-reports", params={"outlet": "OUTLET_002"}, headers=outlet_headers)

        assert res.status_code == 403

    def test_filter_tanggal_dan_ringkasan_revisi(self, client, app_db, admin_headers):
        rid = kirim_closing(app_db, tanggal=HARI_INI)
        kirim_closing(
            app_db, report_id=rid, tanggal=HARI_INI, sent_at="2026-10-02T23:00:00+07:00", message_id="kiriman-2"
        )
        kirim_closing(app_db, tanggal=KEMARIN)

        res = client.get(
            "/api/closing-reports", params={"start_date": "2026-10-02", "end_date": "2026-10-02"}, headers=admin_headers
        )

        [laporan] = res.json()["data"]
        assert laporan["closing_report_id"] == rid
        assert laporan["revision_count"] == 2
        assert laporan["item_count"] == 1
        assert laporan["sent_at"] == "2026-10-02T16:00:00"


class TestDetailLaporan:

    def test_item_revisi_aktif_dan_riwayat(self, client, app_db, admin_headers):
        rid = kirim_closing(app_db, items=[item(sold=10)])
        kirim_closing(
            app_db, report_id=rid, items=[item(sold=12)], sent_at="2026-10-02T23:00:00+07:00", message_id="kiriman-2"
        )

        res = client.get(f"/api/closing-reports/{rid}", headers=admin_headers)

        assert res.status_code == 200
        data = res.json()["data"]
        assert [i["sold"] for i in data["items"]] == [12]
        assert [r["is_current"] for r in data["revisions"]] == [True, False]
        assert "raw_payload" not in data["revisions"][0]

    def test_item_tanpa_kode_dan_tanggal_produksi_tidak_error(self, client, app_db, admin_headers):
        """menuCode / productionDate boleh null (migrasi 012) — urutan tidak boleh 500."""
        rid = kirim_closing(
            app_db,
            items=[
                item(menu_code="SU-002", menu_name="Tuna", production_date=None),
                item(menu_code="SU-001", menu_name="Salmon", menuCode=None),
                item(menu_code="SU-003", menu_name="Ebi"),
            ],
        )

        res = client.get(f"/api/closing-reports/{rid}", headers=admin_headers)

        assert res.status_code == 200
        assert [i["menu_name"] for i in res.json()["data"]["items"]] == ["Tuna", "Ebi", "Salmon"]

    def test_outlet_lain_404(self, client, app_db, outlet_headers):
        rid = kirim_closing(app_db, outlet="OUTLET_002")

        assert client.get(f"/api/closing-reports/{rid}", headers=outlet_headers).status_code == 404

    def test_tidak_ada_404(self, client, admin_headers):
        assert client.get(f"/api/closing-reports/{uuid.uuid4()}", headers=admin_headers).status_code == 404


class TestPerbandingan:
    """Per ProductID POS (diputuskan 2026-10-05): menu yang dipetakan ke produk
    yang sama dijumlah, lalu dibandingkan dengan qty POS produk itu.

        closing(produk) = Σ (sold + adjustment + compensation) × pengali
        selisih         = qty POS − closing(produk)        (rumus pengirim)
    """

    URL = "/api/closing-reports/comparison"

    def _baris(self, client, headers, **params):
        res = client.get(self.URL, params=params, headers=headers)
        assert res.status_code == 200, res.text
        return res.json()["data"]

    def _produk(self, client, headers, product_id, outlet="OUTLET_001", tanggal="2026-10-02", **params):
        cocok = [
            b
            for b in self._baris(client, headers, **params)
            if b["product_id"] == product_id and b["outlet_code"] == outlet and b["production_date"] == tanggal
        ]
        assert len(cocok) == 1, cocok
        return cocok[0]

    def test_menu_dengan_produk_sama_dijumlah(self, client, app_db, admin_headers):
        """Contoh piring: Salmon & Tuna sama-sama piring RED."""
        kirim_closing(app_db, items=[item(sold=5), item("SU-002", "Tuna Nigiri", sold=3)])
        petakan(app_db, "SU-001", 200104)
        petakan(app_db, "SU-002", 200104)
        jual(app_db, 1, 200104, 8, nama="RED")

        baris = self._produk(client, admin_headers, 200104)

        assert baris["product_name"] == "RED"
        assert sorted(m["menu_code"] for m in baris["menus"]) == ["SU-001", "SU-002"]
        assert (baris["closing_qty"], baris["pos_qty"], baris["selisih"], baris["status"]) == (8, 8, 0, "cocok")

    def test_rumus_pengirim_sold_adjustment_compensation(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(sold=5, adjustment=-1, compensation=2)])
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 4)

        baris = self._produk(client, admin_headers, 200104)

        # closing = 5 − 1 + 2 = 6; selisih = POS − closing = 4 − 6
        assert (baris["closing_qty"], baris["pos_qty"], baris["selisih"], baris["status"]) == (6, 4, -2, "selisih")
        [menu] = baris["menus"]
        assert (menu["sold"], menu["adjustment"], menu["compensation"], menu["multiplier"]) == (5, -1, 2, 1)

    def test_pengali_unit_pos_per_porsi(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(sold=3)])
        petakan(app_db, "SU-001", 200104, multiplier=2)
        jual(app_db, 1, 200104, 6)

        baris = self._produk(client, admin_headers, 200104)

        assert (baris["closing_qty"], baris["status"]) == (6, "cocok")

    def test_satu_menu_ke_dua_produk_jadi_dua_baris(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(sold=3)])
        petakan(app_db, "SU-001", 200104)
        petakan(app_db, "SU-001", 200999)
        jual(app_db, 1, 200104, 3)
        jual(app_db, 2, 200999, 1)

        assert self._produk(client, admin_headers, 200104)["status"] == "cocok"
        assert self._produk(client, admin_headers, 200999)["selisih"] == -2

    def test_menu_belum_dipetakan_jadi_baris_sendiri(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(sold=5, adjustment=1)])

        [baris] = self._baris(client, admin_headers)

        assert baris["product_id"] is None
        assert [m["menu_code"] for m in baris["menus"]] == ["SU-001"]
        assert (baris["closing_qty"], baris["pos_qty"], baris["selisih"], baris["status"]) == (
            6,
            None,
            None,
            "belum_dipetakan",
        )

    def test_mapping_nonaktif_diabaikan(self, client, app_db, admin_headers):
        kirim_closing(app_db)
        petakan(app_db, "SU-001", 200104, is_active=False)
        jual(app_db, 1, 200104, 3)

        [baris] = self._baris(client, admin_headers)
        assert baris["status"] == "belum_dipetakan"

    def test_terjual_di_pos_tapi_tidak_ada_di_closing(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item("SU-002", "Tuna")])
        kirim_closing(app_db, outlet="OUTLET_009", items=[item()])  # SU-001 dikenal dari outlet lain
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 4)

        baris = self._produk(client, admin_headers, 200104)

        assert (baris["closing_qty"], baris["pos_qty"], baris["selisih"], baris["status"]) == (
            None,
            4,
            None,
            "tidak_ada_di_closing",
        )
        assert baris["product_name"] == "Salmon HR"
        assert baris["menus"] == []

    def test_outlet_tanggal_tanpa_closing_tidak_ditampilkan(self, client, app_db, admin_headers):
        """Outlet yang belum memakai sistem closing tidak membanjiri laporan."""
        kirim_closing(app_db)
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 4, outlet="OUTLET_002")
        jual(app_db, 2, 200104, 4, sale_date=KEMARIN)

        baris = self._baris(client, admin_headers)

        assert [(b["outlet_code"], b["production_date"]) for b in baris] == [("OUTLET_001", "2026-10-02")]

    def test_dibandingkan_per_tanggal_produksi(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(sold=2, production_date=KEMARIN), item(sold=5)])
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 2, sale_date=KEMARIN)
        jual(app_db, 2, 200104, 5)

        assert self._produk(client, admin_headers, 200104, tanggal="2026-10-01")["status"] == "cocok"
        assert self._produk(client, admin_headers, 200104, tanggal="2026-10-02")["status"] == "cocok"

    def test_tanggal_produksi_kosong_memakai_tanggal_closing(self, client, app_db, admin_headers):
        """Jawaban pengirim: productionDate null = menu tanpa baris produksi hari itu."""
        kirim_closing(app_db, items=[item(sold=4, production_date=None)])
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 4)

        assert self._produk(client, admin_headers, 200104)["status"] == "cocok"

    def test_hanya_revisi_aktif(self, client, app_db, admin_headers):
        rid = kirim_closing(app_db, items=[item(sold=99)])
        kirim_closing(
            app_db, report_id=rid, items=[item(sold=5)], sent_at="2026-10-02T23:00:00+07:00", message_id="kiriman-2"
        )

        [baris] = self._baris(client, admin_headers)
        assert baris["closing_qty"] == 5

    def test_transaksi_terhapus_tidak_dihitung_kecuali_diminta(self, client, app_db, admin_headers):
        """Sama dengan laporan dashboard lain: `include_deleted` default false."""
        kirim_closing(app_db)
        petakan(app_db, "SU-001", 200104)
        jual(app_db, 1, 200104, 3)
        jual(app_db, 2, 200104, 10, deleted=1)

        assert self._produk(client, admin_headers, 200104)["pos_qty"] == 3
        assert self._produk(client, admin_headers, 200104, include_deleted="true")["pos_qty"] == 13

    def test_filter_tanggal_produksi(self, client, app_db, admin_headers):
        kirim_closing(app_db, items=[item(production_date=KEMARIN), item()])

        baris = self._baris(client, admin_headers, start_date="2026-10-02", end_date="2026-10-02")

        assert [b["production_date"] for b in baris] == ["2026-10-02"]

    def test_scope_outlet(self, client, app_db, outlet_headers):
        kirim_closing(app_db, outlet="OUTLET_001")
        kirim_closing(app_db, outlet="OUTLET_002")

        assert {b["outlet_code"] for b in self._baris(client, outlet_headers)} == {"OUTLET_001"}
        assert client.get(self.URL, params={"outlet": "OUTLET_002"}, headers=outlet_headers).status_code == 403
