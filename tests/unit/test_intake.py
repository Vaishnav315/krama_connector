"""Unit tests for the KRAMA ingestion stub interface."""

import uuid

import pytest

from app.ingestion.intake import intake_files, reset_ingestion_cache


def test_intake_files_success():
    """Verify intake_files accepts project UUID, files as (path, bytes), and metadata."""
    reset_ingestion_cache()
    project_id = uuid.uuid4()
    files = [
        ("assembly_snapshot.json", b'{"assembly": "test"}'),
        ("components.json", b'{"components": []}'),
    ]
    metadata = {
        "assembly_snapshot.json": {"source": "onshape", "version": "v1.0"},
    }

    run = intake_files(
        project_id=project_id,
        files=files,
        source="connector",
        metadata_by_source_file=metadata,
    )

    assert run.project_id == project_id
    assert run.source == "connector"
    assert run.status == "completed"
    assert run.file_count == 2
    assert len(run.files) == 2
    assert run.files[0].file_path == "assembly_snapshot.json"
    assert run.files[0].size_bytes == len(b'{"assembly": "test"}')
    assert run.files[0].metadata == {"source": "onshape", "version": "v1.0"}


def test_intake_files_deduplication():
    """Verify that re-submitting identical file content to the same project marks run as deduplicated."""
    reset_ingestion_cache()
    project_id = uuid.uuid4()
    files = [("test.json", b'{"data": "identical_content"}')]

    run1 = intake_files(project_id=project_id, files=files, source="connector")
    assert run1.status == "completed"

    run2 = intake_files(project_id=project_id, files=files, source="connector")
    assert run2.status == "deduplicated"


def test_intake_files_invalid_source():
    """Verify ValueError is raised if source is not 'connector'."""
    project_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Invalid intake source"):
        intake_files(
            project_id=project_id,
            files=[("f.json", b"{}")],
            source="manual_upload",  # type: ignore[arg-type]
        )


def test_intake_files_empty_files_rejected():
    """Verify ValueError is raised if file list is empty."""
    project_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Cannot ingest empty file list"):
        intake_files(project_id=project_id, files=[], source="connector")
