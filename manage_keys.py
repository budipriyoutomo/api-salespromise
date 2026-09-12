"""
Manage API keys per outlet.

Usage:
    python manage_keys.py generate --outlet OUTLET_001
    python manage_keys.py list
    python manage_keys.py rotate --outlet OUTLET_001
    python manage_keys.py revoke --outlet OUTLET_001

Database hanya menyimpan HASH dari key. Key mentah ditampilkan sekali saja saat
dibuat — setelah itu tidak bisa dilihat lagi oleh siapa pun, termasuk admin.

Logikanya sama persis dengan endpoint `/api/api-keys`: keduanya memakai
`app/services/api_key_service.py`.
"""

import argparse

from app.database import SessionLocal
from app.services import api_key_service


def _tampilkan_key_baru(outlet_code: str, raw_key: str, judul: str):
    print(f"[+] {judul} untuk outlet '{outlet_code}'")
    print(f"    Key: {raw_key}")
    print("    Simpan key ini — tidak bisa dilihat lagi!")


def generate_key(outlet_code: str):
    db = SessionLocal()
    try:
        try:
            _, raw_key = api_key_service.create_key(db, outlet_code)
        except api_key_service.OutletSudahPunyaKey:
            existing = api_key_service.get_key(db, outlet_code)
            print(f"[!] Outlet '{outlet_code}' sudah punya key.")
            print(f"    Prefix: {existing.key_prefix or '-'}...")
            print(f"    Status: {'aktif' if existing.is_active else 'nonaktif'}")
            print("    Key mentah tidak bisa ditampilkan lagi — pakai 'rotate' kalau hilang.")
            return

        _tampilkan_key_baru(outlet_code, raw_key, "API key berhasil dibuat")

    finally:
        db.close()


def rotate_key(outlet_code: str):
    db = SessionLocal()
    try:
        try:
            _, raw_key = api_key_service.rotate_key(db, outlet_code)
        except api_key_service.OutletTidakDitemukan:
            print(f"[!] Outlet '{outlet_code}' tidak ditemukan.")
            return

        _tampilkan_key_baru(outlet_code, raw_key, "API key berhasil diganti")
        print("    Key lama sudah tidak berlaku.")

    finally:
        db.close()


def list_keys():
    db = SessionLocal()
    try:
        keys = api_key_service.list_keys(db)

        if not keys:
            print("Belum ada API key.")
            return

        print(f"{'Outlet':<20} {'Status':<10} {'Created At':<25} {'Key'}")
        print("-" * 90)
        for k in keys:
            status = "aktif" if k.is_active else "nonaktif"
            prefix = f"{k.key_prefix}..." if k.key_prefix else "(tersembunyi)"
            print(f"{k.outlet_code:<20} {status:<10} {str(k.created_at):<25} {prefix}")

    finally:
        db.close()


def revoke_key(outlet_code: str):
    db = SessionLocal()
    try:
        try:
            api_key_service.revoke_key(db, outlet_code)
        except api_key_service.OutletTidakDitemukan:
            print(f"[!] Outlet '{outlet_code}' tidak ditemukan.")
            return

        print(f"[+] API key untuk outlet '{outlet_code}' telah dinonaktifkan.")

    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage API keys")
    parser.add_argument("action", choices=["generate", "list", "rotate", "revoke"])
    parser.add_argument("--outlet", type=str, help="Outlet code")

    args = parser.parse_args(argv)

    if args.action == "list":
        list_keys()
        return

    if not args.outlet:
        print(f"[!] --outlet wajib diisi untuk action {args.action}")
        return

    if args.action == "generate":
        generate_key(args.outlet)
    elif args.action == "rotate":
        rotate_key(args.outlet)
    elif args.action == "revoke":
        revoke_key(args.outlet)


if __name__ == "__main__":
    main()
