from dotenv import load_dotenv
import os
from urllib.parse import quote_plus

load_dotenv()

class Settings:
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASS: str = os.getenv("DB_PASS", "")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO") 

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

        if missing:
            raise ValueError(f"Missing env: {', '.join(missing)}")


settings = Settings()
settings.validate()