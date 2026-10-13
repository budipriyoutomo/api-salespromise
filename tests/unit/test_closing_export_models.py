"""Test constraint model log kirim rekap closing (TODO Fase 8).

Dijalankan di SQLite; constraint yang sama ada di migrations/016_closing_export_logs.sql.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.closing_report import ClosingExportLog


def _log(**ubah):
    nilai = dict(
        outlet_code="STTSM",
        production_date=date(2026, 10, 2),
        sequence=1,
        message_id=uuid.uuid4(),
        content_hash="a" * 64,
        item_count=2,
        payload={"items": []},
        status="mengirim",
        sent_by="admin@maharasa.id",
    )
    nilai.update(ubah)
    return ClosingExportLog(**nilai)


def test_log_tersimpan_dengan_default(db_session):
    db_session.add(_log())
    db_session.commit()

    log = db_session.query(ClosingExportLog).one()
    assert log.attempts == 0
    assert log.created_at is not None
    assert log.started_at is not None
    assert log.finished_at is None
    assert log.payload == {"items": []}


@pytest.mark.parametrize("status", ["mengirim", "terkirim", "duplikat", "gagal"])
def test_status_yang_dikenal_diterima(db_session, status):
    db_session.add(_log(status=status))
    db_session.commit()


def test_status_tidak_dikenal_ditolak(db_session):
    db_session.add(_log(status="selesai"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_id_unik(db_session):
    message_id = uuid.uuid4()
    db_session.add(_log(message_id=message_id))
    db_session.add(_log(message_id=message_id, sequence=2))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_sequence_unik_per_outlet_dan_tanggal(db_session):
    db_session.add(_log(sequence=1))
    db_session.add(_log(sequence=1))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_sequence_sama_beda_outlet_atau_tanggal_diterima(db_session):
    db_session.add(_log(sequence=1))
    db_session.add(_log(sequence=1, outlet_code="LAIN"))
    db_session.add(_log(sequence=1, production_date=date(2026, 10, 3)))
    db_session.commit()


@pytest.mark.parametrize("ubah", [{"sequence": 0}, {"attempts": -1}])
def test_sequence_positif_dan_attempts_tidak_negatif(db_session, ubah):
    db_session.add(_log(**ubah))
    with pytest.raises(IntegrityError):
        db_session.commit()
