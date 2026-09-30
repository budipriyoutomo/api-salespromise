"""TransactionID unik PER OUTLET (TODO 0.5, migrasi 010).

POS tiap outlet menomori transaksinya sendiri, jadi TransactionID yang sama
bisa datang dari dua outlet berbeda. Dulu PK `ordertransaction` hanya
("TransactionID") — outlet kedua ditolak `UniqueViolation` dan batch sync-nya
tidak pernah masuk. Item juga di-join hanya lewat TransactionID, sehingga item
satu outlet ikut terhitung di outlet lain.

Di sini dua outlet sengaja memakai TransactionID DAN OrderDetailID yang sama.
"""

from datetime import date

import pytest
from sqlalchemy import inspect

from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services import product_menu_service
from app.services.sales_service import SalesService

HARI = date(2026, 1, 15)


@pytest.fixture()
def bentrok(db_session, sale_factory, item_factory):
    db_session.add_all(
        [
            sale_factory(transaction_id=1, outlet_code="OUTLET_001", sale_date=HARI),
            sale_factory(transaction_id=1, outlet_code="OUTLET_002", sale_date=HARI),
        ]
    )
    db_session.add_all(
        [
            item_factory(order_detail_id=1, transaction_id=1, outlet_code="OUTLET_001", product_id=101, product_name="RED", qty=2),
            item_factory(order_detail_id=1, transaction_id=1, outlet_code="OUTLET_002", product_id=102, product_name="BLUE", qty=5),
        ]
    )
    db_session.commit()
    return db_session


class TestSkemaModel:

    def test_pk_transaksi_memuat_outlet_code(self):
        assert [c.name for c in inspect(Sales).primary_key] == ["TransactionID", "outlet_code"]

    def test_pk_item_memuat_outlet_code(self):
        assert [c.name for c in inspect(SalesItems).primary_key] == ["OrderDetailID", "TransactionID", "outlet_code"]

    def test_fk_item_komposit_ke_transaksi(self):
        (fk,) = SalesItems.__table__.foreign_key_constraints
        assert [c.name for c in fk.columns] == ["TransactionID", "outlet_code"]
        assert [e.target_fullname for e in fk.elements] == [
            "ordertransaction.TransactionID",
            "ordertransaction.outlet_code",
        ]


class TestDuaOutletTransactionIdSama:

    def test_keduanya_tersimpan(self, bentrok):
        assert bentrok.query(Sales).count() == 2
        assert bentrok.query(SalesItems).count() == 2

    def test_colorplate_tidak_tercampur(self, bentrok):
        hasil = {
            (r.product_name, r.outlet_code): float(r.sold)
            for r in SalesService.get_sales_colorplate(db=bentrok, start_date=HARI, end_date=HARI)
        }

        assert hasil == {("RED", "OUTLET_001"): 2.0, ("BLUE", "OUTLET_002"): 5.0}

    def test_rekap_per_product_id_tidak_tercampur(self, bentrok):
        hasil = {
            (r.product_id, r.outlet_code): float(r.sold)
            for r in SalesService.get_sales_by_product_ids(db=bentrok, product_ids=[101, 102])
        }

        assert hasil == {(101, "OUTLET_001"): 2.0, (102, "OUTLET_002"): 5.0}

    def test_top_products_per_outlet(self, bentrok):
        hasil = {r.product_name: float(r.total_qty) for r in SalesService.get_top_products(db=bentrok, outlet="OUTLET_001")}

        assert hasil == {"RED": 2.0}

    def test_list_product_groups_per_outlet(self, bentrok, item_factory):
        bentrok.add(
            item_factory(order_detail_id=2, transaction_id=1, outlet_code="OUTLET_002", product_group="FOOD", product_name="NASI")
        )
        bentrok.commit()

        assert SalesService.list_product_groups(db=bentrok, outlet="OUTLET_001") == ["COLORPLATE"]

    def test_detail_hanya_item_outlet_itu(self, bentrok):
        _, items = SalesService.get_sale_detail(db=bentrok, transaction_id=1, outlet="OUTLET_002")

        assert [(i.product_name, i.outlet_code) for i in items] == [("BLUE", "OUTLET_002")]

    def test_detail_tanpa_outlet_item_mengikuti_transaksi_yang_dikembalikan(self, bentrok):
        sale, items = SalesService.get_sale_detail(db=bentrok, transaction_id=1, outlet=None)

        assert len(items) == 1
        assert items[0].outlet_code == sale.outlet_code

    def test_kandidat_menu_mencatat_outlet_yang_benar(self, bentrok):
        hasil = {k.product_id: k.outlet_codes for k in product_menu_service.list_candidates(bentrok)}

        assert hasil == {101: ["OUTLET_001"], 102: ["OUTLET_002"]}
