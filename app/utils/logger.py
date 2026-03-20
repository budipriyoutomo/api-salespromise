import logging
import os
from app.config import settings

os.makedirs("logs", exist_ok=True)

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

logging.basicConfig(
    filename="logs/api.log",
    level=log_level,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("sync-api")
logger.setLevel(log_level)