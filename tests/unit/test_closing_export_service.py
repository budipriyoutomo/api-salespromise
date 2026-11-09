"""Test penyusunan & pengiriman rekap closing ke API eksternal (TODO Fase 8.4).

Kontrak: docs/usulan-kontrak-kirim-closing.md. Keputusan: TODO.md Fase 8.0.
HTTP client diganti tiruan — perilaku HTTP-nya diuji di test_closing_export_client.py.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.config import settings
from app.core.time import utcnow
from app.models.brand import Brand, OutletBrandMapping
from app.models.closing_report import ClosingExportLog, ClosingMenu, ClosingMenuProduct
from app.models.product import Product, ProductPosMapping
from app.models.product_group_mapping import ProductGroupMapping
from app.models.product_menu_mapping import ProductMenuColorplate, ProductMenuMapping
from app.services import (
    closing_export_client,
    closing_export_service,
    closing_report_service,
    colorplate_publish_service,
)
from app.services.closing_export_client import HasilKirim
from tests.unit.test_routes_closing import (
    HARI_INI,
    KEMARIN,
    item,
    jual,
    kirim_closing,
    petakan,
    tandai_tidak_ada_di_pos,
)

ADMIN = "admin@maharasa.id"


@pytest.fixture(autouse=True)
def konfigurasi(monkeypatch):
    monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "https://api.contoh.id/closing-totals")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "token-uji")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TIMEOUT", 3.0)
    monkeypatch.setattr(settings, "CLOSING_EXPORT_MAX_RETRIES", 1)


class ApiTiruan:
    def __init__(self):
        self.hasil = []
        self.panggilan = []

    def __call__(self, payload, **opsi):
        self.panggilan.append((payload, opsi))
        if self.hasil:
            return self.hasil.pop(0)
        return HasilKirim(status="terkirim", http_status=201, response_body='{"ok":true}', error=None, attempts=1)


@pytest.fixture()
def api(monkeypatch):
    tiruan = ApiTiruan()
    monkeypatch.setattr(closing_export_client, "kirim", tiruan)
    return tiruan


def master(db, code, nama, *pos, product_code=None):
    """Produk master + mapping ProductID POS per outlet. `pos` = (outlet, ProductID)."""
    produk = db.query(Product).filter_by(code=code).one_or_none()
    if produk is None:
        produk = Product(code=code, product_code=product_code or f"PRD-{code}", name=nama, price=0)
        db.add(produk)
        db.flush()
    for outlet, pid in pos:
        db.add(ProductPosMapping(product_id=produk.id, outlet_code=outlet, pos_product_id=pid))
    db.commit()
    return produk


def siapkan(db, outlet="OUTLET_001"):
    """Satu menu terpetakan + satu produk POS non-colorplate di master, siap dikirim.

    Mapping menu berlaku untuk semua outlet — hanya dibuat sekali.
    """
    kirim_closing(db, outlet=outlet, items=[item(sold=10, waste=1, adjustment=-1, compensation=2)])
    if not db.query(ClosingMenuProduct).count():
        petakan(db, "SU-001", 200104)
    master(db, "300001", "Ocha Dingin Master", (outlet, 300001))
    jual(db, 1, 200104, 3, outlet=outlet)
    jual(db, 2, 300001, 2, outlet=outlet, nama="Ocha Dingin", product_group="DRINK")


def jadi_mengirim(db, log, menit_lalu=0):
    """Log `mengirim` yang dimulai `menit_lalu`; lewat BATAS_MACET = macet."""
    log.status = "mengirim"
    log.started_at = utcnow() - timedelta(minutes=menit_lalu)
    db.commit()


MACET = closing_export_service.BATAS_MACET.total_seconds() / 60 + 1


def gagal(kode=500, attempts=2):
    return HasilKirim(status="gagal", http_status=kode, response_body="error", error=f"HTTP {kode}", attempts=attempts)


# ---------------------------------------------------------------------------
# Isi payload
# ---------------------------------------------------------------------------


class TestPayload:

    def test_isi_sesuai_kontrak(self, db_session, api):
        siapkan(db_session)

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        payload, opsi = api.panggilan[0]
        assert payload["messageId"] == str(log.message_id)
        assert payload["sequence"] == 1
        assert payload["sentAt"].endswith("Z")
        assert payload["outlet"] == {"code": "OUTLET_001"}
        assert payload["productionDate"] == "2026-10-02"
        assert payload["items"] == [
            {
                "source": "closing",
                "menuId": str(uuid.uuid5(uuid.NAMESPACE_URL, "SU-001")),
                "menuCode": "SU-001",
                "menuName": "Salmon Nigiri",
                "productId": None,
                "productCode": None,
                "productName": None,
                "colorplateSold": 10,
                "posQty": 3,
                "totalSold": 13,
                "waste": 1,
                "adjustment": -1,
                "compensation": 2,
            },
            {
                "source": "pos_only",
                "menuId": None,
                "menuCode": None,
                "menuName": None,
                "productId": "300001",
                "productCode": "PRD-300001",
                "productName": "Ocha Dingin Master",
                "colorplateSold": 0,
                "posQty": 2,
                "totalSold": 2,
                "waste": 0,
                "adjustment": 0,
                "compensation": 0,
            },
        ]
        assert opsi == {
            "message_id": str(log.message_id),
            "url": "https://api.contoh.id/closing-totals",
            "token": "token-uji",
            "timeout": 3.0,
            "max_retries": 1,
        }

    def test_menu_terpetakan_tidak_terjual_pos_nol(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=4)])
        petakan(db_session, "SU-001", 200104)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (0, 4)

    def test_qty_pos_tanpa_pengali(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104, multiplier=3)
        jual(db_session, 1, 200104, 2)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (2, 3)

    def test_qty_pos_pecahan_tetap_desimal(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104)
        jual(db_session, 1, 200104, 1.5)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (1.5, 2.5)

    def test_transaksi_void_tidak_pernah_dihitung(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104)
        jual(db_session, 1, 200104, 5, deleted=1)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert api.panggilan[0][0]["items"][0]["posQty"] == 0

    def test_hanya_outlet_dan_tanggal_yang_diminta(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        kirim_closing(db_session, outlet="OUTLET_002", items=[item()])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200105)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert [b["menuCode"] for b in api.panggilan[0][0]["items"]] == ["SU-001"]


# ---------------------------------------------------------------------------
# Penolakan sebelum kirim
# ---------------------------------------------------------------------------


class TestDitolak:

    def test_belum_dikonfigurasi(self, db_session, api, monkeypatch):
        siapkan(db_session)
        monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "")

        with pytest.raises(closing_export_service.BelumDikonfigurasi):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        assert api.panggilan == []

    def test_tanpa_closing(self, db_session, api):
        jual(db_session, 1, 200104, 3)

        with pytest.raises(closing_export_service.TidakAdaClosing):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

    def test_menu_belum_dipetakan_diblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)

        with pytest.raises(closing_export_service.Diblokir) as exc:
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert [m.menu_code for m in exc.value.blokir.menu_belum_dipetakan] == ["SU-002"]
        assert exc.value.blokir.produk_dobel == []
        assert api.panggilan == []
        assert db_session.query(ClosingExportLog).count() == 0

    def test_menu_tidak_ada_di_pos_tidak_memblokir(self, db_session, api):
        """Menu yang ditandai admin terkirim dengan posQty 0; totalSold = colorplate."""
        kirim_closing(db_session, items=[item(), item("CP-001", "Piring Kosong", sold=7)])
        petakan(db_session, "SU-001", 200104)
        tandai_tidak_ada_di_pos(db_session, "CP-001")
        jual(db_session, 1, 200104, 3)

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert log.status == "terkirim"
        piring = next(i for i in api.panggilan[0][0]["items"] if i["menuCode"] == "CP-001")
        assert (piring["source"], piring["colorplateSold"], piring["posQty"], piring["totalSold"]) == (
            "closing",
            7,
            0,
            7,
        )
        assert set(piring) == set(api.panggilan[0][0]["items"][0])  # tidak ada field tambahan

    def test_menu_bertanda_tidak_menutupi_menu_lain_yang_belum_dipetakan(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("CP-001", "Piring Kosong")])
        tandai_tidak_ada_di_pos(db_session, "CP-001")

        with pytest.raises(closing_export_service.Diblokir) as exc:
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert [m.menu_code for m in exc.value.blokir.menu_belum_dipetakan] == ["SU-001"]

    def test_produk_dipetakan_ke_dua_menu_diblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104)
        petakan(db_session, "SU-002", 200105)
        jual(db_session, 1, 200104, 3)

        with pytest.raises(closing_export_service.Diblokir) as exc:
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (dobel,) = exc.value.blokir.produk_dobel
        assert (dobel.product_id, dobel.product_name, dobel.menus) == (200104, "Salmon HR", ["SU-001", "SU-002"])

    def test_produk_dua_menu_di_tanggal_lain_tidak_memblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert len(api.panggilan) == 1

    def test_mapping_nonaktif_tidak_dihitung_dobel(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104, is_active=False)
        petakan(db_session, "SU-002", 200105)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert len(api.panggilan) == 1

    def test_kiriman_sebelumnya_masih_berjalan(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal()]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        with pytest.raises(closing_export_service.SedangDikirim):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

    def test_kiriman_macet_ditandai_gagal_lalu_digantikan(self, db_session, api):
        """Proses mati di tengah kiriman: status tertinggal `mengirim` selamanya."""
        siapkan(db_session)
        macet = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, macet, menit_lalu=MACET)

        baru = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        db_session.refresh(macet)
        assert (macet.status, macet.error) == ("gagal", closing_export_service.PESAN_MACET)
        assert macet.finished_at is not None
        assert (baru.sequence, baru.status) == (2, "terkirim")


# ---------------------------------------------------------------------------
# Log & sequence
# ---------------------------------------------------------------------------


class TestLog:

    def test_hasil_terkirim_dicatat(self, db_session, api):
        siapkan(db_session)

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        db_session.expire_all()
        log = db_session.get(ClosingExportLog, log.id)
        assert (log.outlet_code, log.production_date, log.sequence) == ("OUTLET_001", HARI_INI, 1)
        assert (log.status, log.http_status, log.attempts, log.error) == ("terkirim", 201, 1, None)
        assert log.response_body == '{"ok":true}'
        assert log.item_count == 2
        assert log.sent_by == ADMIN
        assert log.started_at is not None
        assert log.finished_at is not None
        assert len(log.content_hash) == 64
        assert log.payload == api.panggilan[0][0]

    def test_hasil_gagal_dicatat(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal(503, attempts=2)]

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert (log.status, log.http_status, log.attempts, log.error) == ("gagal", 503, 2, "HTTP 503")

    def test_sequence_naik_per_outlet_dan_tanggal(self, db_session, api):
        siapkan(db_session)
        siapkan(db_session, outlet="OUTLET_002")

        a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        c = closing_export_service.kirim(db_session, "OUTLET_002", HARI_INI, ADMIN)

        assert (a.sequence, b.sequence, c.sequence) == (1, 2, 1)
        assert a.message_id != b.message_id

    def test_hash_sama_untuk_isi_sama(self, db_session, api):
        siapkan(db_session)

        a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert a.content_hash == b.content_hash


# ---------------------------------------------------------------------------
# Kirim ulang log yang gagal
# ---------------------------------------------------------------------------


class TestKirimUlang:

    def test_payload_dan_message_id_sama(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal(attempts=2)]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        hasil = closing_export_service.kirim_ulang(db_session, log.id)

        assert hasil.id == log.id
        assert api.panggilan[1][0] == api.panggilan[0][0]
        assert api.panggilan[1][1]["message_id"] == str(log.message_id)
        assert (hasil.status, hasil.attempts, hasil.http_status, hasil.error) == ("terkirim", 3, 201, None)
        assert db_session.query(ClosingExportLog).count() == 1

    def test_log_mengirim_yang_macet_boleh_diulang(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log, menit_lalu=MACET)
        sebelum = log.started_at

        hasil = closing_export_service.kirim_ulang(db_session, log.id)

        assert hasil.status == "terkirim"
        assert hasil.started_at > sebelum

    def test_yang_masih_berjalan_tidak_diulang(self, db_session, api):
        """Mengulang kiriman yang belum selesai = request kedua ke API tujuan."""
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        with pytest.raises(closing_export_service.TidakBisaDiulang, match="sedang berjalan"):
            closing_export_service.kirim_ulang(db_session, log.id)

    @pytest.mark.parametrize("status", ["terkirim", "duplikat"])
    def test_yang_sudah_sampai_tidak_diulang(self, db_session, api, status):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        log.status = status
        db_session.commit()

        with pytest.raises(closing_export_service.TidakBisaDiulang):
            closing_export_service.kirim_ulang(db_session, log.id)

    def test_yang_sudah_digantikan_kiriman_baru_tidak_diulang(self, db_session, api):
        """API tujuan akan menolak sequence lama — kirim yang baru saja."""
        siapkan(db_session)
        api.hasil = [gagal()]
        lama = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        with pytest.raises(closing_export_service.TidakBisaDiulang):
            closing_export_service.kirim_ulang(db_session, lama.id)

    def test_tidak_ada(self, db_session, api):
        with pytest.raises(closing_export_service.LogTidakDitemukan):
            closing_export_service.kirim_ulang(db_session, 999)

    def test_belum_dikonfigurasi(self, db_session, api, monkeypatch):
        siapkan(db_session)
        api.hasil = [gagal()]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "")

        with pytest.raises(closing_export_service.BelumDikonfigurasi):
            closing_export_service.kirim_ulang(db_session, log.id)


# ---------------------------------------------------------------------------
# Status per outlet × tanggal
# ---------------------------------------------------------------------------


class TestStatus:

    def _status(self, db, **filter_):
        return {(s.outlet_code, s.production_date): s for s in closing_export_service.status_pasangan(db, **filter_)}

    def test_belum_dikirim(self, db_session, api):
        siapkan(db_session)

        (s,) = self._status(db_session).values()

        assert (s.outlet_code, s.production_date, s.status, s.can_send) == ("OUTLET_001", HARI_INI, "belum_dikirim", True)
        assert (s.item_count, s.total_sold) == (2, 15)
        assert s.last_attempt is None and s.last_sent is None

    def test_terkirim_lalu_closing_direvisi_perlu_kirim_ulang(self, db_session, api):
        siapkan(db_session)
        terkirim = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]
        assert (s.status, s.last_sent.id, s.last_attempt.id) == ("terkirim", terkirim.id, terkirim.id)

        jual(db_session, 3, 200104, 1)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].status == "perlu_kirim_ulang"

    def test_duplikat_dihitung_sudah_sampai(self, db_session, api):
        siapkan(db_session)
        api.hasil = [HasilKirim(status="duplikat", http_status=409, response_body=None, error=None, attempts=1)]
        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].status == "terkirim"

    def test_gagal_setelah_terkirim(self, db_session, api):
        siapkan(db_session)
        sampai = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        api.hasil = [gagal()]
        gagal_ = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]

        assert (s.status, s.last_sent.id, s.last_attempt.id, s.last_attempt.status) == (
            "terkirim",
            sampai.id,
            gagal_.id,
            "gagal",
        )

    def test_diblokir_tidak_bisa_dikirim(self, db_session, api):
        kirim_closing(db_session, items=[item()])

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]

        assert s.can_send is False
        assert [m.menu_code for m in s.menu_belum_dipetakan] == ["SU-001"]

    def test_menu_tidak_ada_di_pos_bisa_dikirim(self, db_session, api):
        kirim_closing(db_session, items=[item()])
        tandai_tidak_ada_di_pos(db_session, "SU-001")

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]

        assert (s.can_send, s.menu_belum_dipetakan, s.status) == (True, [], "belum_dikirim")

    def test_sedang_mengirim_tidak_bisa_dikirim(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].can_send is False

    def test_kiriman_macet_tidak_menghalangi(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log, menit_lalu=MACET)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].can_send is True

    def test_filter_outlet_dan_tanggal(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        kirim_closing(db_session, outlet="OUTLET_002", items=[item()])

        semua = self._status(db_session)
        sebagian = self._status(db_session, outlet="OUTLET_001", start_date=HARI_INI, end_date=HARI_INI)

        assert set(semua) == {("OUTLET_001", HARI_INI), ("OUTLET_001", KEMARIN), ("OUTLET_002", HARI_INI)}
        assert set(sebagian) == {("OUTLET_001", HARI_INI)}

    def test_urut_tanggal_terbaru_dulu(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=KEMARIN), item("SU-002", "Tuna", production_date=HARI_INI)])

        hasil = closing_export_service.status_pasangan(db_session)

        assert [s.production_date for s in hasil] == [HARI_INI, KEMARIN]


# ---------------------------------------------------------------------------
# Riwayat
# ---------------------------------------------------------------------------


def test_riwayat_terbaru_dulu_dengan_filter(db_session, api):
    siapkan(db_session)
    siapkan(db_session, outlet="OUTLET_002")
    a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
    api.hasil = [gagal()]
    b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
    c = closing_export_service.kirim(db_session, "OUTLET_002", HARI_INI, ADMIN)

    rows, total = closing_export_service.list_logs(db_session)
    assert ([r.id for r in rows], total) == ([c.id, b.id, a.id], 3)

    rows, total = closing_export_service.list_logs(db_session, outlet="OUTLET_001", status="gagal")
    assert ([r.id for r in rows], total) == ([b.id], 1)

    rows, total = closing_export_service.list_logs(db_session, start_date=date(2026, 10, 3))
    assert total == 0

    rows, total = closing_export_service.list_logs(db_session, limit=1, offset=1)
    assert ([r.id for r in rows], total) == ([b.id], 3)


# ---------------------------------------------------------------------------
# Colorplate tidak dihitung dobel, item POS memakai master, syarat closing per brand
# ---------------------------------------------------------------------------

OUTLET = "OUTLET_001"


def aktifkan_colorplate(db, product_id_konversi=700):
    """Group COLORPLATE aktif + ProductID `product_id_konversi` dikonversi ke RED × 2."""
    db.add(ProductGroupMapping(product_group="COLORPLATE", is_active=True))
    menu = ProductMenuMapping(product_id=product_id_konversi, is_active=True)
    db.add(menu)
    db.flush()
    db.add(ProductMenuColorplate(menu_mapping_id=menu.id, platecolor="RED", multiplier=2, is_active=True))
    db.commit()


def contoh_dokumen(db):
    """RED 10, Promo 3 (konversi RED), Ocha 2; closing Salmon 6 & Tuna 4 bertanda tidak ada di POS."""
    aktifkan_colorplate(db)
    kirim_closing(db, items=[item("SU-001", "Salmon", sold=6), item("SU-002", "Tuna", sold=4)])
    tandai_tidak_ada_di_pos(db, "SU-001")
    tandai_tidak_ada_di_pos(db, "SU-002")
    jual(db, 1, 500, 10, nama="RED", product_group="COLORPLATE")
    jual(db, 2, 300, 2, nama="Ocha", product_group="DRINK")
    jual(db, 3, 700, 3, nama="Promo", product_group="PROMO")


def buka_tanda(db, menu_code):
    """Lepas tanda "tidak ada di POS" supaya menu bisa dipetakan ke ProductID."""
    db.query(ClosingMenu).filter_by(menu_code=menu_code).one().not_in_pos = False
    db.commit()


def brand(db, requires_closing, outlet=OUTLET):
    b = Brand(code="NOC", name="Brand Uji", requires_closing=requires_closing)
    db.add(b)
    db.flush()
    db.add(OutletBrandMapping(outlet_code=outlet, brand_id=b.id))
    db.commit()
    return b


def rekap(db):
    return closing_export_service.susun_rekap(db, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)


def total(r):
    return sum(i["totalSold"] for i in closing_export_service.susun_isi(r)["items"])


class TestColorplateTidakDobel:

    def test_contoh_dokumen_total_12(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha Master", (OUTLET, 300))

        (r,) = rekap(db_session)

        assert not r.blokir
        assert total(r) == 12
        items = closing_export_service.susun_isi(r)["items"]
        assert [(i["source"], i["menuCode"] or i["productId"], i["totalSold"]) for i in items] == [
            ("closing", "SU-001", 6),
            ("closing", "SU-002", 4),
            ("pos_only", "M-OCHA", 2),
        ]
        assert (items[-1]["productCode"], items[-1]["productName"]) == ("PRD-M-OCHA", "Ocha Master")

    def test_group_colorplate_dengan_spasi_tetap_dikenali(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        jual(db_session, 4, 501, 5, nama="BLUE", product_group=" colorplate ")

        (r,) = rekap(db_session)

        assert not r.blokir and total(r) == 12

    def test_produk_tanpa_master_memblokir(self, db_session):
        contoh_dokumen(db_session)

        (r,) = rekap(db_session)

        assert [(p.product_id, p.product_name) for p in r.blokir.produk_belum_master] == [(300, "Ocha")]

    def test_master_tanpa_product_code_memblokir(self, db_session):
        contoh_dokumen(db_session)
        produk = master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        produk.product_code = None
        db_session.commit()

        (r,) = rekap(db_session)

        assert [p.product_id for p in r.blokir.produk_belum_master] == [300]

    @pytest.mark.parametrize("nonaktif", ["mapping", "produk"])
    def test_master_nonaktif_memblokir(self, db_session, nonaktif):
        contoh_dokumen(db_session)
        produk = master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        if nonaktif == "produk":
            produk.is_active = False
        else:
            db_session.query(ProductPosMapping).one().is_active = False
        db_session.commit()

        (r,) = rekap(db_session)

        assert [p.product_id for p in r.blokir.produk_belum_master] == [300]

    def test_master_outlet_lain_tidak_berlaku(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", ("OUTLET_002", 300))

        (r,) = rekap(db_session)

        assert [p.product_id for p in r.blokir.produk_belum_master] == [300]

    @pytest.mark.parametrize("pid", [500, 700])
    def test_produk_colorplate_dipetakan_ke_menu_memblokir(self, db_session, pid):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        buka_tanda(db_session, "SU-001")
        petakan(db_session, "SU-001", pid)

        (r,) = rekap(db_session)

        assert [(p.product_id, p.menus) for p in r.blokir.produk_colorplate_dipetakan] == [(pid, ["SU-001"])]

    def test_dua_productid_satu_master_dijumlah(self, db_session):
        contoh_dokumen(db_session)
        jual(db_session, 4, 301, 5, nama="Ocha Besar", product_group="DRINK")
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300), (OUTLET, 301))

        (r,) = rekap(db_session)

        assert [(i["productId"], i["posQty"]) for i in r.items_produk] == [("M-OCHA", 7)]

    def test_produk_terpetakan_ke_menu_tidak_jadi_pos_only(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        buka_tanda(db_session, "SU-001")
        petakan(db_session, "SU-001", 300)

        (r,) = rekap(db_session)

        assert not r.blokir
        assert r.items_produk == []
        assert total(r) == 12

    def test_group_colorplate_nonaktif_red_jadi_belum_master(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))
        db_session.query(ProductGroupMapping).one().is_active = False
        db_session.commit()

        (r,) = rekap(db_session)

        assert [p.product_id for p in r.blokir.produk_belum_master] == [500]

    def test_compare_with_pos_tetap_menampilkan_semua_produk_pos(self, db_session):
        contoh_dokumen(db_session)

        baris = closing_report_service.compare_with_pos(db_session, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)

        assert sorted(b.products[0].product_id for b in baris if b.menu_id is None) == [300, 500, 700]

    def test_compare_with_pos_baris_tanpa_menu_membawa_master_dan_colorplate(self, db_session):
        """Aturan yang sama dengan kirim rekap: colorplate dilewati, lainnya lewat master."""
        contoh_dokumen(db_session)
        jual(db_session, 4, 900, 1, nama="Air Mineral", product_group="DRINK")
        master(db_session, "M-OCHA", "Ocha Master", (OUTLET, 300))
        # Mapping outlet lain tidak berlaku untuk outlet ini.
        master(db_session, "M-AIR", "Air Master", ("OUTLET_LAIN", 900))

        baris = closing_report_service.compare_with_pos(db_session, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)

        produk = {b.products[0].product_id: b.products[0] for b in baris if b.menu_id is None}
        assert produk[300].master.code == "M-OCHA"
        assert produk[300].master.name == "Ocha Master"
        assert not produk[300].is_colorplate
        assert produk[900].master is None
        assert not produk[900].is_colorplate
        assert produk[500].is_colorplate and produk[700].is_colorplate

    def test_compare_with_pos_master_nonaktif_tidak_dipakai(self, db_session):
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha Master", (OUTLET, 300)).is_active = False
        db_session.commit()

        baris = closing_report_service.compare_with_pos(db_session, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)

        (ocha,) = [b.products[0] for b in baris if b.menu_id is None and b.products[0].product_id == 300]
        assert ocha.master is None


class TestAturanColorplate:
    """Satu aturan dipakai publish colorplate dan kirim rekap closing."""

    def test_group_aktif_dan_konversi(self, db_session):
        aktifkan_colorplate(db_session)

        aturan = colorplate_publish_service.aturan_colorplate(db_session)

        assert aturan.termasuk(500, " Colorplate ")
        assert aturan.termasuk(700, "PROMO")
        assert not aturan.termasuk(300, "DRINK")
        assert not aturan.termasuk(300, None)

    def test_group_nonaktif_hanya_konversi(self, db_session):
        aktifkan_colorplate(db_session)
        db_session.query(ProductGroupMapping).one().is_active = False
        db_session.commit()

        aturan = colorplate_publish_service.aturan_colorplate(db_session)

        assert not aturan.termasuk(500, "COLORPLATE")
        assert aturan.termasuk(700, "PROMO")

    def test_publish_tetap_menghitung_sama(self, db_session):
        contoh_dokumen(db_session)

        (red,) = colorplate_publish_service.rekap_colorplate(db_session, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)

        # RED 10 + Promo 3 × 2.
        assert (red.platecolor, red.sold) == ("RED", 16)


class TestSyaratClosingPerBrand:

    def jual_ocha(self, db):
        jual(db, 2, 300, 2, nama="Ocha", product_group="DRINK")
        master(db, "M-OCHA", "Ocha", (OUTLET, 300))

    def test_brand_wajib_closing_tanpa_closing_tidak_ada_rekap(self, db_session, api):
        brand(db_session, True)
        self.jual_ocha(db_session)

        assert rekap(db_session) == []
        with pytest.raises(closing_export_service.TidakAdaClosing):
            closing_export_service.kirim(db_session, OUTLET, HARI_INI, ADMIN)

    def test_outlet_tanpa_brand_tetap_wajib_closing(self, db_session, api):
        self.jual_ocha(db_session)

        assert rekap(db_session) == []
        with pytest.raises(closing_export_service.TidakAdaClosing):
            closing_export_service.kirim(db_session, OUTLET, HARI_INI, ADMIN)

    def test_brand_tanpa_syarat_bisa_kirim_pos_only(self, db_session, api):
        brand(db_session, False)
        self.jual_ocha(db_session)

        (r,) = rekap(db_session)
        assert not r.blokir and total(r) == 2

        (s,) = closing_export_service.status_pasangan(db_session, start_date=HARI_INI, end_date=HARI_INI)
        assert (s.can_send, s.has_closing, s.item_count, s.total_sold) == (True, False, 1, 2)

        log = closing_export_service.kirim(db_session, OUTLET, HARI_INI, ADMIN)
        assert log.status == "terkirim"
        assert [i["source"] for i in api.panggilan[0][0]["items"]] == ["pos_only"]

    def test_brand_tanpa_syarat_tetap_pakai_closing_kalau_ada(self, db_session):
        brand(db_session, False)
        contoh_dokumen(db_session)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))

        (r,) = rekap(db_session)

        assert r.baris_menu and total(r) == 12

    def test_brand_tanpa_syarat_colorplate_terjual_diblokir(self, db_session):
        aktifkan_colorplate(db_session)
        brand(db_session, False)
        jual(db_session, 1, 500, 10, nama="RED", product_group="COLORPLATE")
        jual(db_session, 2, 700, 3, nama="Promo", product_group="PROMO")

        (r,) = rekap(db_session)

        assert [p.product_id for p in r.blokir.colorplate_tanpa_closing] == [500, 700]

    def test_brand_tanpa_syarat_tanpa_penjualan(self, db_session, api):
        brand(db_session, False)

        with pytest.raises(closing_export_service.TidakAdaPenjualan):
            closing_export_service.kirim(db_session, OUTLET, HARI_INI, ADMIN)

    def test_void_tidak_dihitung(self, db_session):
        brand(db_session, False)
        jual(db_session, 9, 300, 4, nama="Ocha", product_group="DRINK", deleted=1)
        master(db_session, "M-OCHA", "Ocha", (OUTLET, 300))

        assert rekap(db_session) == []

    def test_status_tanpa_rentang_tanggal_tidak_memindai_penjualan(self, db_session):
        brand(db_session, False)
        self.jual_ocha(db_session)

        assert closing_export_service.status_pasangan(db_session) == []
