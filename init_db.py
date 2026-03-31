"""
Initialize database tables.

Usage:
    python init_db.py
"""

import pkgutil
import importlib

from app.database import Base, engine
import app.models  # root package


def load_models():
    """
    Auto import all modules in app.models
    biar SQLAlchemy register semua model
    """
    package = app.models

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{module_name}")


def init_db():
    print("🚀 Loading models...")
    load_models()

    print("🚀 Creating tables...")
    try:
        print("⚠️ Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully")
    except Exception as e:
        print("❌ Failed to initialize database")
        print(f"Error: {e}")


if __name__ == "__main__":
    init_db()