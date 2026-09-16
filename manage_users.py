"""
Manage user dashboard (login frontend).

Usage:
    python manage_users.py create --email admin@maharasa.id --role admin
    python manage_users.py create --email kasir@maharasa.id --role outlet --outlet OUTLET_001
    python manage_users.py list
    python manage_users.py password --email admin@maharasa.id
    python manage_users.py deactivate --email admin@maharasa.id
    python manage_users.py activate --email admin@maharasa.id
    python manage_users.py delete --email seed@maharasa.id [--yes]

Password dimasukkan lewat prompt (tidak terlihat di shell history) atau
lewat --password untuk keperluan otomatisasi.

Role:
    admin   — akses penuh semua outlet
    manager — baca data semua outlet
    outlet  — baca data outletnya sendiri (wajib --outlet)

Logikanya sama persis dengan endpoint `/api/users`: keduanya memakai
`app/services/user_service.py`.
"""

import argparse
import getpass
import sys

from app.database import SessionLocal
from app.models.user import ROLE_OUTLET
from app.services import user_service

MIN_PASSWORD_LENGTH = user_service.MIN_PASSWORD_LENGTH


def _read_password(provided=None):
    if provided:
        return provided

    password = getpass.getpass("Password: ")
    ulangi = getpass.getpass("Ulangi password: ")

    if password != ulangi:
        print("[!] Password tidak sama.")
        return None

    return password


def create_user(email: str, role: str, outlet_code=None, password=None, full_name=None):
    password = _read_password(password)
    if password is None:
        return

    db = SessionLocal()
    try:
        try:
            user = user_service.create_user(
                db,
                email=email,
                password=password,
                role=role,
                outlet_code=outlet_code,
                full_name=full_name,
            )
        except user_service.EmailSudahTerdaftar:
            print(f"[!] Email '{user_service.normalize_email(email)}' sudah terdaftar.")
            return
        except user_service.DataTidakValid as exc:
            print(f"[!] {exc}")
            return

        print(f"[+] User '{user.email}' dibuat dengan role '{user.role}'")

    finally:
        db.close()


def list_users():
    db = SessionLocal()
    try:
        users = user_service.list_users(db)

        if not users:
            print("Belum ada user.")
            return

        print(f"{'Email':<35} {'Role':<10} {'Outlet':<15} {'Status'}")
        print("-" * 75)
        for u in users:
            status = "aktif" if u.is_active else "nonaktif"
            print(f"{u.email:<35} {u.role:<10} {(u.outlet_code or '-'):<15} {status}")

    finally:
        db.close()


def change_password(email: str, password=None):
    password = _read_password(password)
    if password is None:
        return

    db = SessionLocal()
    try:
        user = user_service.get_by_email(db, email)

        if not user:
            print(f"[!] User '{user_service.normalize_email(email)}' tidak ditemukan.")
            return

        try:
            user_service.set_password(db, user.id, password)
        except user_service.DataTidakValid as exc:
            print(f"[!] {exc}")
            return

        print(f"[+] Password '{user.email}' diperbarui.")

    finally:
        db.close()


def set_active(email: str, is_active: bool):
    db = SessionLocal()
    try:
        try:
            user = user_service.set_active(db, email, is_active)
        except user_service.UserTidakDitemukan:
            print(f"[!] User '{user_service.normalize_email(email)}' tidak ditemukan.")
            return
        except user_service.MenguncilDiriSendiri as exc:
            print(f"[!] {exc}")
            return

        print(f"[+] User '{user.email}' sekarang {'aktif' if is_active else 'nonaktif'}.")

    finally:
        db.close()


def delete_user(email: str, konfirmasi: bool = False):
    email = user_service.normalize_email(email)

    # Hapus tidak bisa dibatalkan, jadi "y" saja tidak cukup — email harus
    # diketik ulang, supaya salah sasaran ketahuan sebelum terlambat.
    if not konfirmasi:
        ketikan = input(f"Hapus permanen '{email}'? Ketik ulang emailnya untuk konfirmasi: ")
        if user_service.normalize_email(ketikan) != email:
            print("[!] Dibatalkan — email yang diketik tidak sama.")
            return

    db = SessionLocal()
    try:
        try:
            user_service.delete_user(db, email)
        except user_service.UserTidakDitemukan:
            print(f"[!] User '{email}' tidak ditemukan.")
            return
        except user_service.MenguncilDiriSendiri as exc:
            print(f"[!] {exc}")
            return

        print(f"[+] User '{email}' dihapus.")

    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage user dashboard")
    parser.add_argument("action", choices=["create", "list", "password", "activate", "deactivate", "delete"])
    parser.add_argument("--email", type=str)
    parser.add_argument("--role", type=str, default=ROLE_OUTLET)
    parser.add_argument("--outlet", type=str)
    parser.add_argument("--password", type=str, help="Isi langsung; kalau kosong akan ditanya lewat prompt")
    parser.add_argument("--name", type=str)
    parser.add_argument("--yes", action="store_true", help="Lewati konfirmasi delete")

    args = parser.parse_args(argv)

    if args.action == "list":
        list_users()
        return

    if not args.email:
        print(f"[!] --email wajib diisi untuk action {args.action}")
        return

    if args.action == "create":
        create_user(
            email=args.email,
            role=args.role,
            outlet_code=args.outlet,
            password=args.password,
            full_name=args.name,
        )
    elif args.action == "password":
        change_password(email=args.email, password=args.password)
    elif args.action == "activate":
        set_active(args.email, True)
    elif args.action == "deactivate":
        set_active(args.email, False)
    elif args.action == "delete":
        delete_user(args.email, konfirmasi=args.yes)


if __name__ == "__main__":
    main(sys.argv[1:])
