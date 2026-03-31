from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routes import analyze, health
from api.routes.history import router as history_router
from api.db.connection import get_pool, close_pool
from api.core.cache import get_redis, close_redis
from api.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print("Starting QuerySense API...")
    await get_pool()        # warm up Postgres connection pool
    await get_redis()       # warm up Redis connection
    print("Postgres connected.")
    print("Redis connected.")
    print(f"Running on http://{settings.api_host}:{settings.api_port}")
    print("Docs at http://localhost:8000/docs")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    print("Shutting down...")
    await close_pool()
    await close_redis()
    print("Connections closed.")


app = FastAPI(
    title="QuerySense",
    description="PostgreSQL query analyzer — plain English diagnosis + AI-powered fixes",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# allow_origins=["*"] lets the HTML file work when opened directly from disk
# (file:// origin) and from any future deployment URL
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(analyze.router, prefix="/api/v1", tags=["Analysis"])
app.include_router(health.router, tags=["Health"])
app.include_router(history_router)


@app.get("/")
async def root():
    return {
        "name": "QuerySense",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "analyze": "/api/v1/analyze",
        "history": "/api/v1/history",
    }