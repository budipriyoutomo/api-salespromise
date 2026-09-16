"""
Konfigurasi global pytest.

PENTING: env di-set di sini SEBELUM `app.config` di-import.
`app/config.py` memanggil `settings.validate()` saat import, dan
`load_dotenv()` tidak menimpa env yang sudah ada (override=False),
jadi nilai di bawah ini yang dipakai — bukan `.env` milik developer.
"""

import os

os.environ["DB_USER"] = "test_user"
os.environ["DB_PASS"] = "test_pass"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "test_db"
os.environ["LOG_LEVEL"] = "WARNING"
# Test sengaja memicu LOGIN GAGAL dsb. — jangan sampai tercampur ke logs/api.log developer.
os.environ["LOG_FILE"] = os.devnull

os.environ["JWT_SECRET"] = "secret-khusus-test-jangan-dipakai-di-produksi"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
os.environ["CORS_ORIGINS"] = "http://localhost:3000,https://dashboard.maharasa.id"

os.environ["RABBITMQ_HOST"] = "test-rabbit"
os.environ["RABBITMQ_USER"] = "test-user"
os.environ["RABBITMQ_PASSWORD"] = "test-pass"

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import security  # noqa: E402
from app.database import Base  # noqa: E402
from app.models.api_key import ApiKey  # noqa: E402
from app.models.product_group_mapping import ProductGroupMapping  # noqa: E402
from app.models.sales import Sales  # noqa: E402
from app.models.sales_items import SalesItems  # noqa: E402
from app.models.user import User  # noqa: E402

# ---------------------------------------------------------------------------
# Database in-memory (SQLite)
# ---------------------------------------------------------------------------
# Dipakai untuk query baca dan route yang memakai SQL standar.
#
# CATATAN: `sync_sales` memakai `on_conflict_do_update` — dialek PostgreSQL —
# sehingga TIDAK bisa diuji di sini. Lihat tests/unit/test_sales_service_sync.py
# (statement-level, session di-mock) dan tests/integration/ (Postgres asli).


@pytest.fixture()
def db_session():
    """Session lepas untuk test service."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)

    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def app_db():
    """Session yang dipakai bersama antara test dan aplikasi.

    StaticPool menjaga semua koneksi menunjuk database in-memory yang sama,
    sehingga baris yang di-seed test terlihat oleh request yang dilayani app.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Builder data uji
# ---------------------------------------------------------------------------


def make_sale_row(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 15), **overrides):
    """Baris `ordertransaction` untuk diisi langsung ke DB test."""
    values = dict(
        transaction_id=transaction_id,
        outlet_code=outlet_code,
        sale_date=sale_date,
        shop_id=1,
        receipt_total_amount=150000,
        receipt_pay_price=150000,
    )
    values.update(overrides)
    return Sales(**values)


def make_item_row(
    order_detail_id=1,
    transaction_id=1,
    product_group="COLORPLATE",
    product_name="RED",
    qty=2,
    sale_date=date(2026, 1, 15),
    **overrides,
):
    """Baris `orderdetail` untuk diisi langsung ke DB test."""
    values = dict(
        order_detail_id=order_detail_id,
        transaction_id=transaction_id,
        sale_date=sale_date,
        product_id=101,
        product_group=product_group,
        product_name=product_name,
        qty=qty,
        price=75000,
        retail_price=75000,
    )
    values.update(overrides)
    return SalesItems(**values)


@pytest.fixture()
def sale_factory():
    return make_sale_row


@pytest.fixture()
def item_factory():
    return make_item_row


@pytest.fixture()
def persisted_sales(app_db):
    """Baris `ordertransaction` yang sudah tersimpan.

    Penting untuk test response model: default kolom SQLAlchemy baru terisi
    saat INSERT, jadi objek yang belum disimpan punya banyak kolom `None`.
    """

    def _make(jumlah=1, transaction_id=1, outlet_code="OUTLET_001"):
        rows = [
            make_sale_row(transaction_id=transaction_id + i, outlet_code=outlet_code)
            for i in range(jumlah)
        ]
        app_db.add_all(rows)
        app_db.commit()
        for row in rows:
            app_db.refresh(row)
        return rows

    return _make


# ---------------------------------------------------------------------------
# Identitas: API key outlet & user dashboard
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_api_key(app_db):
    """Buat API key outlet di DB test. Mengembalikan key mentahnya.

    DB hanya menyimpan hash — sama seperti produksi.
    """

    def _make(outlet_code="OUTLET_001", is_active=True, raw_key=None):
        raw_key = raw_key or security.generate_api_key()
        app_db.add(
            ApiKey(
                key_hash=security.hash_api_key(raw_key),
                key_prefix=security.api_key_prefix(raw_key),
                outlet_code=outlet_code,
                is_active=is_active,
                created_at=datetime(2026, 1, 1),
            )
        )
        app_db.commit()
        return raw_key

    return _make


@pytest.fixture()
def make_user(app_db):
    """Buat user dashboard di DB test. Mengembalikan objek User."""

    def _make(
        email="admin@maharasa.id",
        password="rahasia123",
        role="admin",
        outlet_code=None,
        is_active=True,
        full_name="Pengguna Uji",
    ):
        user = User(
            email=email,
            password_hash=security.hash_password(password),
            full_name=full_name,
            role=role,
            outlet_code=outlet_code,
            is_active=is_active,
            created_at=datetime(2026, 1, 1),
        )
        app_db.add(user)
        app_db.commit()
        app_db.refresh(user)
        return user

    return _make


@pytest.fixture()
def make_product_group(app_db):
    """Baris `product_group_mappings` di DB test.

    DB test dibuat lewat `create_all`, bukan migrasi — jadi seed COLORPLATE
    dari migrasi 006 TIDAK ada di sini. Test yang butuh group aktif (mis.
    publish) wajib membuatnya sendiri.
    """

    def _make(product_group="COLORPLATE", is_active=True):
        row = ProductGroupMapping(
            product_group=product_group,
            is_active=is_active,
            created_at=datetime(2026, 1, 1),
        )
        app_db.add(row)
        app_db.commit()
        app_db.refresh(row)
        return row

    return _make


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def token_for():
    """Access token untuk sebuah User, tanpa lewat endpoint login."""

    def _token(user):
        return security.create_access_token(
            subject=user.email,
            role=user.role,
            outlet_code=user.outlet_code,
        )

    return _token


# ---------------------------------------------------------------------------
# Client aplikasi
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(app_db):
    """TestClient untuk `app.main.app` dengan `get_db` diarahkan ke DB test."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: app_db

    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def api_key_headers(make_api_key):
    """Header Bearer berisi API key outlet yang aktif (untuk endpoint mesin POS)."""
    return bearer(make_api_key(outlet_code="OUTLET_001"))


@pytest.fixture()
def admin_headers(make_user, token_for):
    """Header Bearer berisi JWT milik user admin (untuk endpoint dashboard)."""
    return bearer(token_for(make_user(email="admin@maharasa.id", role="admin")))
