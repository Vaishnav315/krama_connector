#!/usr/bin/env python3
"""Verification Test Suite for FreeCAD-to-KRAMA Bridge.

Demonstrates:
  1. Universal FreeCAD extraction and KRAMA snapshot creation.
  2. B-Rep to canonical units normalization (mm -> m, mm³ -> m³).
  3. KRAMA SnapshotDiffEngine detecting component movements and centroid shifts.
  4. KRAMA intake_files() ingestion of partitioned snapshot artifacts.

Can be run standalone with any standard Python 3.11+:
  python test_bridge.py
"""

import copy
import glob
import os
import sys
import uuid

# ---------------------------------------------------------------------------
# Setup sys.path to access krama_onshape_connector and its virtual environment
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_KRAMA_ROOT = None
for candidate in [
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_onshape_connector")),
]:
    if os.path.exists(os.path.join(candidate, "app", "schemas")):
        _KRAMA_ROOT = candidate
        break

if not _KRAMA_ROOT:
    _KRAMA_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_onshape_connector"))

if _KRAMA_ROOT not in sys.path:
    sys.path.insert(0, _KRAMA_ROOT)

_venv_site_packages = glob.glob(os.path.join(_KRAMA_ROOT, ".venv", "lib", "python*", "site-packages"))
for _sp in _venv_site_packages:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

sys.path.insert(0, _THIS_DIR)

from freecad_connector import FreeCADConnector

from app.ingestion.intake import intake_files
from app.services.diff_service import SnapshotDiffEngine


def test_freecad_connector_live_state():
    """Test extraction of Snapshot from live_state.json."""
    watch_file = os.path.join(_THIS_DIR, "live_state.json")
    assert os.path.exists(watch_file), f"Watch file not found: {watch_file}"

    connector = FreeCADConnector(watch_file=watch_file)
    snap = connector.extract_snapshot(
        document_reference=watch_file,
        version_reference="test_v1",
    )

    print("\n--- 1. Snapshot Extraction ---")
    print(f"Snapshot ID : {snap.snapshot_id}")
    print(f"Source      : {snap.source}")
    print(f"Document    : {snap.document.document_name}")
    print(f"Components  : {len(snap.components)}")
    print(f"Instances   : {len(snap.assembly.instances)}")

    assert snap.source == "freecad"
    assert len(snap.components) > 0, "Expected at least 1 component definition"
    assert len(snap.assembly.instances) > 0, "Expected at least 1 instance in hierarchy"
    assert snap.units.length == "meter"
    assert snap.units.mass == "kilogram"
    print("✓ Snapshot extraction verified")
    return snap


def test_krama_diff_engine(snap_v1):
    """Test change detection and diffing using KRAMA SnapshotDiffEngine."""
    print("\n--- 2. KRAMA Diff Engine Change Detection ---")
    snap_v2 = copy.deepcopy(snap_v1)
    snap_v2.snapshot_id = str(uuid.uuid4())
    snap_v2.document.version_name = "test_v2"

    # Select the first instance and shift its Z-coordinate by +10.0 mm (+0.010 m)
    target_inst = snap_v2.assembly.instances[0]
    inst_name = target_inst.name
    old_z = target_inst.transform[11]
    new_z = old_z + 0.010  # 10 mm in meters
    target_inst.transform[11] = new_z

    diff_engine = SnapshotDiffEngine(spatial_tolerance=1e-5, mass_tolerance=1e-4)
    diff = diff_engine.compare(snap_v1, snap_v2)

    print(f"Moved instance target: {inst_name}")
    print(f"Old translation Z    : {old_z:.6f} m")
    print(f"New translation Z    : {new_z:.6f} m")
    print(f"Diff summary         : {diff.summary}")

    assert diff.summary["moved_instances"] == 1, f"Expected 1 moved instance, got {diff.summary['moved_instances']}"
    moved = diff.moved_instances[0]
    assert moved.name == inst_name
    delta_z_mm = (moved.new_transform[11] - moved.old_transform[11]) * 1000.0
    print(f"Detected Δ translation: {delta_z_mm:.3f} mm")
    assert abs(delta_z_mm - 10.0) < 1e-3, f"Expected 10.0 mm shift, got {delta_z_mm}"
    print("✓ Change detection and 10 mm shift diff verified")


def test_krama_intake_files(snap):
    """Test ingestion via KRAMA intake_files stub."""
    print("\n--- 3. KRAMA intake_files() Ingestion ---")
    project_id = uuid.UUID("00000000-cafe-babe-beef-ca0da000001a")
    files = snap.partition_for_intake()
    file_names = [f[0] for f in files]
    print(f"Partitioned files for intake: {file_names}")

    metadata = {
        name: {
            "source": snap.source,
            "snapshot_id": snap.snapshot_id,
            "version_id": snap.document.version_id,
        }
        for name in file_names
    }

    run = intake_files(
        project_id=project_id,
        files=files,
        source="connector",
        metadata_by_source_file=metadata,
    )

    print(f"IngestionRun ID   : {run.run_id}")
    print(f"Ingestion status  : {run.status}")
    print(f"Files ingested    : {run.file_count}")
    assert run.status == "completed"
    assert run.file_count == len(files)
    print("✓ KRAMA intake ingestion verified")


def test_sqlalchemy_persistence(snap):
    """Test persistence to SQLAlchemy database (SQLite)."""
    print("\n--- 4. SQLAlchemy Database Persistence ---")
    from app.database import SessionLocal, init_db
    from app.models.connection import Connection
    from app.models.document import LinkedDocument
    from app.models.project import Project
    from app.models.snapshot import SnapshotRecord

    init_db()
    with SessionLocal() as db:
        conn_id = "conn_freecad_test"
        if not db.query(Connection).filter(Connection.id == conn_id).first():
            db.add(Connection(
                id=conn_id,
                name="FreeCAD Test Bridge",
                base_url="local://freecad",
                access_key_masked="FREECAD_TEST",
            ))
            db.commit()

        proj_id = "00000000-cafe-babe-beef-ca0da000001a"
        if not db.query(Project).filter(Project.id == proj_id).first():
            db.add(Project(id=proj_id, name="FreeCAD Bridge Project"))
            db.commit()

        doc_id = snap.document.document_id or "freecad_live_doc"
        if not db.query(LinkedDocument).filter(LinkedDocument.id == doc_id).first():
            db.add(LinkedDocument(
                id=doc_id,
                project_id=proj_id,
                connection_id=conn_id,
                document_id=doc_id,
                element_id="live_assembly",
            ))
            db.commit()

        # Delete any existing record with same ID to allow re-runs
        db.query(SnapshotRecord).filter(SnapshotRecord.id == snap.snapshot_id).delete()
        db.commit()

        record = SnapshotRecord(
            id=snap.snapshot_id,
            project_id=proj_id,
            document_id=doc_id,
            version_id=snap.document.version_id,
            version_name=snap.document.version_name,
            element_id="live_assembly",
            total_mass=snap.assembly_mass_properties.mass if snap.assembly_mass_properties else None,
            instance_count=len(snap.assembly.instances),
            component_count=len(snap.components),
            payload_json=snap.to_deterministic_json(),
            extracted_at=snap.extracted_at,
        )
        db.add(record)
        db.commit()

        # Verify from database
        persisted = db.query(SnapshotRecord).filter(SnapshotRecord.id == snap.snapshot_id).first()
        assert persisted is not None, "Failed to retrieve snapshot from database"
        print(f"Persisted Snapshot ID : {persisted.id}")
        print(f"Stored Instance Count : {persisted.instance_count}")
        print(f"Stored Component Count: {persisted.component_count}")
        assert persisted.instance_count == len(snap.assembly.instances)
        print("✓ SQLAlchemy database persistence verified")


if __name__ == "__main__":
    print("==================================================================")
    print("  KRAMA FREECAD CONNECTOR BRIDGE — VERIFICATION SUITE")
    print("==================================================================")
    snap = test_freecad_connector_live_state()
    test_krama_diff_engine(snap)
    test_krama_intake_files(snap)
    test_sqlalchemy_persistence(snap)
    print("\n==================================================================")
    print("  ALL BRIDGE TESTS PASSED SUCCESSFULLY ✓")
    print("==================================================================")
