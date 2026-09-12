"""Logika pengelolaan API key outlet.

Dipakai bersama oleh route `/api/api-keys` dan CLI `manage_keys.py`, supaya
aturan seperti "tidak boleh menimpa key yang sudah ada" hanya ditulis sekali.

Key mentah tidak pernah tersimpan. Fungsi yang membuat key mengembalikan
`(api_key_row, raw_key)` — pemanggil bertanggung jawab menampilkan `raw_key`
tepat sekali, lalu melupakannya.
"""

from app.core import security
from app.core.time import utcnow
from app.models.api_key import ApiKey


class OutletSudahPunyaKey(Exception):
    """Outlet sudah punya key. Menimpanya akan memutus mesin POS di lapangan."""


class OutletTidakDitemukan(Exception):
    pass


def list_keys(db):
    return db.query(ApiKey).order_by(ApiKey.outlet_code).all()


def get_key(db, outlet_code: str):
    return db.query(ApiKey).filter(ApiKey.outlet_code == outlet_code).first()


def _pasang_key_baru(api_key: ApiKey, raw_key: str):
    api_key.key_hash = security.hash_api_key(raw_key)
    api_key.key_prefix = security.api_key_prefix(raw_key)
    api_key.is_active = True
    api_key.updated_at = utcnow()


def create_key(db, outlet_code: str):
    """Buat key untuk outlet yang belum punya. Mengembalikan `(row, raw_key)`."""
    if get_key(db, outlet_code):
        raise OutletSudahPunyaKey(outlet_code)

    raw_key = security.generate_api_key()

    api_key = ApiKey(
        key_hash=security.hash_api_key(raw_key),
        key_prefix=security.api_key_prefix(raw_key),
        outlet_code=outlet_code,
        is_active=True,
        created_at=utcnow(),
    )

    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return api_key, raw_key


def rotate_key(db, outlet_code: str):
    """Ganti key outlet dengan yang baru. Key lama langsung tidak berlaku.

    Ini juga satu-satunya cara memulihkan outlet yang key-nya sudah direvoke —
    key lamanya sudah tidak diketahui siapa pun, jadi "mengaktifkan kembali"
    tidak ada gunanya.
    """
    api_key = get_key(db, outlet_code)

    if not api_key:
        raise OutletTidakDitemukan(outlet_code)

    raw_key = security.generate_api_key()
    _pasang_key_baru(api_key, raw_key)

    db.commit()
    db.refresh(api_key)

    return api_key, raw_key


def revoke_key(db, outlet_code: str):
    api_key = get_key(db, outlet_code)

    if not api_key:
        raise OutletTidakDitemukan(outlet_code)

    api_key.is_active = False
    api_key.updated_at = utcnow()

    db.commit()
    db.refresh(api_key)

    return api_key
