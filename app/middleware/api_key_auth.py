from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings


class APIKeyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi"):
            return await call_next(request)

        auth = request.headers.get("Authorization")

        if not auth:
            raise HTTPException(status_code=401, detail="Missing Authorization")

        token = auth.replace("Bearer ", "")

        if token != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")

        response = await call_next(request)

        return response