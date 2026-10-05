"""Test constraint model closing report (TODO Fase 7.2).

Dijalankan di SQLite; constraint yang sama ada di migrations/011_closing_reports.sql.
"""

from datetime import date, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.closing_report import (
    ClosingMenu,
    ClosingMenuProduct,
    ClosingReport,
    ClosingReportItem,
    ClosingReportRevision,
)

REPORT_ID = UUID("6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")
MENU_ID = UUID("0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d")


def _laporan(db):
    laporan = ClosingReport(
        closing_report_id=REPORT_ID,
        report_date=date(2026, 10, 2),
        outlet_code="STTSM",
        outlet_name="Maharasa PIK",
        brand_code="MHR",
        brand_name="Maharasa",
    )
    db.add(laporan)
    db.flush()
    return laporan


def _revisi(db, laporan, message_id="m-1", sent_at=datetime(2026, 10, 2, 15, 15), is_current=True):
    revisi = ClosingReportRevision(
        report_id=laporan.id,
        message_id=message_id,
        version=1,
        sent_at=sent_at,
        is_current=is_current,
        raw_payload={"event": "closingreport.submitted"},
    )
    db.add(revisi)
    db.flush()
    return revisi


def _item(revisi, **ubah):
    nilai = dict(
        revision_id=revisi.id,
        menu_id=MENU_ID,
        menu_code="SU-001",
        menu_name="Salmon Nigiri",
        production_date=date(2026, 10, 2),
        sold=42,
        waste=3,
        adjustment=1,
        compensation=0,
    )
    nilai.update(ubah)
    return ClosingReportItem(**nilai)


def test_laporan_revisi_item_tersimpan_dan_terbaca_lagi(db_session):
    laporan = _laporan(db_session)
    revisi = _revisi(db_session, laporan)
    db_session.add(_item(revisi))
    db_session.commit()
    db_session.expire_all()

    tersimpan = db_session.query(ClosingReport).one()
    assert tersimpan.closing_report_id == REPORT_ID
    assert tersimpan.created_at is not None
    assert [r.message_id for r in tersimpan.revisions] == ["m-1"]
    assert tersimpan.revisions[0].raw_payload == {"event": "closingreport.submitted"}
    assert tersimpan.revisions[0].received_at is not None
    item = tersimpan.revisions[0].items[0]
    assert (item.menu_id, item.sold, item.adjustment) == (MENU_ID, 42, 1)


def test_closing_report_id_unik(db_session):
    _laporan(db_session)

    with pytest.raises(IntegrityError):
        _laporan(db_session)


def test_satu_laporan_hanya_boleh_punya_satu_revisi_aktif(db_session):
    laporan = _laporan(db_session)
    _revisi(db_session, laporan, message_id="m-1")

    with pytest.raises(IntegrityError):
        _revisi(db_session, laporan, message_id="m-2", sent_at=datetime(2026, 10, 2, 16, 0))


def test_revisi_lama_tetap_tersimpan_sebagai_tidak_aktif(db_session):
    laporan = _laporan(db_session)
    _revisi(db_session, laporan, message_id="m-1", is_current=False)
    _revisi(db_session, laporan, message_id="m-2", sent_at=datetime(2026, 10, 2, 16, 0))
    db_session.commit()

    assert db_session.query(ClosingReportRevision).count() == 2


def test_pesan_yang_sama_dikirim_ulang_ditolak_unique(db_session):
    """Jawaban pengirim: retry membawa sentAt baru, isinya identik — messageId saja kuncinya."""
    laporan = _laporan(db_session)
    _revisi(db_session, laporan, message_id="m-1", is_current=False)

    with pytest.raises(IntegrityError):
        _revisi(db_session, laporan, message_id="m-1", sent_at=datetime(2026, 10, 3, 1, 0), is_current=False)


def test_item_menu_dan_tanggal_produksi_unik_per_revisi(db_session):
    revisi = _revisi(db_session, _laporan(db_session))
    db_session.add(_item(revisi))
    db_session.flush()

    db_session.add(_item(revisi))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["sold", "waste"])
def test_qty_item_negatif_ditolak(db_session, field):
    revisi = _revisi(db_session, _laporan(db_session))
    db_session.add(_item(revisi, **{field: -1}))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_adjustment_item_boleh_negatif(db_session):
    revisi = _revisi(db_session, _laporan(db_session))
    db_session.add(_item(revisi, adjustment=-2))
    db_session.flush()


def test_compensation_negatif_dan_kode_tanggal_kosong_diterima(db_session):
    """Jawaban pengirim: menuCode & productionDate bisa null, compensation belum divalidasi."""
    revisi = _revisi(db_session, _laporan(db_session))
    db_session.add(_item(revisi, compensation=-1, menu_code=None, production_date=None))
    db_session.flush()


def test_menu_id_unik(db_session):
    db_session.add(ClosingMenu(menu_code="SU-001", menu_id=MENU_ID, menu_name="Salmon Nigiri"))
    db_session.flush()

    db_session.add(ClosingMenu(menu_code="SU-999", menu_id=MENU_ID, menu_name="Nama lain"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_menu_code_sama_beda_brand_diterima(db_session):
    """menuCode unik per brand saja, dan bisa null."""
    db_session.add_all(
        [
            ClosingMenu(menu_code="SU-001", menu_id=MENU_ID, menu_name="Salmon", brand_code="MHR"),
            ClosingMenu(
                menu_code="SU-001",
                menu_id=UUID("1b2c3d4e-5f6a-4b8c-9d0e-1f2a3b4c5d6e"),
                menu_name="Salmon",
                brand_code="LAIN",
            ),
            ClosingMenu(menu_code=None, menu_id=UUID("2c3d4e5f-6a7b-4c9d-8e0f-2a3b4c5d6e7f"), menu_name="Lama"),
        ]
    )
    db_session.flush()


def test_menu_dipetakan_ke_banyak_product_dengan_pengali(db_session):
    menu = ClosingMenu(menu_code="SU-001", menu_id=MENU_ID, menu_name="Salmon Nigiri")
    db_session.add(menu)
    db_session.flush()
    db_session.add_all(
        [
            ClosingMenuProduct(closing_menu_id=menu.id, product_id=200104, multiplier=1),
            ClosingMenuProduct(closing_menu_id=menu.id, product_id=200999, multiplier=2),
        ]
    )
    db_session.commit()
    db_session.expire_all()

    menu = db_session.query(ClosingMenu).one()
    assert [(p.product_id, p.multiplier, p.is_active) for p in menu.products] == [(200104, 1, True), (200999, 2, True)]
    assert menu.first_seen_at is not None


def test_product_yang_sama_tidak_boleh_dobel_di_satu_menu(db_session):
    menu = ClosingMenu(menu_code="SU-001", menu_id=MENU_ID, menu_name="Salmon Nigiri")
    db_session.add(menu)
    db_session.flush()
    db_session.add(ClosingMenuProduct(closing_menu_id=menu.id, product_id=200104))
    db_session.flush()

    db_session.add(ClosingMenuProduct(closing_menu_id=menu.id, product_id=200104))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("ubah", [{"multiplier": 0}, {"product_id": 0}])
def test_pengali_dan_product_id_harus_positif(db_session, ubah):
    menu = ClosingMenu(menu_code="SU-001", menu_id=MENU_ID, menu_name="Salmon Nigiri")
    db_session.add(menu)
    db_session.flush()
    nilai = dict(closing_menu_id=menu.id, product_id=200104, multiplier=1)
    nilai.update(ubah)
    db_session.add(ClosingMenuProduct(**nilai))

    with pytest.raises(IntegrityError):
        db_session.flush()
