"""
Manage API keys per outlet.

Usage:
    python manage_keys.py generate --outlet OUTLET_001
    python manage_keys.py list
    python manage_keys.py revoke --outlet OUTLET_001
"""

import argparse
import secrets
from datetime import datetime

from app.database import SessionLocal
from app.models.api_key import ApiKey


def generate_key(outlet_code: str):
    db = SessionLocal()
    try:
        existing = db.query(ApiKey).filter(ApiKey.outlet_code == outlet_code).first()
        if existing:
            print(f"[!] Outlet '{outlet_code}' sudah punya key.")
            print(f"    Key   : {existing.key}")
            print(f"    Status: {'aktif' if existing.is_active else 'nonaktif'}")
            return

        new_key = secrets.token_urlsafe(32)

        api_key = ApiKey(
            key=new_key,
            outlet_code=outlet_code,
            is_active=True,
            created_at=datetime.utcnow()
        )

        db.add(api_key)
        db.commit()

        print(f"[+] API key berhasil dibuat untuk outlet '{outlet_code}'")
        print(f"    Key: {new_key}")
        print(f"    Simpan key ini — tidak bisa dilihat lagi!")

    finally:
        db.close()


def list_keys():
    db = SessionLocal()
    try:
        keys = db.query(ApiKey).order_by(ApiKey.outlet_code).all()

        if not keys:
            print("Belum ada API key.")
            return

        print(f"{'Outlet':<20} {'Status':<10} {'Created At':<25} {'Key'}")
        print("-" * 90)
        for k in keys:
            status = "aktif" if k.is_active else "nonaktif"
            print(f"{k.outlet_code:<20} {status:<10} {str(k.created_at):<25} {k.key}")

    finally:
        db.close()


def revoke_key(outlet_code: str):
    db = SessionLocal()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.outlet_code == outlet_code).first()

        if not api_key:
            print(f"[!] Outlet '{outlet_code}' tidak ditemukan.")
            return

        api_key.is_active = False
        db.commit()

        print(f"[+] API key untuk outlet '{outlet_code}' telah dinonaktifkan.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage API keys")
    parser.add_argument("action", choices=["generate", "list", "revoke"])
    parser.add_argument("--outlet", type=str, help="Outlet code")

    args = parser.parse_args()

    if args.action == "generate":
        if not args.outlet:
            print("[!] --outlet wajib diisi untuk action generate")
        else:
            generate_key(args.outlet)

    elif args.action == "list":
        list_keys()

    elif args.action == "revoke":
        if not args.outlet:
            print("[!] --outlet wajib diisi untuk action revoke")
        else:
            revoke_key(args.outlet)