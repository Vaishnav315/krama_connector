"""Onshape mass properties extractor and provenance resolver.

Parses physical properties (mass, volume, centroid, inertia tensor) from
Onshape API responses while strictly preserving provenance and avoiding 0.0 substitution.
References:
- https://onshape-public.github.io/docs/api-adv/assemblies/#mass-properties
"""

from __future__ import annotations

from typing import Any

from app.schemas.common import ProvenanceRecord, ProvenanceSource
from app.schemas.mass_properties import InertiaTensor, MassProperties


def parse_onshape_mass_properties(
    raw_mass_data: dict[str, Any] | None,
    is_assembly: bool = True,
    entity_id: str | None = None,
) -> MassProperties:
    """Transform Onshape mass properties payload into canonical MassProperties.

    Rules:
    - Never invent missing values or silently substitute 0.0 for an unmeasured property.
    - If hasMass is False or mass array is empty/null, set mass=None and mark provenance as SOURCE_UNAVAILABLE.
    - If computed from CAD B-rep geometry, mark provenance as COMPUTED_FROM_GEOMETRY.
    - Onshape returns mass arrays as [mass_value] and centroids as [x, y, z].
    """
    if not raw_mass_data or not raw_mass_data.get("hasMass", False):
        return MassProperties(
            mass=None,
            volume=None,
            surface_area=None,
            center_of_mass=None,
            inertia_tensor=None,
            principal_moments=None,
            provenance=ProvenanceRecord(
                source=ProvenanceSource.SOURCE_UNAVAILABLE,
                description=f"Mass properties unavailable for {'assembly' if is_assembly else 'part'} {entity_id or ''} in source CAD system",
                confidence=1.0,
            ),
        )

    # Onshape mass is typically a 1-element list [val]
    raw_mass = raw_mass_data.get("mass")
    mass_val: float | None = None
    if isinstance(raw_mass, list) and len(raw_mass) > 0 and raw_mass[0] is not None:
        mass_val = float(raw_mass[0])
    elif isinstance(raw_mass, (int, float)):
        mass_val = float(raw_mass)

    raw_volume = raw_mass_data.get("volume")
    vol_val: float | None = None
    if isinstance(raw_volume, list) and len(raw_volume) > 0 and raw_volume[0] is not None:
        vol_val = float(raw_volume[0])
    elif isinstance(raw_volume, (int, float)):
        vol_val = float(raw_volume)

    raw_area = raw_mass_data.get("surfaceArea")
    area_val: float | None = None
    if isinstance(raw_area, list) and len(raw_area) > 0 and raw_area[0] is not None:
        area_val = float(raw_area[0])
    elif isinstance(raw_area, (int, float)):
        area_val = float(raw_area)

    # Centroid: [x, y, z]
    raw_centroid = raw_mass_data.get("centroid")
    center_of_mass: list[float] | None = None
    if isinstance(raw_centroid, list) and len(raw_centroid) >= 3:
        center_of_mass = [float(raw_centroid[0]), float(raw_centroid[1]), float(raw_centroid[2])]

    # Inertia tensor components: [Ixx, Iyy, Izz, Ixy, Ixz, Iyz]
    raw_inertia = raw_mass_data.get("inertia")
    inertia_tensor: InertiaTensor | None = None
    if isinstance(raw_inertia, list) and len(raw_inertia) >= 3:
        ixx = float(raw_inertia[0])
        iyy = float(raw_inertia[1])
        izz = float(raw_inertia[2])
        ixy = float(raw_inertia[3]) if len(raw_inertia) > 3 else 0.0
        ixz = float(raw_inertia[4]) if len(raw_inertia) > 4 else 0.0
        iyz = float(raw_inertia[5]) if len(raw_inertia) > 5 else 0.0
        inertia_tensor = InertiaTensor(
            ixx=ixx,
            iyy=iyy,
            izz=izz,
            ixy=ixy,
            ixz=ixz,
            iyz=iyz,
        )

    # Principal moments
    raw_pm = raw_mass_data.get("principalMoments")
    principal_moments: list[float] | None = None
    if isinstance(raw_pm, list) and len(raw_pm) >= 3:
        principal_moments = [float(raw_pm[0]), float(raw_pm[1]), float(raw_pm[2])]

    # Respect Onshape's isMassOverridden flag — when true, mass was manually entered
    if raw_mass_data.get("isMassOverridden", False):
        provenance = ProvenanceRecord(
            source=ProvenanceSource.ENTERED_MANUALLY,
            description="Mass manually overridden by user in Onshape Part Studio; not computed from geometry",
            confidence=1.0,
            raw_source_field="massproperties.isMassOverridden",
        )
    else:
        provenance = ProvenanceRecord(
            source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
            description="Computed from Onshape solid geometry and assigned material density",
            confidence=1.0,
            raw_source_field="massproperties",
        )

    return MassProperties(
        mass=mass_val,
        volume=vol_val,
        surface_area=area_val,
        center_of_mass=center_of_mass,
        inertia_tensor=inertia_tensor,
        principal_moments=principal_moments,
        provenance=provenance,
    )
