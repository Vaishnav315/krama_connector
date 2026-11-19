"""Sync orchestration service.

Extracts CAD snapshots via the connector adapter, records audit trails in SQLAlchemy,
and dispatches partitioned artifacts to KRAMA's intake_files pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.freecad.adapter import FreeCADConnector
from app.connectors.onshape.adapter import OnshapeConnector
from app.connectors.onshape.client import OnshapeClient
from app.ingestion.intake import intake_files
from app.models.connection import Connection
from app.models.document import LinkedDocument
from app.models.snapshot import SnapshotRecord
from app.models.sync_run import SyncRun
from app.schemas.snapshot import Snapshot
from app.services.change_detection import ChangeDetectionService

logger = logging.getLogger(__name__)


class SyncService:
    """Coordinates snapshot extraction, persistence, and ingestion dispatch."""

    def __init__(self, db: Session, connector: OnshapeConnector | FreeCADConnector | None = None):
        self.db = db
        if connector is not None:
            self.connector = connector
        else:
            settings = get_settings()
            # In test environments or when explicitly flagged, use recorded fixtures
            if settings.ENVIRONMENT == "test" or settings.USE_MOCK_ONSHAPE or not (settings.ONSHAPE_ACCESS_KEY and settings.ONSHAPE_SECRET_KEY):
                self.connector = OnshapeConnector(use_fixtures=True)
            else:
                live_client = OnshapeClient(
                    base_url=settings.ONSHAPE_BASE_URL,
                    access_key=settings.ONSHAPE_ACCESS_KEY,
                    secret_key=settings.ONSHAPE_SECRET_KEY,
                    oauth_token=settings.ONSHAPE_OAUTH_TOKEN,
                )
                self.connector = OnshapeConnector(client=live_client, use_fixtures=False)
        self.change_detector = ChangeDetectionService(self.connector)

    def _resolve_connector(self, doc: LinkedDocument) -> OnshapeConnector | FreeCADConnector:
        """Select the right connector based on the connection provider.

        For FreeCAD connections the base_url column holds the live_state.json watch
        file path recorded at connection registration time.
        For Onshape connections the already-constructed self.connector is re-used.
        """
        connection: Connection | None = (
            self.db.query(Connection).filter(Connection.id == doc.connection_id).first()
        )
        if connection and connection.provider == "freecad":
            return FreeCADConnector(watch_file=connection.base_url)
        return self.connector

    def execute_sync(
        self,
        project_id: str,
        document_id: str,
        version_id: str | None = None,
        force: bool = False,
    ) -> tuple[SyncRun, SnapshotRecord | None]:
        """Execute synchronization for a linked document.

        Args:
            project_id: KRAMA project UUID string.
            document_id: Database LinkedDocument primary key or Onshape document ID.
            version_id: Specific version to extract; if None, uses latest committed version.
            force: If True, forces snapshot extraction even if already synced.

        Returns:
            Tuple of (SyncRun, SnapshotRecord or None if skipped/failed).
        """
        # Look up linked document
        doc = (
            self.db.query(LinkedDocument)
            .filter(
                (LinkedDocument.project_id == project_id)
                & ((LinkedDocument.id == document_id) | (LinkedDocument.document_id == document_id))
            )
            .first()
        )
        if not doc:
            raise ValueError(f"Linked document '{document_id}' not found for project '{project_id}'")

        # Resolve target version
        target_version = version_id
        if not target_version:
            versions = self.connector.get_versions(doc.document_id)
            target_version = versions[0]["id"] if versions else "latest"

        # Check for changes if not forced
        if not force and doc.last_synced_version_id == target_version:
            # Document is already synced to this exact version
            sync_run = SyncRun(
                project_id=project_id,
                document_id=doc.id,
                status="deduplicated",
                version_id=target_version,
                microversion_id=doc.last_synced_microversion_id,
                records_synced=0,
                duration_ms=0.0,
            )
            self.db.add(sync_run)
            self.db.commit()
            self.db.refresh(sync_run)
            logger.info("Sync skipped: Document %s already at version %s", doc.document_id, target_version)
            # Return most recent snapshot for this version if available
            existing_snap = (
                self.db.query(SnapshotRecord)
                .filter(
                    (SnapshotRecord.document_id == doc.id)
                    & (SnapshotRecord.version_id == target_version)
                )
                .order_by(SnapshotRecord.created_at.desc())
                .first()
            )
            return sync_run, existing_snap

        start_time = time.perf_counter()
        sync_run = SyncRun(
            project_id=project_id,
            document_id=doc.id,
            status="running",
            version_id=target_version,
        )
        self.db.add(sync_run)
        self.db.commit()

        try:
            # 1. Select the right connector for the linked document's provider
            #    (FreeCAD connections store the watch_file path in base_url)
            active_connector = self._resolve_connector(doc)

            # 2. Extract canonical snapshot via connector adapter
            snapshot: Snapshot = active_connector.extract_snapshot(
                document_reference=doc.document_id,
                version_reference=target_version,
                element_reference=doc.element_id,
            )

            # 3. Persist snapshot record in DB
            snap_record = SnapshotRecord(
                id=snapshot.snapshot_id,
                project_id=project_id,
                document_id=doc.id,
                version_id=snapshot.document.version_id,
                version_name=snapshot.document.version_name,
                microversion_id=snapshot.document.microversion_id,
                element_id=snapshot.document.element_id,
                total_mass=snapshot.assembly_mass_properties.mass if snapshot.assembly_mass_properties else None,
                instance_count=len(snapshot.assembly.instances),
                component_count=len(snapshot.components),
                payload_json=snapshot.to_deterministic_json(),
                extracted_at=snapshot.extracted_at,
            )
            self.db.add(snap_record)

            # 4. Partition snapshot into artifacts and dispatch to KRAMA intake interface
            provider = active_connector.__class__.__name__.lower().replace("connector", "")
            files = snapshot.partition_for_intake()
            metadata = {
                f_name: {
                    "source": provider,
                    "snapshot_id": snapshot.snapshot_id,
                    "version_id": target_version,
                    "extracted_at": snapshot.extracted_at.isoformat(),
                }
                for f_name, _ in files
            }

            intake_run = intake_files(
                project_id=uuid.UUID(project_id),
                files=files,
                source="connector",
                metadata_by_source_file=metadata,
            )

            # 5. Update linked document sync state
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            doc.last_synced_version_id = snapshot.document.version_id
            doc.last_synced_microversion_id = snapshot.document.microversion_id
            doc.last_synced_at = datetime.now(UTC)

            # 5. Finalize sync run record
            sync_run.status = "completed" if intake_run.status == "completed" else "deduplicated"
            sync_run.snapshot_id = snapshot.snapshot_id
            sync_run.microversion_id = snapshot.document.microversion_id
            sync_run.records_synced = len(snapshot.assembly.instances) + len(snapshot.components)
            sync_run.duration_ms = duration_ms

            self.db.commit()
            self.db.refresh(sync_run)
            self.db.refresh(snap_record)

            return sync_run, snap_record

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            sync_run.status = "failed"
            sync_run.duration_ms = duration_ms
            sync_run.error_message = str(exc)
            self.db.commit()
            logger.exception("Sync run failed for document %s: %s", doc.document_id, exc)
            raise
