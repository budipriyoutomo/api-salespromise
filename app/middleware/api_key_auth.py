from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings

EXCLUDED_PATHS = ("/docs", "/openapi", "/redoc")


class APIKeyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        if any(request.url.path.startswith(p) for p in EXCLUDED_PATHS):
            return await call_next(request)

        auth = request.headers.get("Authorization")

        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

        token = auth[len("Bearer "):]

        if not settings.API_KEY or token != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return await call_next(request)