"""Test endpoint laporan untuk dashboard frontend (Fase 2).

Berbeda dari test route lain, di sini service TIDAK di-mock: datanya di-seed ke
`app_db` dan query sungguhan yang dijalankan. Untuk endpoint agregat, bentuk
angkanya justru bagian yang paling perlu dijaga.
"""

from datetime import date

import pytest

from tests.conftest import bearer


@pytest.fixture()
def seeded(app_db, sale_factory, item_factory):
    app_db.add_all(
        [
            sale_factory(
                transaction_id=1,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 10),
                receipt_pay_price=100000,
                receipt_total_amount=2,
                receipt_discount=10000,
            ),
            sale_factory(
                transaction_id=2,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=200000,
                receipt_total_amount=17,
            ),
            sale_factory(
                transaction_id=3,
                outlet_code="OUTLET_002",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=300000,
                receipt_total_amount=1,
            ),
            sale_factory(
                transaction_id=4,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=999000,
                receipt_total_amount=500,
                deleted=1,
            ),
        ]
    )
    app_db.add_all(
        [
            item_factory(order_detail_id=1, transaction_id=1, product_id=101, product_name="RED", qty=2),
            item_factory(order_detail_id=1, transaction_id=2, product_id=102, product_name="BLUE", qty=10),
            item_factory(order_detail_id=1, transaction_id=3, product_id=101, product_name="RED", qty=1),
        ]
    )
    app_db.commit()


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


@pytest.fixture()
def manager_headers(make_user, token_for):
    user = make_user(email="manager@maharasa.id", role="manager")
    return bearer(token_for(user))


class TestSummary:

    def test_mengembalikan_angka_ringkas(self, client, seeded, admin_headers):
        response = client.get("/api/sales/summary", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_transactions"] == 3
        assert data["total_amount"] == 600000
        assert data["total_discount"] == 10000
        assert data["average_per_transaction"] == 200000

    def test_transaksi_terhapus_tidak_ikut(self, client, seeded, admin_headers):
        data = client.get("/api/sales/summary", headers=admin_headers).json()["data"]

        assert data["total_amount"] == 600000

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        data = client.get("/api/sales/summary", headers=outlet_headers).json()["data"]

        assert data["total_transactions"] == 2
        assert data["total_amount"] == 300000

    def test_role_outlet_tidak_bisa_meminta_outlet_lain(self, client, seeded, outlet_headers):
        response = client.get("/api/sales/summary?outlet=OUTLET_002", headers=outlet_headers)

        assert response.status_code == 403

    def test_filter_rentang_tanggal(self, client, seeded, admin_headers):
        response = client.get(
            "/api/sales/summary?start_date=2026-01-15&end_date=2026-01-15",
            headers=admin_headers,
        )

        assert response.json()["data"]["total_transactions"] == 2

    def test_tanpa_data_mengembalikan_nol(self, client, admin_headers):
        data = client.get("/api/sales/summary", headers=admin_headers).json()["data"]

        assert data["total_amount"] == 0
        assert data["average_per_transaction"] == 0

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/summary").status_code == 401

    def test_tanggal_format_salah_ditolak_422(self, client, admin_headers):
        assert client.get("/api/sales/summary?start_date=15-01-2026", headers=admin_headers).status_code == 422


class TestDaily:

    def test_satu_baris_per_tanggal_terurut(self, client, seeded, admin_headers):
        data = client.get("/api/sales/daily", headers=admin_headers).json()["data"]

        assert [row["sale_date"] for row in data] == ["2026-01-10", "2026-01-15"]

    def test_membawa_omzet_dan_jumlah_transaksi(self, client, seeded, admin_headers):
        data = client.get("/api/sales/daily", headers=admin_headers).json()["data"]

        assert data[1]["total_amount"] == 500000
        assert data[1]["total_transactions"] == 2

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        data = client.get("/api/sales/daily", headers=outlet_headers).json()["data"]

        assert sum(row["total_amount"] for row in data) == 300000

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/daily").status_code == 401


class TestByOutlet:

    def test_admin_melihat_semua_outlet(self, client, seeded, admin_headers):
        data = client.get("/api/sales/by-outlet", headers=admin_headers).json()["data"]

        assert {row["outlet_code"] for row in data} == {"OUTLET_001", "OUTLET_002"}

    def test_terurut_dari_omzet_terbesar(self, client, seeded, admin_headers, app_db, sale_factory):
        app_db.add(sale_factory(
                transaction_id=9,
                outlet_code="OUTLET_003",
                receipt_pay_price=1000000,
                receipt_total_amount=3,
            ))
        app_db.commit()

        data = client.get("/api/sales/by-outlet", headers=admin_headers).json()["data"]

        assert data[0]["outlet_code"] == "OUTLET_003"

    def test_manager_boleh_mengakses(self, client, seeded, manager_headers):
        assert client.get("/api/sales/by-outlet", headers=manager_headers).status_code == 200

    def test_role_outlet_ditolak_403(self, client, seeded, outlet_headers):
        """Perbandingan antar outlet bukan haknya user outlet."""
        assert client.get("/api/sales/by-outlet", headers=outlet_headers).status_code == 403

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/by-outlet").status_code == 401


class TestTopProducts:

    def test_terurut_dari_terlaris(self, client, seeded, admin_headers):
        data = client.get("/api/sales/top-products", headers=admin_headers).json()["data"]

        assert data[0]["product_name"] == "BLUE"
        assert data[0]["total_qty"] == 10

    def test_limit_dipatuhi(self, client, seeded, admin_headers):
        data = client.get("/api/sales/top-products?limit=1", headers=admin_headers).json()["data"]

        assert len(data) == 1

    def test_limit_melebihi_maksimum_ditolak_422(self, client, seeded, admin_headers):
        assert client.get("/api/sales/top-products?limit=9999", headers=admin_headers).status_code == 422

    def test_filter_product_group(self, client, seeded, admin_headers):
        data = client.get("/api/sales/top-products?product_group=COLORPLATE", headers=admin_headers).json()["data"]

        assert {row["product_name"] for row in data} == {"RED", "BLUE"}

    def test_filter_product_group_memakai_nama_ternormalisasi(self, client, seeded, admin_headers):
        """Nilai dari `/api/sales/product-groups` harus bisa langsung dipakai di sini."""
        data = client.get("/api/sales/top-products?product_group=%20colorplate", headers=admin_headers).json()["data"]

        assert {row["product_name"] for row in data} == {"RED", "BLUE"}
        assert {row["product_group"] for row in data} == {"COLORPLATE"}

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        data = client.get("/api/sales/top-products", headers=outlet_headers).json()["data"]

        nama = {row["product_name"] for row in data}
        assert nama == {"RED", "BLUE"}
        assert {row["product_name"]: row["total_qty"] for row in data}["RED"] == 2

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/top-products").status_code == 401


class TestSaleDetail:

    def test_mengembalikan_transaksi_dan_item(self, client, seeded, admin_headers):
        response = client.get("/api/sales/2", headers=admin_headers)

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["transaction_id"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["product_name"] == "BLUE"

    def test_transaksi_tidak_ada_menghasilkan_404(self, client, seeded, admin_headers):
        assert client.get("/api/sales/99999", headers=admin_headers).status_code == 404

    def test_role_outlet_tidak_bisa_membaca_transaksi_outlet_lain(self, client, seeded, outlet_headers):
        """Transaksi 3 milik OUTLET_002 — harus 404, bukan datanya."""
        response = client.get("/api/sales/3", headers=outlet_headers)

        assert response.status_code == 404

    def test_role_outlet_bisa_membaca_transaksinya_sendiri(self, client, seeded, outlet_headers):
        assert client.get("/api/sales/2", headers=outlet_headers).status_code == 200

    def test_tidak_bentrok_dengan_path_statis(self, client, seeded, admin_headers):
        """`/summary` tidak boleh terbaca sebagai transaction_id."""
        assert client.get("/api/sales/summary", headers=admin_headers).status_code == 200
        assert client.get("/api/sales/colorplate", headers=admin_headers).status_code == 200

    def test_transaction_id_bukan_angka_ditolak_422(self, client, seeded, admin_headers):
        assert client.get("/api/sales/bukan-angka", headers=admin_headers).status_code == 422

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/2").status_code == 401


class TestExportCsv:

    def test_mengembalikan_csv(self, client, seeded, admin_headers):
        response = client.get("/api/sales/export", headers=admin_headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")

    def test_header_kolom_ada(self, client, seeded, admin_headers):
        baris = client.get("/api/sales/export", headers=admin_headers).text.splitlines()

        assert baris[0].startswith("transaction_id,outlet_code,sale_date")

    def test_semua_baris_ikut(self, client, seeded, admin_headers):
        baris = client.get("/api/sales/export", headers=admin_headers).text.strip().splitlines()

        assert len(baris) == 4  # 1 header + 3 transaksi aktif

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        isi = client.get("/api/sales/export", headers=outlet_headers).text

        assert "OUTLET_002" not in isi

    def test_nama_file_disarankan_lewat_content_disposition(self, client, seeded, admin_headers):
        response = client.get("/api/sales/export", headers=admin_headers)

        assert "attachment" in response.headers.get("content-disposition", "")
        assert ".csv" in response.headers.get("content-disposition", "")

    def test_filter_tanggal_dipatuhi(self, client, seeded, admin_headers):
        baris = (
            client.get("/api/sales/export?start_date=2026-01-10&end_date=2026-01-10", headers=admin_headers)
            .text.strip()
            .splitlines()
        )

        assert len(baris) == 2  # header + 1 transaksi

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/export").status_code == 401


class TestSyncStatus:

    def test_mengembalikan_status_per_outlet(self, client, seeded, admin_headers):
        response = client.get("/api/outlets/sync-status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()["data"]
        assert {row["outlet_code"] for row in data} == {"OUTLET_001", "OUTLET_002"}

    def test_membawa_tanggal_penjualan_terakhir(self, client, seeded, admin_headers):
        data = client.get("/api/outlets/sync-status", headers=admin_headers).json()["data"]

        per_outlet = {row["outlet_code"]: row for row in data}
        assert per_outlet["OUTLET_001"]["last_sale_date"] == "2026-01-15"

    def test_membawa_jumlah_transaksi(self, client, seeded, admin_headers):
        data = client.get("/api/outlets/sync-status", headers=admin_headers).json()["data"]

        per_outlet = {row["outlet_code"]: row for row in data}
        assert per_outlet["OUTLET_002"]["total_transactions"] == 1

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        data = client.get("/api/outlets/sync-status", headers=outlet_headers).json()["data"]

        assert [row["outlet_code"] for row in data] == ["OUTLET_001"]

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/outlets/sync-status").status_code == 401
