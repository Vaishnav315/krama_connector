"""Snapshot comparison and change detection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document import LinkedDocument
from app.schemas.api import ChangeCheckResponse
from app.schemas.diff import SnapshotDiff
from app.services.snapshot_service import SnapshotService
from app.services.sync_service import SyncService

router = APIRouter(tags=["Diffs & Changes"])


@router.get("/snapshots/{snapshot_id}/diff/{other_snapshot_id}", response_model=SnapshotDiff)
def compare_snapshots(
    snapshot_id: str,
    other_snapshot_id: str,
    db: Session = Depends(get_db),
) -> SnapshotDiff:
    """Compare two versioned snapshots and return a deterministic difference report.

    Reports added, removed, moved instances, component definition changes, material modifications,
    and assembly-level mass and center-of-mass shifts.
    """
    snapshot_service = SnapshotService(db=db)
    try:
        return snapshot_service.compare_snapshots(
            base_snapshot_id=snapshot_id,
            target_snapshot_id=other_snapshot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Diff calculation failed: {exc}",
        ) from exc


@router.get("/projects/{project_id}/changes", response_model=ChangeCheckResponse)
def check_project_changes(
    project_id: str,
    db: Session = Depends(get_db),
) -> ChangeCheckResponse:
    """Check whether any linked documents in the project have newer source versions available."""
    docs = db.query(LinkedDocument).filter(LinkedDocument.project_id == project_id).all()
    sync_service = SyncService(db=db)
    change_detector = sync_service.change_detector

    results = []
    for d in docs:
        change_info = change_detector.check_for_changes(d)
        results.append(change_info)

    return ChangeCheckResponse(
        project_id=project_id,
        documents_checked=len(docs),
        changes=results,
    )
