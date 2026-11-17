"""Schemas for deterministic snapshot comparison and change detection."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.geometry import BoundingBox3D


class ChangeClassification(StrEnum):
    """Provenance and detection confidence of an identified change."""

    SOURCE_DETECTED = "source_detected"       # Confirmed via source CAD history/metadata
    SNAPSHOT_INFERRED = "snapshot_inferred"   # Derived mathematically by comparing snapshots
    INDETERMINATE = "indeterminate"           # Cannot establish because one or both versions lacked source data


class ValueChange(BaseModel):
    """Detailed before-and-after record of a changed scalar or property."""

    property_name: str
    old_value: Any = None
    new_value: Any = None
    delta: Any = None
    classification: ChangeClassification = ChangeClassification.SNAPSHOT_INFERRED
    explanation: str | None = None


class QuantityChange(BaseModel):
    """Change in the instance count of a component definition."""

    component_id: str
    component_name: str
    old_quantity: int
    new_quantity: int
    delta: int


class InstanceDiff(BaseModel):
    """Instance-level addition, removal, or transform shift."""

    instance_id: str
    name: str
    component_id: str
    parent_instance_id: str | None = None
    change_type: str = Field(description="'added', 'removed', or 'moved'")
    old_transform: list[float] | None = None
    new_transform: list[float] | None = None


class ComponentDiff(BaseModel):
    """Comprehensive change summary for a specific component definition."""

    component_id: str
    name: str
    property_changes: list[ValueChange] = Field(default_factory=list)
    material_change: ValueChange | None = None
    part_number_change: ValueChange | None = None
    revision_change: ValueChange | None = None
    mass_change: ValueChange | None = None
    center_of_mass_change: ValueChange | None = None
    bounding_box_change: ValueChange | None = None
    custom_property_changes: list[ValueChange] = Field(default_factory=list)


class AssemblyDelta(BaseModel):
    """Overall assembly level physical and extents changes."""

    old_total_mass: float | None = None
    new_total_mass: float | None = None
    mass_delta: float | None = None
    mass_classification: ChangeClassification = ChangeClassification.SNAPSHOT_INFERRED
    mass_explanation: str | None = None

    old_center_of_mass: list[float] | None = None
    new_center_of_mass: list[float] | None = None
    center_of_mass_shift_distance: float | None = None
    center_of_mass_classification: ChangeClassification = ChangeClassification.SNAPSHOT_INFERRED

    old_extents: BoundingBox3D | None = None
    new_extents: BoundingBox3D | None = None
    extents_changed: bool = False


class SnapshotDiff(BaseModel):
    """Structured report comparing two snapshots."""

    base_snapshot_id: str
    target_snapshot_id: str
    base_version_name: str
    target_version_name: str
    base_extracted_at: datetime
    target_extracted_at: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    summary: dict[str, int] = Field(
        default_factory=dict,
        description="Summary counts: added_instances, removed_instances, changed_components, etc.",
    )

    added_instances: list[InstanceDiff] = Field(default_factory=list)
    removed_instances: list[InstanceDiff] = Field(default_factory=list)
    moved_instances: list[InstanceDiff] = Field(default_factory=list)

    quantity_changes: list[QuantityChange] = Field(default_factory=list)
    changed_components: list[ComponentDiff] = Field(default_factory=list)
    assembly_delta: AssemblyDelta = Field(default_factory=AssemblyDelta)

    indeterminate_properties: list[ValueChange] = Field(
        default_factory=list,
        description="Properties where changes could not be evaluated due to missing source data",
    )
    warnings: list[str] = Field(default_factory=list)
