"""Sync orchestration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import SyncRequest, SyncResponse
from app.services.sync_service import SyncService

router = APIRouter(prefix="/projects", tags=["Sync Orchestration"])


@router.post("/{project_id}/sync", response_model=SyncResponse)
def trigger_sync(
    project_id: str,
    request: SyncRequest,
    db: Session = Depends(get_db),
) -> SyncResponse:
    """Trigger CAD synchronization for a linked document within a project."""
    sync_service = SyncService(db=db)
    try:
        sync_run, snap_record = sync_service.execute_sync(
            project_id=project_id,
            document_id=request.document_id,
            version_id=request.version_id,
            force=request.force,
        )
        msg = (
            "Synchronization completed successfully"
            if sync_run.status == "completed"
            else "Sync deduplicated: already at target version"
        )
        return SyncResponse(
            sync_run_id=sync_run.id,
            project_id=sync_run.project_id,
            document_id=sync_run.document_id,
            status=sync_run.status,
            version_id=sync_run.version_id,
            microversion_id=sync_run.microversion_id,
            snapshot_id=sync_run.snapshot_id,
            records_synced=sync_run.records_synced,
            duration_ms=sync_run.duration_ms,
            message=msg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync execution failed: {exc}",
        ) from exc
