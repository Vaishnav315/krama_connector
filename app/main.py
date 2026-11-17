"""FastAPI Application Entry Point.

KRAMA Engineering Connector for Onshape CAD/PLM Systems.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.router import api_router
from app.config import get_settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    # Initialize database tables
    init_db()
    yield


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Production-grade read-only CAD/PLM connector between Onshape and KRAMA's "
        "engineering knowledge graph ingestion pipeline."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for web development and API exploration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount primary API router
app.include_router(api_router)


@app.get("/", include_in_schema=False)
def root():
    """Redirect root to interactive Swagger UI documentation."""
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
