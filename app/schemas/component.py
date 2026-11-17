"""Schemas for component definitions, materials, and part identity."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.geometry import BoundingBox3D
from app.schemas.mass_properties import MassProperties


class ComponentDefinition(BaseModel):
    """Canonical representation of a unique physical part or subassembly definition.

    Note: This is the definition (prototype), distinct from individual assembly occurrences/instances.
    """

    component_id: str = Field(description="Globally unique/stable component definition identifier")
    name: str = Field(description="Part or component display name")
    part_number: str | None = Field(default=None, description="Official part number from metadata, if assigned")
    revision: str | None = Field(default=None, description="Revision label, if configured")
    material: str | None = Field(default=None, description="Material designation (e.g., 'Aluminum 6061-T6')")
    material_density: float | None = Field(default=None, description="Density in kg/m^3 if defined")
    is_standard_content: bool = Field(default=False, description="Whether part is standard hardware (nuts, bolts, etc.)")
    mass_properties: MassProperties | None = Field(default=None, description="Mass properties of this component definition")
    local_bounding_box: BoundingBox3D | None = Field(default=None, description="Part-local bounding box")
    world_bounding_box: BoundingBox3D | None = Field(default=None, description="Reference instance world bounding box")
    custom_properties: dict[str, Any] = Field(default_factory=dict, description="Custom metadata key-values")
    source_element_id: str | None = Field(default=None, description="Onshape elementId where defined")
    source_part_id: str | None = Field(default=None, description="Onshape internal partId")
