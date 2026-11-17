"""Snapshot storage and retrieval service.

Provides lookup, deserialization, and comparison queries for versioned CAD snapshots.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.snapshot import SnapshotRecord
from app.schemas.diff import SnapshotDiff
from app.schemas.snapshot import Snapshot
from app.services.diff_service import SnapshotDiffEngine


class SnapshotService:
    """Manages snapshot queries and comparison operations."""

    def __init__(self, db: Session):
        self.db = db
        self.diff_engine = SnapshotDiffEngine()

    def get_snapshot_record(self, snapshot_id: str) -> SnapshotRecord | None:
        """Query snapshot record by ID."""
        return self.db.query(SnapshotRecord).filter(SnapshotRecord.id == snapshot_id).first()

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        """Retrieve and deserialize full canonical Snapshot object."""
        record = self.get_snapshot_record(snapshot_id)
        if not record:
            return None
        payload = json.loads(record.payload_json)
        return Snapshot.model_validate(payload)

    def list_snapshots(self, project_id: str) -> list[SnapshotRecord]:
        """List all snapshots associated with a project in chronological order."""
        return (
            self.db.query(SnapshotRecord)
            .filter(SnapshotRecord.project_id == project_id)
            .order_by(SnapshotRecord.created_at.desc())
            .all()
        )

    def compare_snapshots(self, base_snapshot_id: str, target_snapshot_id: str) -> SnapshotDiff:
        """Compare two stored snapshots and return structured SnapshotDiff."""
        base_snap = self.get_snapshot(base_snapshot_id)
        if not base_snap:
            raise ValueError(f"Base snapshot '{base_snapshot_id}' not found")

        target_snap = self.get_snapshot(target_snapshot_id)
        if not target_snap:
            raise ValueError(f"Target snapshot '{target_snapshot_id}' not found")

        return self.diff_engine.compare(base_snap, target_snap)
