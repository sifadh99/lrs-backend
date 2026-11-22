"""FastAPI application entry point.  Run locally:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from psycopg import Connection

from app.config import get_settings
from app.db import get_conn, pool

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()          # startup: open DB connections
    yield
    pool.close()         # shutdown: close them cleanly


app = FastAPI(title="Learning Resource Sharing API", version="0.1.0", lifespan=lifespan)

# The React app runs on another origin (port 5173 locally), so the browser needs CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["health"])
def healthz() -> dict:
    """Liveness: the process is up. Never touches the database."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz(response: Response, conn: Connection = Depends(get_conn)) -> dict:
    """Readiness: can we serve real traffic, i.e. does the database answer?"""
    try:
        conn.execute("SELECT 1")
        return {"status": "ready"}
    except Exception:  # noqa: BLE001 - any DB error means "not ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "database unavailable"}
