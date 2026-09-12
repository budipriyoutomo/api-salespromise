"""Test schema Pydantic — kontrak payload yang diterima API."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.models.sales_items import SalesItems
from app.schemas.sales_event import PublishSalesRequest
from app.schemas.sales_schema import SalesItemSchema, SalesSchema, SyncRequestSchema

MINIMAL_ITEM = {
    "order_detail_id": 1,
    "transaction_id": 10001,
    "sale_date": "2026-01-15",
    "product_id": 101,
    "qty": 2,
    "price": 75000,
}

MINIMAL_SALE = {"transaction_id": 10001}


class TestSalesItemSchema:

    def test_payload_minimal_valid(self):
        item = SalesItemSchema(**MINIMAL_ITEM)

        assert item.order_detail_id == 1
        assert item.sale_date == date(2026, 1, 15)

    def test_default_terisi_saat_field_opsional_tidak_dikirim(self):
        item = SalesItemSchema(**MINIMAL_ITEM)

        assert item.product_group is None
        assert item.product_dept is None
        assert item.product_name is None
        assert item.product_set_type == 0
        assert item.order_status_id == 2
        assert item.sale_mode == 1
        assert item.retail_price == 0.0
        assert item.minimum_price == 0.0
        assert item.comment is None
        assert item.order_staff_id == 0
        assert item.order_table_id == 0
        assert item.void_staff_id == 0

    @pytest.mark.parametrize("field", ["order_detail_id", "transaction_id", "sale_date", "product_id", "qty", "price"])
    def test_field_wajib_tidak_boleh_hilang(self, field):
        payload = dict(MINIMAL_ITEM)
        payload.pop(field)

        with pytest.raises(ValidationError) as exc:
            SalesItemSchema(**payload)

        assert field in str(exc.value)

    @pytest.mark.parametrize("bad_date", ["15-01-2026", "2026/01/15", "bukan tanggal", ""])
    def test_sale_date_format_salah_ditolak(self, bad_date):
        payload = dict(MINIMAL_ITEM, sale_date=bad_date)

        with pytest.raises(ValidationError):
            SalesItemSchema(**payload)

    def test_qty_dan_price_string_angka_ter_coerce_ke_float(self):
        item = SalesItemSchema(**dict(MINIMAL_ITEM, qty="2.5", price="75000.75"))

        assert item.qty == 2.5
        assert item.price == 75000.75

    def test_qty_non_numerik_ditolak(self):
        with pytest.raises(ValidationError):
            SalesItemSchema(**dict(MINIMAL_ITEM, qty="dua"))

    def test_from_attributes_aktif_untuk_serialisasi_orm(self, db_session, sale_factory, item_factory):
        """`Config.from_attributes` dipakai agar objek ORM bisa langsung divalidasi.

        Objek harus sudah tersimpan lebih dulu: default kolom SQLAlchemy baru
        terisi saat INSERT, bukan saat instance dibuat.
        """
        db_session.add(sale_factory())
        db_session.add(item_factory())
        db_session.commit()

        row = db_session.query(SalesItems).first()
        item = SalesItemSchema.model_validate(row, from_attributes=True)

        assert item.order_detail_id == 1
        assert item.product_name == "RED"
        assert item.qty == 2


class TestSalesSchema:

    def test_payload_minimal_hanya_butuh_transaction_id(self):
        sale = SalesSchema(**MINIMAL_SALE)

        assert sale.transaction_id == 10001

    def test_transaction_id_wajib(self):
        with pytest.raises(ValidationError) as exc:
            SalesSchema()

        assert "transaction_id" in str(exc.value)

    def test_items_kosong_valid(self):
        sale = SalesSchema(**MINIMAL_SALE)

        assert sale.items == []

    def test_items_default_tidak_dibagi_antar_instance(self):
        """Jebakan klasik mutable default — pastikan `default_factory` benar-benar dipakai."""
        a = SalesSchema(**MINIMAL_SALE)
        b = SalesSchema(**MINIMAL_SALE)

        a.items.append(SalesItemSchema(**MINIMAL_ITEM))

        assert b.items == []

    def test_default_numerik_nol_dan_status_default(self):
        sale = SalesSchema(**MINIMAL_SALE)

        assert sale.shop_id == 0
        assert sale.transaction_status_id == 1
        assert sale.sale_mode == 1
        assert sale.deleted == 0
        assert sale.no_customer == 1
        assert sale.receipt_total_amount == 0.0
        assert sale.vat_percent == 0.0
        assert sale.service_charge == 0.0
        assert sale.is_split_transaction == 0

    def test_tanggal_opsional_boleh_none(self):
        sale = SalesSchema(**MINIMAL_SALE)

        assert sale.sale_date is None
        assert sale.paid_time is None
        assert sale.close_time is None
        assert sale.void_time is None

    def test_paid_time_menerima_iso_datetime(self):
        sale = SalesSchema(**MINIMAL_SALE, paid_time="2026-01-15T10:30:00")

        assert sale.paid_time == datetime(2026, 1, 15, 10, 30)

    def test_nested_items_ter_parse(self):
        sale = SalesSchema(**MINIMAL_SALE, items=[MINIMAL_ITEM, dict(MINIMAL_ITEM, order_detail_id=2)])

        assert len(sale.items) == 2
        assert all(isinstance(i, SalesItemSchema) for i in sale.items)
        assert [i.order_detail_id for i in sale.items] == [1, 2]

    def test_item_invalid_menggagalkan_seluruh_sale(self):
        bad_item = dict(MINIMAL_ITEM)
        bad_item.pop("qty")

        with pytest.raises(ValidationError):
            SalesSchema(**MINIMAL_SALE, items=[bad_item])

    def test_outlet_code_bukan_bagian_dari_schema(self):
        """outlet_code berasal dari API key, tidak boleh diterima dari body."""
        assert "outlet_code" not in SalesSchema.model_fields
        assert "outlet" not in SalesSchema.model_fields


class TestSyncRequestSchema:

    def test_membungkus_daftar_sales(self):
        req = SyncRequestSchema(sales=[MINIMAL_SALE, dict(MINIMAL_SALE, transaction_id=10002)])

        assert len(req.sales) == 2

    def test_sales_wajib_ada(self):
        with pytest.raises(ValidationError):
            SyncRequestSchema()

    def test_sales_boleh_list_kosong(self):
        req = SyncRequestSchema(sales=[])

        assert req.sales == []


class TestPublishSalesRequest:

    def test_default_exchange_dan_routing_key(self):
        req = PublishSalesRequest(date="2026-01-15")

        assert req.exchange == "posdata_exchange"
        assert req.routing_key == "posdata.created"

    def test_date_wajib(self):
        with pytest.raises(ValidationError) as exc:
            PublishSalesRequest()

        assert "date" in str(exc.value)

    def test_exchange_dan_routing_key_bisa_dioverride(self):
        req = PublishSalesRequest(date="2026-01-15", exchange="lain_exchange", routing_key="lain.created")

        assert req.exchange == "lain_exchange"
        assert req.routing_key == "lain.created"

    def test_date_di_parse_jadi_objek_date(self):
        req = PublishSalesRequest(date="2026-01-15")

        assert req.date == date(2026, 1, 15)

    @pytest.mark.parametrize("bad_date", ["15-01-2026", "besok", "2026-13-01"])
    def test_date_invalid_ditolak(self, bad_date):
        with pytest.raises(ValidationError):
            PublishSalesRequest(date=bad_date)
