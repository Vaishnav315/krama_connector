"""Unit tests for deterministic snapshot diffing and change detection."""

from app.connectors.onshape.adapter import OnshapeConnector
from app.schemas.common import ProvenanceRecord, ProvenanceSource
from app.schemas.diff import ChangeClassification
from app.schemas.mass_properties import MassProperties
from app.services.diff_service import SnapshotDiffEngine


def test_diff_v1_and_v2_real_design_changes():
    """Verify that diffing v1 and v2 detects added/removed instances, quantity deltas, and physical property changes."""
    connector = OnshapeConnector(use_fixtures=True)
    snap_v1 = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")
    snap_v2 = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "9c4d6e8a23f5b7a9c1d3f5b7")

    diff_engine = SnapshotDiffEngine()
    diff = diff_engine.compare(snap_v1, snap_v2)

    assert diff.base_snapshot_id == snap_v1.snapshot_id
    assert diff.target_snapshot_id == snap_v2.snapshot_id

    # 1. Added instances: Force/Torque Sensor
    added_names = [a.name for a in diff.added_instances]
    assert any("Force Torque Sensor" in name for name in added_names)

    # 2. Removed instances: 2 of the M8 cap screws
    removed_ids = [r.instance_id for r in diff.removed_instances]
    assert "inst_m8_bolt_3" in removed_ids
    assert "inst_m8_bolt_4" in removed_ids

    # 3. Quantity changes
    m8_qty = next(q for q in diff.quantity_changes if "part_m8_screw" in q.component_id)
    assert m8_qty.old_quantity == 4
    assert m8_qty.new_quantity == 2
    assert m8_qty.delta == -2

    # 4. Material changes on elbow joint
    elbow_diff = next(c for c in diff.changed_components if "part_elbow_joint" in c.component_id)
    assert elbow_diff.material_change is not None
    assert elbow_diff.material_change.old_value == "Aluminum 7075-T6"
    assert elbow_diff.material_change.new_value == "Titanium Ti-6Al-4V"
    assert elbow_diff.material_change.classification == ChangeClassification.SOURCE_DETECTED

    # 5. Revision change on bicep tube
    bicep_diff = next(c for c in diff.changed_components if "part_bicep_tube" in c.component_id)
    assert bicep_diff.revision_change is not None
    assert bicep_diff.revision_change.old_value == "A"
    assert bicep_diff.revision_change.new_value == "B"

    # 6. Assembly mass delta and CoM shift
    assert diff.assembly_delta.old_total_mass == 14.850
    assert diff.assembly_delta.new_total_mass == 15.420
    assert round(diff.assembly_delta.mass_delta, 3) == 0.570
    assert diff.assembly_delta.mass_classification == ChangeClassification.SNAPSHOT_INFERRED
    assert diff.assembly_delta.center_of_mass_shift_distance is not None
    assert diff.assembly_delta.center_of_mass_shift_distance > 0.0


def test_diff_identical_snapshots():
    """Verify that comparing identical snapshots produces no additions, removals, or deltas."""
    connector = OnshapeConnector(use_fixtures=True)
    snap_v1 = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    diff_engine = SnapshotDiffEngine()
    diff = diff_engine.compare(snap_v1, snap_v1)

    assert len(diff.added_instances) == 0
    assert len(diff.removed_instances) == 0
    assert len(diff.moved_instances) == 0
    assert len(diff.quantity_changes) == 0
    assert len(diff.changed_components) == 0
    assert diff.assembly_delta.mass_delta == 0.0


def test_diff_missing_mass_is_indeterminate_not_zero():
    """Verify that an unavailable mass property in comparison is marked INDETERMINATE rather than generating a false delta."""
    connector = OnshapeConnector(use_fixtures=True)
    snap_a = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")
    snap_b = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    # Simulate missing assembly mass in snapshot B
    snap_b.assembly_mass_properties = MassProperties(
        mass=None,
        provenance=ProvenanceRecord(
            source=ProvenanceSource.SOURCE_UNAVAILABLE,
            description="Unavailable",
        ),
    )

    diff_engine = SnapshotDiffEngine()
    diff = diff_engine.compare(snap_a, snap_b)

    assert diff.assembly_delta.old_total_mass == 14.850
    assert diff.assembly_delta.new_total_mass is None
    assert diff.assembly_delta.mass_delta is None  # NOT 14.850 or -14.850!
    assert diff.assembly_delta.mass_classification == ChangeClassification.INDETERMINATE
    assert any("indeterminate due to missing mass" in w for w in diff.warnings)
