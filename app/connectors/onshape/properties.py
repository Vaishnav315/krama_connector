"""Onshape component metadata and custom property extractor.

Resolves component definitions, part numbers, revisions, materials,
and explicitly audits any missing metadata fields.
References:
- https://onshape-public.github.io/docs/api-adv/metadata/
"""

from __future__ import annotations

from typing import Any

from app.connectors.onshape.mass_properties import parse_onshape_mass_properties
from app.schemas.common import MissingValueRecord
from app.schemas.component import ComponentDefinition


def extract_component_definitions(
    raw_assembly_data: dict[str, Any],
    raw_mass_properties_data: dict[str, Any] | None = None,
) -> tuple[list[ComponentDefinition], list[MissingValueRecord]]:
    """Extract deduplicated ComponentDefinitions and audit missing metadata fields.

    Returns:
    - List of canonical ComponentDefinition objects.
    - List of MissingValueRecord objects recording any missing part numbers, revisions, materials, or mass.
    """
    components: list[ComponentDefinition] = []
    missing_records: list[MissingValueRecord] = []
    seen_component_ids: set[str] = set()

    raw_parts = raw_assembly_data.get("parts", [])
    bodies_mass = (raw_mass_properties_data or {}).get("bodies", {})

    for p in raw_parts:
        raw_part_id = p.get("partId")
        if not raw_part_id:
            continue

        component_id = f"part_{raw_part_id}"
        if component_id in seen_component_ids:
            continue
        seen_component_ids.add(component_id)

        part_name = p.get("name", f"Part {raw_part_id}")
        part_number = p.get("partNumber")
        revision = p.get("revision")
        material = p.get("material")
        density = p.get("density")
        elem_id = p.get("elementId")

        # Audit missing part number
        if not part_number:
            missing_records.append(
                MissingValueRecord(
                    entity_id=component_id,
                    entity_type="part",
                    property_name="part_number",
                    reason="Part number not assigned in Onshape component metadata",
                )
            )

        # Audit missing revision
        if not revision:
            missing_records.append(
                MissingValueRecord(
                    entity_id=component_id,
                    entity_type="part",
                    property_name="revision",
                    reason="Revision not released or tracked in Onshape release management",
                )
            )

        # Audit missing material
        if not material:
            missing_records.append(
                MissingValueRecord(
                    entity_id=component_id,
                    entity_type="part",
                    property_name="material",
                    reason="No material assigned to part definition in Onshape Part Studio",
                )
            )

        # Per-part mass properties from bodies
        body_mass_data = bodies_mass.get(raw_part_id)
        mass_props = parse_onshape_mass_properties(
            raw_mass_data=body_mass_data,
            is_assembly=False,
            entity_id=component_id,
        )

        if mass_props.mass is None:
            missing_records.append(
                MissingValueRecord(
                    entity_id=component_id,
                    entity_type="part",
                    property_name="mass",
                    reason="Mass calculation unavailable because part definition lacks density or volume",
                )
            )

        comp = ComponentDefinition(
            component_id=component_id,
            name=part_name,
            part_number=part_number,
            revision=revision,
            material=material,
            material_density=density,
            is_standard_content=p.get("isStandardContent", False),
            mass_properties=mass_props,
            custom_properties=p.get("customProperties", {}),
            source_element_id=elem_id,
            source_part_id=raw_part_id,
        )
        components.append(comp)

    return components, missing_records
