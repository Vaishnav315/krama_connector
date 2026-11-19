"""Unit tests for Onshape hierarchy extraction, repeated instances, and snapshot adapter."""

from app.connectors.onshape.adapter import OnshapeConnector
from app.schemas.common import ProvenanceSource


def test_onshape_adapter_connect_and_versions():
    """Verify adapter connects using fixtures and lists committed versions."""
    connector = OnshapeConnector(use_fixtures=True)
    assert connector.connect() is True

    versions = connector.get_versions("65a1f2b3c4d5e6f7a8b9c0d1")
    assert len(versions) >= 2
    version_ids = [v["id"] for v in versions]
    assert "7a2e4b8f01c3d5e7a9b0c1d2" in version_ids
    assert "9c4d6e8a23f5b7a9c1d3f5b7" in version_ids


def test_assembly_hierarchy_extraction_and_nesting():
    """Verify adapter extracts 2+ levels of subassemblies and >= 15 part instances."""
    connector = OnshapeConnector(use_fixtures=True)
    hierarchy = connector.get_assembly("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    assert hierarchy.assembly_id == "43210fedcba9876543210fed"
    # Total instances (subassemblies + parts)
    assert len(hierarchy.instances) >= 15
    assert len(hierarchy.instances) == 22

    # Verify nested subassemblies
    subassemblies = [inst for inst in hierarchy.instances if inst.is_subassembly]
    assert len(subassemblies) == 2
    sub_names = [s.name for s in subassemblies]
    assert any("Articulated Arm Module" in name for name in sub_names)
    assert any("Wrist & End Effector" in name for name in sub_names)

    # Verify occurrence path parent-child relationships
    wrist_subasm = next(s for s in subassemblies if "Wrist & End Effector" in s.name)
    assert wrist_subasm.parent_instance_id == "inst_arm_module_subasm_1"

    # Verify repeated instances: 4x M8 screws, 2x Dowel pins, 2x M4 screws, 2x silicone pads
    assert hierarchy.instance_counts["part_part_m8_screw"] == 4
    assert hierarchy.instance_counts["part_part_dowel_pin"] == 2
    assert hierarchy.instance_counts["part_part_m4_screw"] == 2
    assert hierarchy.instance_counts["part_part_rubber_pad"] == 2

    # Check overall bounding box
    assert hierarchy.overall_extents is not None
    assert hierarchy.overall_extents.coordinate_system == "world_space"
    assert hierarchy.overall_extents.dimensions == [0.5, 0.67, 0.72]


def test_part_metadata_and_missing_values_audit():
    """Verify component definitions preserve materials and part numbers without inventing missing values."""
    connector = OnshapeConnector(use_fixtures=True)
    components = connector.get_components("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    comp_map = {c.component_id: c for c in components}

    # Base pedestal: has material and revision A
    base = comp_map["part_part_base_pedestal"]
    assert base.part_number == "ARM-001-BASE"
    assert base.revision == "A"
    assert base.material == "Cast Iron Class 30"
    assert base.mass_properties is not None
    assert base.mass_properties.mass == 6.250

    # Gripper servo: COTS part with missing material and missing mass
    servo = comp_map["part_part_gripper_servo"]
    assert servo.material is None  # NOT invented!
    assert servo.mass_properties is not None
    assert servo.mass_properties.mass is None  # NOT defaulted to 0.0!
    assert servo.mass_properties.provenance.source == ProvenanceSource.SOURCE_UNAVAILABLE


def test_mass_properties_provenance():
    """Verify overall assembly mass properties and explicit provenance."""
    connector = OnshapeConnector(use_fixtures=True)
    mass_props = connector.get_mass_properties("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    assert mass_props.mass == 14.850
    assert mass_props.volume == 0.00285
    assert mass_props.center_of_mass == [-0.015, 0.085, 0.180]
    assert mass_props.inertia_tensor is not None
    assert mass_props.inertia_tensor.ixx == 0.125
    assert mass_props.provenance.source == ProvenanceSource.COMPUTED_FROM_GEOMETRY


def test_extract_snapshot_complete():
    """Verify full snapshot creation with version tracking and missing value explanations."""
    connector = OnshapeConnector(use_fixtures=True)
    snapshot = connector.extract_snapshot("65a1f2b3c4d5e6f7a8b9c0d1", "7a2e4b8f01c3d5e7a9b0c1d2")

    assert snapshot.source == "onshape"
    assert snapshot.document.document_id == "65a1f2b3c4d5e6f7a8b9c0d1"
    assert snapshot.document.version_id == "7a2e4b8f01c3d5e7a9b0c1d2"
    assert snapshot.document.microversion_id == "8b3f5c9e12d4a6f8b0c2e4a6"
    assert len(snapshot.assembly.instances) == 22
    assert len(snapshot.components) == 13

    # Check missing values audit trail
    missing_props = {(m.entity_id, m.property_name) for m in snapshot.missing_values}
    # Gripper servo should have missing material and missing mass
    assert ("part_part_gripper_servo", "material") in missing_props
    assert ("part_part_gripper_servo", "mass") in missing_props
    # Standard hardware screws have no revision tracked
    assert ("part_part_m8_screw", "revision") in missing_props


def test_mass_properties_is_mass_overridden_provenance():
    """Verify isMassOverridden flag sets provenance to ENTERED_MANUALLY."""
    from app.connectors.onshape.mass_properties import parse_onshape_mass_properties

    raw = {
        "hasMass": True,
        "isMassOverridden": True,
        "mass": [5.5],
        "volume": [0.001],
        "centroid": [0.0, 0.0, 0.1],
    }
    mp = parse_onshape_mass_properties(raw, is_assembly=False, entity_id="test_part")
    assert mp.mass == 5.5
    assert mp.provenance.source == ProvenanceSource.ENTERED_MANUALLY
    assert "manually overridden" in mp.provenance.description.lower()
