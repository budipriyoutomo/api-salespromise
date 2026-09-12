import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


def _split_csv(raw: str):
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """Konfigurasi aplikasi.

    Env dibaca di `__init__`, bukan sebagai atribut kelas. Dengan begitu
    `Settings()` bisa dibuat ulang di test dengan env yang berbeda tanpa perlu
    `importlib.reload` — reload menghasilkan objek `settings` baru sementara
    modul lain masih memegang yang lama, dan itu sumber kebocoran antar-test.
    """

    def __init__(self):
        # --- Database ---
        self.DB_USER: str = os.getenv("DB_USER", "")
        self.DB_PASS: str = os.getenv("DB_PASS", "")
        self.DB_HOST: str = os.getenv("DB_HOST", "localhost")
        self.DB_PORT: str = os.getenv("DB_PORT", "5432")
        self.DB_NAME: str = os.getenv("DB_NAME", "")

        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # --- Auth user (dashboard / frontend terpisah) ---
        self.JWT_SECRET: str = os.getenv("JWT_SECRET", "")
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        self.REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

        # --- RabbitMQ ---
        # Password sengaja tanpa default: lebih baik gagal terhubung daripada
        # menaruh kredensial di dalam kode.
        self.RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
        self.RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "maharasa")
        self.RABBITMQ_PASSWORD: str = os.getenv("RABBITMQ_PASSWORD", "")

        # --- Pembatasan percobaan login ---
        # 0 = mematikan pembatasan.
        self.LOGIN_MAX_ATTEMPTS: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))
        self.LOGIN_WINDOW_SECONDS: int = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

        # --- Batas payload sync ---
        self.MAX_SALES_PER_REQUEST: int = int(os.getenv("MAX_SALES_PER_REQUEST", "1000"))

        # --- CORS untuk frontend terpisah ---
        self.CORS_ORIGINS: list = _split_csv(os.getenv("CORS_ORIGINS", ""))

    @property
    def DATABASE_URL(self):
        password = quote_plus(self.DB_PASS)
        return (
            f"postgresql+psycopg2://{self.DB_USER}:"
            f"{password}@{self.DB_HOST}:"
            f"{self.DB_PORT}/{self.DB_NAME}"
        )

    def validate(self):
        missing = []
        if not self.DB_USER:
            missing.append("DB_USER")
        if not self.DB_PASS:
            missing.append("DB_PASS")
        if not self.DB_NAME:
            missing.append("DB_NAME")
        if not self.JWT_SECRET:
            missing.append("JWT_SECRET")

        if missing:
            raise ValueError(f"Missing env: {', '.join(missing)}")


settings = Settings()
settings.validate()
