"""Snapshot retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import SnapshotSummary
from app.schemas.snapshot import Snapshot
from app.services.snapshot_service import SnapshotService

router = APIRouter(tags=["Snapshots"])


@router.get("/projects/{project_id}/snapshots", response_model=list[SnapshotSummary])
def list_project_snapshots(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[SnapshotSummary]:
    """Retrieve all snapshot summaries for a project in reverse chronological order."""
    snapshot_service = SnapshotService(db=db)
    records = snapshot_service.list_snapshots(project_id)
    return [
        SnapshotSummary(
            snapshot_id=r.id,
            project_id=r.project_id,
            document_id=r.document_id,
            version_id=r.version_id,
            version_name=r.version_name,
            microversion_id=r.microversion_id,
            element_id=r.element_id,
            total_mass=r.total_mass,
            instance_count=r.instance_count,
            component_count=r.component_count,
            extracted_at=r.extracted_at,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.get("/snapshots/{snapshot_id}", response_model=Snapshot)
def get_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
) -> Snapshot:
    """Retrieve complete canonical Snapshot JSON document by snapshot ID."""
    snapshot_service = SnapshotService(db=db)
    snapshot = snapshot_service.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot '{snapshot_id}' not found",
        )
    return snapshot
