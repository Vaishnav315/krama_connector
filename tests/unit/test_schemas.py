"""Unit tests for domain schemas, mass properties, and snapshot serialization."""

import json

from app.schemas.assembly import AssemblyHierarchy, InstanceNode
from app.schemas.common import (
    MissingValueRecord,
    ProvenanceRecord,
    ProvenanceSource,
    UnitsSchema,
    WarningRecord,
)
from app.schemas.component import ComponentDefinition
from app.schemas.geometry import BoundingBox3D
from app.schemas.mass_properties import InertiaTensor, MassProperties
from app.schemas.snapshot import DocumentReference, Snapshot


def test_mass_properties_missing_not_zero():
    """Verify that an unavailable mass property remains None rather than silently defaulting to 0."""
    props = MassProperties(
        mass=None,
        volume=None,
        provenance=ProvenanceRecord(
            source=ProvenanceSource.SOURCE_UNAVAILABLE,
            description="Part has no material density assigned in Onshape",
        ),
    )
    assert props.mass is None
    assert props.volume is None
    assert props.has_valid_mass is False
    assert props.provenance.source == ProvenanceSource.SOURCE_UNAVAILABLE


def test_mass_properties_valid_calculation():
    """Verify valid mass properties and inertia tensors preserve precision and provenance."""
    props = MassProperties(
        mass=1.425,
        volume=0.00052,
        center_of_mass=[0.1, 0.2, 0.05],
        inertia_tensor=InertiaTensor(ixx=0.012, iyy=0.015, izz=0.008),
        provenance=ProvenanceRecord(
            source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
            description="Calculated from exact B-Rep geometry and Al-6061 density",
        ),
    )
    assert props.mass == 1.425
    assert props.has_valid_mass is True
    assert props.center_of_mass == [0.1, 0.2, 0.05]
    assert props.inertia_tensor.ixx == 0.012
    assert props.provenance.source == ProvenanceSource.COMPUTED_FROM_GEOMETRY


def test_bounding_box_creation():
    """Verify bounding box calculation and coordinate space preservation."""
    bbox = BoundingBox3D.from_min_max(
        min_point=[-0.5, 0.0, 1.0],
        max_point=[0.5, 2.0, 3.0],
        coordinate_system="world_space",
        units="meter",
    )
    assert bbox.dimensions == [1.0, 2.0, 2.0]
    assert bbox.coordinate_system == "world_space"


def test_assembly_hierarchy_and_repeated_instances():
    """Verify that repeated instances are preserved as separate nodes while providing aggregated counts."""
    inst1 = InstanceNode(
        instance_id="M_bolt_1",
        name="Hex Bolt M8x30 <1>",
        component_id="comp_bolt_m8",
    )
    inst2 = InstanceNode(
        instance_id="M_bolt_2",
        name="Hex Bolt M8x30 <2>",
        component_id="comp_bolt_m8",
    )
    assembly = AssemblyHierarchy(
        assembly_id="elem_asm_1",
        name="Main Assembly",
        instances=[inst1, inst2],
        instance_counts={"comp_bolt_m8": 2},
        root_instances=["M_bolt_1", "M_bolt_2"],
    )

    assert len(assembly.instances) == 2
    assert assembly.instances[0].instance_id == "M_bolt_1"
    assert assembly.instances[1].instance_id == "M_bolt_2"
    assert assembly.instance_counts["comp_bolt_m8"] == 2
    assert len(assembly.get_instances_for_component("comp_bolt_m8")) == 2


def test_snapshot_deterministic_json_and_partitioning():
    """Verify that snapshot produces deterministic JSON and partitions into expected intake files."""
    doc = DocumentReference(
        document_id="doc_123",
        document_name="Robotic Arm Assembly",
        element_id="elem_456",
        version_id="ver_789",
        version_name="Release v1.0",
        microversion_id="mver_abc",
    )
    comp = ComponentDefinition(
        component_id="comp_arm_base",
        name="Arm Base Cast",
        part_number="ARM-001",
        material="Aluminum 6061-T6",
    )
    inst = InstanceNode(
        instance_id="inst_1",
        name="Arm Base <1>",
        component_id="comp_arm_base",
    )
    asm = AssemblyHierarchy(
        assembly_id="elem_456",
        name="Robotic Arm",
        instances=[inst],
        instance_counts={"comp_arm_base": 1},
        root_instances=["inst_1"],
    )
    snapshot = Snapshot(
        snapshot_id="snap_test_001",
        document=doc,
        units=UnitsSchema(),
        assembly=asm,
        components=[comp],
        warnings=[WarningRecord(code="WARN_NO_MASS", message="Part base has no mass", entity_id="comp_arm_base")],
        missing_values=[
            MissingValueRecord(
                entity_id="comp_arm_base",
                entity_type="part",
                property_name="mass",
                reason="No density property",
            )
        ],
    )

    json_str = snapshot.to_deterministic_json()
    parsed = json.loads(json_str)
    assert parsed["snapshot_id"] == "snap_test_001"
    assert parsed["document"]["document_id"] == "doc_123"
    assert len(parsed["missing_values"]) == 1

    # Test file partitioning for intake
    partitioned = snapshot.partition_for_intake()
    file_names = [f[0] for f in partitioned]
    assert file_names == [
        "assembly_snapshot.json",
        "components.json",
        "properties.json",
        "provenance.json",
    ]
    for _filename, content in partitioned:
        assert isinstance(content, bytes)
        assert len(content) > 0
