"""Schemas for 3D bounding boxes, coordinate spaces, and extents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BoundingBox3D(BaseModel):
    """Axis-aligned 3D bounding box / geometric extents.

    Distinguishes whether coordinates are defined in part-local space or world/assembly space.
    """

    min_point: list[float] = Field(description="[min_x, min_y, min_z]")
    max_point: list[float] = Field(description="[max_x, max_y, max_z]")
    dimensions: list[float] = Field(description="[dx, dy, dz] bounding extents size")
    coordinate_system: Literal["world_space", "local_space"] = "world_space"
    units: str = "meter"

    @classmethod
    def from_min_max(
        cls,
        min_point: list[float],
        max_point: list[float],
        coordinate_system: Literal["world_space", "local_space"] = "world_space",
        units: str = "meter",
    ) -> BoundingBox3D:
        """Construct bounding box and automatically calculate extent dimensions."""
        dimensions = [
            max(0.0, max_point[0] - min_point[0]),
            max(0.0, max_point[1] - min_point[1]),
            max(0.0, max_point[2] - min_point[2]),
        ]
        return cls(
            min_point=min_point,
            max_point=max_point,
            dimensions=dimensions,
            coordinate_system=coordinate_system,
            units=units,
        )
