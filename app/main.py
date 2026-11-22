"""FastAPI application entry point.  Run locally:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app import cache
from app.config import get_settings
from app.db import pool
from app.routers import auth, categories, resources

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()          # startup: open DB connections
    yield
    pool.close()         # shutdown: close them cleanly


app = FastAPI(title="GetCode API", version="0.1.0", lifespan=lifespan)

# The React app runs on another origin (port 5173 locally), so the browser needs CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(resources.router)
app.include_router(categories.router)


@app.get("/healthz", tags=["health"])
def healthz() -> dict:
    """Liveness: the process is up. Never touches the database."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz(response: Response) -> dict:
    """Readiness: can we serve real traffic, i.e. does the database answer?

    The cache is reported but never makes us "not ready": without Redis we are slower,
    not broken, and Kubernetes must not pull every pod out of service because of it.
    """
    # Borrow the connection INSIDE the try, with a short timeout. Through the Conn dependency
    # an empty pool would wait 30 s and then answer 500 instead of a quick 503.
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return {"status": "ready", "cache": cache.status()}
    except Exception:  # noqa: BLE001 - any DB error means "not ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "database unavailable"}
