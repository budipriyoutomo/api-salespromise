"""Kolom `Deleted` harus sampai ke frontend (TODO frontend 5.5).

Frontend perlu menandai struk yang dibatalkan secara visual. Tanpa kolom ini
di response, satu-satunya petunjuk yang tersedia adalah `void_staff_id`, dan
itu kolom lain dengan arti lain — menandai void berdasarkan tebakan.

Yang dikunci di sini adalah **kolomnya ikut terkirim**, bukan sekadar nilainya
kebetulan benar di satu baris contoh.
"""

from app.schemas.sales_response import SaleDetail, SaleResponse


class TestSaleResponseMembawaDeleted:

    def test_field_deleted_ada_di_schema(self):
        assert "deleted" in SaleResponse.model_fields

    def test_nilai_deleted_ikut_terkirim(self, persisted_sales, sale_factory, app_db):
        sale = sale_factory(transaction_id=9001, deleted=1)
        app_db.add(sale)
        app_db.commit()
        app_db.refresh(sale)

        hasil = SaleResponse.model_validate(sale)

        assert hasil.deleted == 1

    def test_transaksi_normal_deleted_nol(self, persisted_sales, sale_factory, app_db):
        sale = sale_factory(transaction_id=9002)
        app_db.add(sale)
        app_db.commit()
        app_db.refresh(sale)

        assert SaleResponse.model_validate(sale).deleted == 0

    def test_deleted_punya_default_supaya_baris_lama_tidak_gagal(self):
        # Baris yang belum tersimpan belum punya default kolom dari DB.
        hasil = SaleResponse(
            transaction_id=1,
            shop_id=1,
            receipt_id=0,
            receipt_total_amount=0,
            receipt_pay_price=0,
            receipt_discount=0,
            transaction_status_id=1,
            void_staff_id=0,
        )

        assert hasil.deleted == 0


class TestSaleDetailMembawaDeleted:
    """Detail transaksi dipakai dialog di frontend — penandanya harus sama."""

    def test_field_deleted_ada_di_schema_detail(self):
        assert "deleted" in SaleDetail.model_fields
