from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.routes.sync_routes import router as sync_router
from app.middleware.api_key_auth import APIKeyMiddleware


app = FastAPI(
    title="Sales Sync API",
    version="1.0.0"
)

app.add_middleware(APIKeyMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(sync_router)


@app.get("/")
def health():
    return {"status": "ok"}