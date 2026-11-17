"""Schemas for assembly hierarchy, instances, occurrences, and transforms."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.geometry import BoundingBox3D


class InstanceNode(BaseModel):
    """An individual occurrence/instance of a component in the assembly tree.

    Preserves repeated instances as distinct entities with their own instance_id and transform.
    """

    instance_id: str = Field(description="Unique instance occurrence ID (e.g. 'M123_456' or occurrence path)")
    name: str = Field(description="Instance display name (e.g. 'Bracket <1>', 'Bracket <2>')")
    component_id: str = Field(description="References the ComponentDefinition ID")
    parent_instance_id: str | None = Field(default=None, description="Parent subassembly instance ID, or None if root")
    is_subassembly: bool = Field(default=False, description="True if this instance is a nested subassembly")
    transform: list[float] = Field(
        default_factory=lambda: [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ],
        description="Row-major 4x4 spatial transformation matrix in assembly coordinates",
    )
    suppressed: bool = Field(default=False, description="Whether instance is suppressed in the assembly")


class AssemblyHierarchy(BaseModel):
    """Complete structural hierarchy of the mechanical assembly."""

    assembly_id: str = Field(description="Assembly element ID")
    name: str = Field(description="Assembly title / root component name")
    instances: list[InstanceNode] = Field(default_factory=list, description="All individual part & subassembly instances")
    instance_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Aggregated count of occurrences per component_id",
    )
    root_instances: list[str] = Field(default_factory=list, description="Top-level child instance IDs")
    overall_extents: BoundingBox3D | None = Field(default=None, description="World bounding box of entire assembly")

    def get_instances_for_component(self, component_id: str) -> list[InstanceNode]:
        """Return all occurrences corresponding to a specific component definition."""
        return [inst for inst in self.instances if inst.component_id == component_id]

    def get_children_of(self, parent_instance_id: str | None) -> list[InstanceNode]:
        """Return all direct children of an instance, or top-level instances if None."""
        return [inst for inst in self.instances if inst.parent_instance_id == parent_instance_id]
