from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    API_KEY: str = os.getenv("API_KEY", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def validate(self):
        if not self.DATABASE_URL:
            raise ValueError("Environment variable DATABASE_URL is not set")
        if not self.API_KEY:
            raise ValueError("Environment variable API_KEY is not set")


settings = Settings()
settings.validate()