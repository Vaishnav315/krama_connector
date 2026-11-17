"""Health check endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.config import get_settings
from app.schemas.api import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Retrieve service health status, version, and current environment."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(UTC),
    )
