"""Test kontrak event `closingreport.submitted` (TODO Fase 7.1).

Pesan datang dari sistem lain lewat RabbitMQ. Pesan yang gagal validasi
tidak boleh menyentuh database — consumer mengarahkannya ke DLQ.
"""

import copy
from datetime import date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.closing_report_event import ClosingReportSubmitted

REPORT_ID = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"
MENU_ID = "0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"
MENU_ID_2 = "1b2c3d4e-5f6a-4b8c-9d0e-1f2a3b4c5d6e"

PAYLOAD = {
    "event": "closingreport.submitted",
    "version": 1,
    "messageId": REPORT_ID,
    "sentAt": "2026-10-02T22:15:00+07:00",
    "data": {
        "closingReportId": REPORT_ID,
        "date": "2026-10-02",
        "outlet": {"code": "MHR-01", "name": "Maharasa PIK"},
        "brand": {"code": "MHR", "name": "Maharasa"},
        "items": [
            {
                "menuId": MENU_ID,
                "menuCode": "SU-001",
                "menuName": "Salmon Nigiri",
                "productionDate": "2026-10-02",
                "sold": 42,
                "waste": 3,
                "adjustment": 1,
                "compensation": 0,
            }
        ],
    },
}


def payload(**ubah_data):
    """Salinan PAYLOAD; argumen mengganti field di dalam `data`."""
    hasil = copy.deepcopy(PAYLOAD)
    hasil["data"].update(ubah_data)
    return hasil


def payload_item(**ubah_item):
    hasil = copy.deepcopy(PAYLOAD)
    hasil["data"]["items"][0].update(ubah_item)
    return hasil


class TestPayloadValid:

    def test_contoh_kontrak_diterima(self):
        event = ClosingReportSubmitted.model_validate(PAYLOAD)

        assert event.event == "closingreport.submitted"
        assert event.version == 1
        assert event.message_id == REPORT_ID
        assert event.data.closing_report_id == UUID(REPORT_ID)
        assert event.data.date == date(2026, 10, 2)
        assert event.data.outlet.code == "MHR-01"
        assert event.data.outlet.name == "Maharasa PIK"
        assert event.data.brand.code == "MHR"
        assert event.data.brand.name == "Maharasa"

        item = event.data.items[0]
        assert item.menu_id == UUID(MENU_ID)
        assert item.menu_code == "SU-001"
        assert item.menu_name == "Salmon Nigiri"
        assert item.production_date == date(2026, 10, 2)
        assert (item.sold, item.waste, item.adjustment, item.compensation) == (42, 3, 1, 0)

    def test_bisa_langsung_dari_bytes_json(self):
        """Consumer menerima `body` berupa bytes dari pika."""
        import json

        event = ClosingReportSubmitted.model_validate_json(json.dumps(PAYLOAD).encode())

        assert event.data.closing_report_id == UUID(REPORT_ID)

    def test_field_tambahan_diabaikan(self):
        """Pengirim boleh menambah field tanpa mematahkan consumer."""
        data = payload(catatan="baru")
        data["traceId"] = "abc"
        data["data"]["items"][0]["unit"] = "pcs"

        ClosingReportSubmitted.model_validate(data)


class TestEnvelope:

    def test_event_lain_ditolak(self):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(dict(PAYLOAD, event="closingreport.deleted"))

    @pytest.mark.parametrize("version", [0, 2, "2"])
    def test_versi_tidak_dikenal_ditolak(self, version):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(dict(PAYLOAD, version=version))

    @pytest.mark.parametrize("field", ["event", "version", "messageId", "sentAt", "data"])
    def test_field_envelope_wajib(self, field):
        data = copy.deepcopy(PAYLOAD)
        data.pop(field)

        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(data)

    @pytest.mark.parametrize("message_id", ["", "   "])
    def test_message_id_kosong_ditolak(self, message_id):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(dict(PAYLOAD, messageId=message_id))

    def test_sent_at_dinormalisasi_ke_utc_tanpa_tzinfo(self):
        """Kolom timestamp di DB tanpa timezone dan berisi UTC (lihat app/core/time.py)."""
        event = ClosingReportSubmitted.model_validate(PAYLOAD)

        assert event.sent_at == datetime(2026, 10, 2, 15, 15, 0)
        assert event.sent_at.tzinfo is None

    def test_sent_at_tanpa_zona_waktu_ditolak(self):
        """Tanpa offset tidak bisa diketahui jam itu WIB atau UTC."""
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(dict(PAYLOAD, sentAt="2026-10-02T22:15:00"))


class TestData:

    @pytest.mark.parametrize("field", ["closingReportId", "date", "outlet", "brand", "items"])
    def test_field_data_wajib(self, field):
        data = copy.deepcopy(PAYLOAD)
        data["data"].pop(field)

        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(data)

    def test_closing_report_id_bukan_uuid_ditolak(self):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(closingReportId="CR-123"))

    @pytest.mark.parametrize("tanggal", ["02-10-2026", "2026/10/02", "bukan tanggal"])
    def test_format_tanggal_salah_ditolak(self, tanggal):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(date=tanggal))

    def test_items_kosong_ditolak(self):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(items=[]))

    def test_outlet_code_di_trim_tanpa_ubah_huruf(self):
        """`api_keys.outlet_code` dicocokkan persis — huruf tidak boleh diubah."""
        event = ClosingReportSubmitted.model_validate(payload(outlet={"code": " Sttsm ", "name": "PIK"}))

        assert event.data.outlet.code == "Sttsm"

    def test_outlet_code_maksimal_20_karakter(self):
        """Sama dengan panjang kolom `api_keys.outlet_code`."""
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(outlet={"code": "X" * 21, "name": "PIK"}))

    @pytest.mark.parametrize("kode", ["", "   "])
    def test_outlet_code_kosong_ditolak(self, kode):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(outlet={"code": kode, "name": "PIK"}))

    def test_brand_code_dinormalisasi_seperti_tabel_brands(self):
        event = ClosingReportSubmitted.model_validate(payload(brand={"code": " mhr ", "name": "Maharasa"}))

        assert event.data.brand.code == "MHR"

    def test_brand_code_maksimal_20_karakter(self):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload(brand={"code": "M" * 21, "name": "Maharasa"}))


class TestItem:

    @pytest.mark.parametrize(
        "field", ["menuId", "menuName", "sold", "waste", "adjustment", "compensation"]
    )
    def test_field_item_wajib(self, field):
        data = copy.deepcopy(PAYLOAD)
        data["data"]["items"][0].pop(field)

        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(data)

    def test_menu_id_bukan_uuid_ditolak(self):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload_item(menuId="123"))

    def test_menu_code_di_trim(self):
        event = ClosingReportSubmitted.model_validate(payload_item(menuCode=" SU-001 "))

        assert event.data.items[0].menu_code == "SU-001"

    @pytest.mark.parametrize("kode", [None, "", "   "])
    def test_menu_code_boleh_kosong(self, kode):
        """Jawaban pengirim: menu lama belum punya kode. Kuncinya menuId, bukan menuCode."""
        event = ClosingReportSubmitted.model_validate(payload_item(menuCode=kode))

        assert event.data.items[0].menu_code is None

    def test_menu_code_boleh_tidak_dikirim(self):
        data = copy.deepcopy(PAYLOAD)
        data["data"]["items"][0].pop("menuCode")

        assert ClosingReportSubmitted.model_validate(data).data.items[0].menu_code is None

    def test_production_date_boleh_null(self):
        """Jawaban pengirim: null kalau menu tidak punya baris produksi hari itu."""
        event = ClosingReportSubmitted.model_validate(payload_item(productionDate=None))

        assert event.data.items[0].production_date is None

    @pytest.mark.parametrize("field", ["sold", "waste"])
    def test_qty_negatif_ditolak(self, field):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload_item(**{field: -1}))

    def test_adjustment_boleh_negatif(self):
        """Dikonfirmasi pengirim: adjustment adalah koreksi, tanpa batas bawah."""
        event = ClosingReportSubmitted.model_validate(payload_item(adjustment=-2))

        assert event.data.items[0].adjustment == -2

    def test_compensation_negatif_diterima(self):
        """Pengirim belum memvalidasinya per menu. Diputuskan 2026-10-05: diterima,
        consumer mencatat warning — satu angka janggal tidak membuang laporan sehari."""
        event = ClosingReportSubmitted.model_validate(payload_item(compensation=-1))

        assert event.data.items[0].compensation == -1

    @pytest.mark.parametrize("field", ["sold", "waste", "adjustment", "compensation"])
    def test_qty_pecahan_ditolak(self, field):
        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(payload_item(**{field: 1.5}))

    def test_production_date_boleh_beda_dengan_tanggal_closing(self):
        """Mis. waste stok produksi kemarin dilaporkan di closing hari ini."""
        event = ClosingReportSubmitted.model_validate(payload_item(productionDate="2026-10-01"))

        assert event.data.items[0].production_date == date(2026, 10, 1)

    def test_menu_sama_tanpa_tanggal_produksi_dua_kali_ditolak(self):
        data = copy.deepcopy(PAYLOAD)
        data["data"]["items"][0]["productionDate"] = None
        data["data"]["items"].append(copy.deepcopy(data["data"]["items"][0]))

        with pytest.raises(ValidationError):
            ClosingReportSubmitted.model_validate(data)

    def test_menu_sama_tanggal_produksi_sama_dua_kali_ditolak(self):
        """Satu baris per (menu, tanggal produksi) — kalau dobel, tidak jelas mana yang benar."""
        data = copy.deepcopy(PAYLOAD)
        data["data"]["items"].append(copy.deepcopy(data["data"]["items"][0]))

        with pytest.raises(ValidationError) as exc:
            ClosingReportSubmitted.model_validate(data)

        assert MENU_ID in str(exc.value)

    def test_menu_sama_tanggal_produksi_beda_diterima(self):
        data = copy.deepcopy(PAYLOAD)
        kedua = copy.deepcopy(data["data"]["items"][0])
        kedua["productionDate"] = "2026-10-01"
        data["data"]["items"].append(kedua)

        event = ClosingReportSubmitted.model_validate(data)

        assert len(event.data.items) == 2

    def test_menu_berbeda_diterima(self):
        data = copy.deepcopy(PAYLOAD)
        kedua = copy.deepcopy(data["data"]["items"][0])
        kedua.update(menuId=MENU_ID_2, menuCode="SU-002", menuName="Tuna Nigiri")
        data["data"]["items"].append(kedua)

        event = ClosingReportSubmitted.model_validate(data)

        assert [i.menu_code for i in event.data.items] == ["SU-001", "SU-002"]
