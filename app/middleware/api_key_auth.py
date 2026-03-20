from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.api_key import ApiKey

EXCLUDED_PATHS = ("/docs", "/openapi", "/redoc")


class APIKeyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        if any(request.url.path.startswith(p) for p in EXCLUDED_PATHS):
            return await call_next(request)

        auth = request.headers.get("Authorization")

        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

        token = auth[len("Bearer "):]

        db: Session = SessionLocal()
        try:
            api_key = db.query(ApiKey).filter(
                ApiKey.key == token,
                ApiKey.is_active == True
            ).first()
        finally:
            db.close()

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")

        # Simpan outlet_code ke request state
        # agar sync_routes bisa ambil langsung tanpa perlu dikirim di body
        request.state.outlet_code = api_key.outlet_code

        return await call_next(request)