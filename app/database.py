from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


def engine_options(s) -> dict:
    """Opsi engine dari settings.

    Pool berlaku per worker gunicorn: total koneksi = worker x (pool_size +
    max_overflow). Jaga di bawah `max_connections` Postgres.

    `statement_timeout` membuat query yang terlalu berat gagal cepat, bukan
    menahan koneksi sampai request lain ikut antre lalu gagal di pool.
    """
    opsi = {
        "pool_pre_ping": True,
        "pool_size": s.DB_POOL_SIZE,
        "max_overflow": s.DB_MAX_OVERFLOW,
        "pool_timeout": s.DB_POOL_TIMEOUT,
        "pool_recycle": s.DB_POOL_RECYCLE,
    }
    if s.DB_STATEMENT_TIMEOUT_MS > 0:
        opsi["connect_args"] = {"options": f"-c statement_timeout={s.DB_STATEMENT_TIMEOUT_MS}"}
    return opsi


engine = create_engine(settings.DATABASE_URL, **engine_options(settings))

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
