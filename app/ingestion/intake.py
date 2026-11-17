"""KRAMA Ingestion Interface Stub.

This module implements the fixed intake interface required by KRAMA's ingestion pipeline.
The connector produces versioned snapshot artifacts and submits them via `intake_files`.
It never writes directly to KRAMA's internal knowledge graph.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestionFileRecord(BaseModel):
    """Metadata recorded for an ingested file artifact."""

    file_path: str
    size_bytes: int
    content_hash_sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionRun(BaseModel):
    """Result of submitting files to the KRAMA ingestion pipeline."""

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    source: Literal["connector"] = "connector"
    status: Literal["completed", "failed", "deduplicated"] = "completed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    file_count: int
    files: list[IngestionFileRecord]
    ingestion_metadata: dict[str, Any] = Field(default_factory=dict)


# In-memory deduplication cache for the ingestion stub to simulate KRAMA's idempotent behavior
_INGESTED_HASH_CACHE: dict[uuid.UUID, set[str]] = {}


def reset_ingestion_cache() -> None:
    """Utility function to clear in-memory ingestion cache (primarily for tests)."""
    _INGESTED_HASH_CACHE.clear()


def intake_files(
    *,
    project_id: uuid.UUID,
    files: list[tuple[str, bytes]],
    source: Literal["connector"],
    metadata_by_source_file: dict[str, dict[str, Any]] | None = None,
) -> IngestionRun:
    """Submit CAD snapshot files and associated provenance metadata to KRAMA ingestion.

    Parameters:
    - project_id: The UUID of the destination KRAMA engineering project.
    - files: List of (relative_path, content_bytes) tuples representing partitioned artifacts.
    - source: Must be literal "connector".
    - metadata_by_source_file: Optional dictionary mapping each file path to provenance metadata.

    Returns:
    - IngestionRun record describing the intake execution.
    """
    if source != "connector":
        raise ValueError(f"Invalid intake source: expected 'connector', got '{source}'")

    if not files:
        raise ValueError("Cannot ingest empty file list: at least one file artifact is required")

    file_records: list[IngestionFileRecord] = []
    metadata_by_file = metadata_by_source_file or {}

    # Calculate content hashes
    run_hashes: set[str] = set()
    for file_path, content in files:
        if not isinstance(content, bytes):
            raise TypeError(f"File content for '{file_path}' must be bytes, got {type(content)}")

        sha256 = hashlib.sha256(content).hexdigest()
        run_hashes.add(sha256)
        file_meta = metadata_by_file.get(file_path, {})
        file_records.append(
            IngestionFileRecord(
                file_path=file_path,
                size_bytes=len(content),
                content_hash_sha256=sha256,
                metadata=file_meta,
            )
        )

    # Check for deduplication (identical content submitted to the same project)
    existing_hashes = _INGESTED_HASH_CACHE.setdefault(project_id, set())
    status: Literal["completed", "deduplicated"] = "completed"
    if run_hashes and run_hashes.issubset(existing_hashes):
        status = "deduplicated"
    else:
        existing_hashes.update(run_hashes)

    return IngestionRun(
        project_id=project_id,
        source=source,
        status=status,
        file_count=len(file_records),
        files=file_records,
        ingestion_metadata={
            "submitted_file_names": [f[0] for f in files],
            "deduplicated": status == "deduplicated",
        },
    )
