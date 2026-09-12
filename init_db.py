"""
Initialize database tables.

Usage:
    python init_db.py

Secara default HANYA membuat tabel yang belum ada.

Untuk menghapus seluruh tabel lebih dulu (menghancurkan semua data), env
berikut harus diisi persis:

    INIT_DB_CONFIRM=DROP-ALL python init_db.py

Pagar ini ada karena versi sebelumnya memanggil `drop_all()` tanpa syarat —
satu kali salah jalan di server, seluruh data transaksi hilang.

Untuk perubahan skema di produksi, pakai file di `migrations/`, bukan skrip ini.
"""

import importlib
import os
import pkgutil

import app.models  # root package
from app.database import Base, engine

DROP_CONFIRMATION = "DROP-ALL"


def boleh_drop() -> bool:
    return os.getenv("INIT_DB_CONFIRM") == DROP_CONFIRMATION


def load_models():
    """
    Auto import all modules in app.models
    biar SQLAlchemy register semua model
    """
    package = app.models

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{module_name}")


def init_db():
    print("Loading models...")
    load_models()

    try:
        if boleh_drop():
            print("PERINGATAN: menghapus seluruh tabel...")
            Base.metadata.drop_all(bind=engine)
        else:
            print(f"Lewati drop_all (set INIT_DB_CONFIRM={DROP_CONFIRMATION} kalau memang diinginkan)")

        print("Creating tables...")
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully")

    except Exception as e:
        print("Failed to initialize database")
        print(f"Error: {e}")


if __name__ == "__main__":
    init_db()
