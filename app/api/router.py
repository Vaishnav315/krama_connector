"""Combined API router mounting all route controllers."""

from fastapi import APIRouter

from app.api.routes.connections import router as connections_router
from app.api.routes.diffs import router as diffs_router
from app.api.routes.health import router as health_router
from app.api.routes.projects import router as projects_router
from app.api.routes.snapshots import router as snapshots_router
from app.api.routes.sync import router as sync_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(connections_router)
api_router.include_router(projects_router)
api_router.include_router(sync_router)
api_router.include_router(snapshots_router)
api_router.include_router(diffs_router)
