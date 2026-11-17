"""Onshape assembly hierarchy and occurrence graph transformer.

Handles recursive subassembly resolution, occurrence transform mapping,
instance aggregation, and distinction between definitions and occurrences.
References:
- https://onshape-public.github.io/docs/api-adv/assemblies/
"""

from __future__ import annotations

from typing import Any

from app.schemas.assembly import AssemblyHierarchy, InstanceNode
from app.schemas.geometry import BoundingBox3D


def parse_onshape_assembly_hierarchy(
    raw_assembly_data: dict[str, Any],
    overall_bounding_box_data: dict[str, Any] | None = None,
) -> AssemblyHierarchy:
    """Transform raw Onshape assembly API response into canonical AssemblyHierarchy.

    Key considerations:
    - Onshape represents assemblies with rootAssembly instances, subAssemblies definitions,
      and flattened occurrences with hierarchical path lists (e.g. ['subasm_1', 'subasm_2', 'part_1']).
    - Preserves repeated instances distinctly.
    - Aggregates instance counts per component definition.
    - Resolves 4x4 spatial transformation matrix for each instance occurrence.
    """
    root_asm = raw_assembly_data.get("rootAssembly", {})
    assembly_id = root_asm.get("elementId") or raw_assembly_data.get("elementId", "unknown_assembly")
    doc_id = root_asm.get("documentId") or raw_assembly_data.get("documentId", "unknown_document")

    # Map occurrences by path string to their transform and properties
    occurrences_map: dict[str, dict[str, Any]] = {}
    for occ in root_asm.get("occurrences", []):
        path_list = occ.get("path", [])
        path_str = "/".join(path_list)
        occurrences_map[path_str] = occ

    # Build subassembly index by elementId
    subassemblies_by_id: dict[str, dict[str, Any]] = {}
    for sub in root_asm.get("subAssemblies", []):
        sub_elem_id = sub.get("elementId")
        if sub_elem_id:
            subassemblies_by_id[sub_elem_id] = sub

    instances: list[InstanceNode] = []
    instance_counts: dict[str, int] = {}
    root_instance_ids: list[str] = []

    def process_subassembly(
        current_asm: dict[str, Any],
        parent_instance_id: str | None = None,
        path_prefix: list[str] | None = None,
    ) -> None:
        prefix = path_prefix or []
        for raw_inst in current_asm.get("instances", []):
            inst_id = raw_inst.get("id")
            inst_name = raw_inst.get("name", inst_id)
            inst_type = raw_inst.get("type", "Part")
            is_sub = inst_type == "Assembly"

            # Component definition ID
            if is_sub:
                component_id = f"asm_{raw_inst.get('elementId')}"
            else:
                raw_part_id = raw_inst.get("partId")
                raw_inst.get("elementId", "")
                component_id = f"part_{raw_part_id}" if raw_part_id else f"part_{inst_id}"

            # Path in occurrence hierarchy
            current_path = [*prefix, inst_id]
            current_path_str = "/".join(current_path)

            # Retrieve spatial transform from occurrences if available, else identity
            occ_info = occurrences_map.get(current_path_str, {})
            transform = occ_info.get("transform") or [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ]
            suppressed = raw_inst.get("suppressed", False)

            node = InstanceNode(
                instance_id=current_path_str,  # Use full occurrence path as stable unique instance ID
                name=inst_name,
                component_id=component_id,
                parent_instance_id=parent_instance_id,
                is_subassembly=is_sub,
                transform=transform,
                suppressed=suppressed,
            )
            instances.append(node)

            if parent_instance_id is None:
                root_instance_ids.append(node.instance_id)

            # Count occurrences (only for actual physical parts, not subassembly groups)
            if not is_sub and not suppressed:
                instance_counts[component_id] = instance_counts.get(component_id, 0) + 1

            # Recurse into nested subassembly if applicable
            if is_sub:
                target_sub_elem = raw_inst.get("elementId")
                nested_sub = subassemblies_by_id.get(target_sub_elem)
                if nested_sub:
                    process_subassembly(
                        current_asm=nested_sub,
                        parent_instance_id=node.instance_id,
                        path_prefix=current_path,
                    )

    # Process root assembly instances
    process_subassembly(root_asm, parent_instance_id=None, path_prefix=[])

    # Parse overall assembly bounding box
    overall_extents: BoundingBox3D | None = None
    if overall_bounding_box_data:
        try:
            min_pt = [
                float(overall_bounding_box_data["lowX"]),
                float(overall_bounding_box_data["lowY"]),
                float(overall_bounding_box_data["lowZ"]),
            ]
            max_pt = [
                float(overall_bounding_box_data["highX"]),
                float(overall_bounding_box_data["highY"]),
                float(overall_bounding_box_data["highZ"]),
            ]
            overall_extents = BoundingBox3D.from_min_max(
                min_point=min_pt,
                max_point=max_pt,
                coordinate_system="world_space",
                units="meter",
            )
        except (KeyError, ValueError, TypeError):
            overall_extents = None

    return AssemblyHierarchy(
        assembly_id=assembly_id,
        name=f"Assembly {assembly_id} (Doc: {doc_id})",
        instances=instances,
        instance_counts=instance_counts,
        root_instances=root_instance_ids,
        overall_extents=overall_extents,
    )
