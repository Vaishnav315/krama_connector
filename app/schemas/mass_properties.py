"""Schemas for mass properties, inertia tensors, and center of mass."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ProvenanceRecord, ProvenanceSource


class InertiaTensor(BaseModel):
    """Symmetric 3x3 inertia tensor components in the specified coordinate frame."""

    ixx: float
    iyy: float
    izz: float
    ixy: float = 0.0
    ixz: float = 0.0
    iyz: float = 0.0


class MassProperties(BaseModel):
    """Physical mass and inertial properties with explicit provenance and units.

    IMPORTANT: If mass properties were unavailable from the source CAD model,
    numerical values remain None rather than silently defaulting to 0.0.
    """

    mass: float | None = Field(default=None, description="Total mass in kg, or None if unavailable")
    volume: float | None = Field(default=None, description="Total volume in m^3, or None")
    surface_area: float | None = Field(default=None, description="Total surface area in m^2, or None")
    center_of_mass: list[float] | None = Field(
        default=None,
        description="[x, y, z] center of gravity coordinates in specified units/frame",
    )
    inertia_tensor: InertiaTensor | None = Field(
        default=None,
        description="Moments and products of inertia at center of mass",
    )
    principal_moments: list[float] | None = Field(
        default=None,
        description="[I1, I2, I3] principal moments of inertia",
    )
    provenance: ProvenanceRecord = Field(
        default_factory=lambda: ProvenanceRecord(
            source=ProvenanceSource.SOURCE_UNAVAILABLE,
            description="Mass properties not provided by CAD system",
        )
    )

    @property
    def has_valid_mass(self) -> bool:
        """Return True if mass is a non-None, strictly positive measurement."""
        return self.mass is not None and self.mass > 0
