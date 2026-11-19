"""FreeCAD CADConnector adapter.

Implements CADConnector for FreeCAD models, supporting both live watcher/macro snapshots
(live_state.json) and direct headless/fixture extractions.

Preserves hierarchical subassemblies, extracts part identities (part number, revision,
material, density), computes physical mass when density is assigned, honestly audits
missing values when unassigned, and uses content-addressed version identity for live edits.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.connectors.base import CADConnector
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

logger = logging.getLogger(__name__)

MM_TO_M = 1.0 / 1000.0
MM3_TO_M3 = 1.0 / 1_000_000_000.0
DEFAULT_WATCH_FILE = (
    Path(__file__).parent.parent.parent.parent
    / "freecad_api_test"
    / "freecad_krama_bridge"
    / "live_state.json"
)


def _mm_vec_to_m(vec_mm: list[float] | None) -> list[float] | None:
    if vec_mm is None:
        return None
    return [v * MM_TO_M for v in vec_mm]


def _bbox_mm_to_m(bb_mm: dict[str, Any]) -> BoundingBox3D:
    mn = _mm_vec_to_m(bb_mm["min"]) or [0.0, 0.0, 0.0]
    mx = _mm_vec_to_m(bb_mm["max"]) or [0.0, 0.0, 0.0]
    return BoundingBox3D.from_min_max(mn, mx, coordinate_system="world_space", units="meter")


def _transform_mm_to_m(mat16: list[float] | None) -> list[float]:
    if not mat16 or len(mat16) != 16:
        return [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    m = list(mat16)
    m[3] = m[3] * MM_TO_M
    m[7] = m[7] * MM_TO_M
    m[11] = m[11] * MM_TO_M
    return m


def _version_id_from_data(meta: dict[str, Any], asm_data: dict[str, Any] | None = None) -> str:
    """Derive a stable, content-addressed version identifier for live design state.

    Computes SHA-256 over the canonical assembly definition:
    instance names, spatial placements (4x4 transforms), component definitions,
    and geometry bounding boxes.

    Guarantees:
    1. If the live model is unmodified (or reverted/undone), the version ID is IDENTICAL.
    2. If a part is moved in the 3D viewport (even before saving to disk), the version ID
       changes deterministically to reflect the active in-memory CAD design revision.
    3. Unsaved edits generate distinct, traceable version IDs in KRAMA's intake pipeline.
    """
    if asm_data and "instances" in asm_data:
        live_footprint = []
        for inst in sorted(asm_data.get("instances", []), key=lambda x: str(x.get("instance_name", ""))):
            live_footprint.append({
                "name": inst.get("instance_name"),
                "transform": inst.get("placement", {}).get("transform_matrix_4x4"),
                "vol": inst.get("geometry", {}).get("volume_mm3"),
                "props": inst.get("custom_properties", {}),
            })
        hasher = hashlib.sha256()
        hasher.update(json.dumps(live_footprint, sort_keys=True).encode("utf-8"))
        state_hash = hasher.hexdigest()[:16]
        return f"freecad_rev_{state_hash}"

    # Secondary fallback: file hash if saved to disk
    file_hash = meta.get("file_hash_sha256")
    if file_hash:
        return f"freecad_sha256_{file_hash[:16]}"

    epoch = meta.get("extracted_at_epoch", 0)
    return f"freecad_live_{int(epoch)}"


class FreeCADConnector(CADConnector):
    """Adapter bridging FreeCAD models and live observer snapshots to CADConnector."""

    def __init__(self, watch_file: Path | str | None = None):
        self.watch_file = Path(watch_file) if watch_file else DEFAULT_WATCH_FILE

    def _load(self) -> dict[str, Any]:
        if not self.watch_file.exists():
            raise FileNotFoundError(
                f"FreeCAD bridge state file not found at: {self.watch_file}\n"
                "Run freecad_observer_bridge.FCMacro inside FreeCAD to generate state."
            )
        with open(self.watch_file, encoding="utf-8") as f:
            return json.load(f)

    def _meta(self, data: dict[str, Any]) -> dict[str, Any]:
        return data.get("metadata", {})

    def _asm(self, data: dict[str, Any]) -> dict[str, Any]:
        return data.get("assembly", {})

    def connect(self) -> bool:
        """Verify presence of live bridge state file."""
        return self.watch_file.exists()

    def get_document(self, document_reference: str) -> dict[str, Any]:
        data = self._load()
        meta = self._meta(data)
        return {
            "documentId": document_reference,
            "name": meta.get("document_name", document_reference),
            "label": meta.get("document_label", document_reference),
            "source": "FreeCAD",
            "file_path": meta.get("file_path", ""),
        }

    def get_versions(self, document_reference: str) -> list[dict[str, Any]]:
        data = self._load()
        meta = self._meta(data)
        asm_data = self._asm(data)
        version_id = _version_id_from_data(meta, asm_data)
        epoch = meta.get("extracted_at_epoch", 0)
        time_str = datetime.fromtimestamp(epoch, tz=UTC).strftime("%H:%M:%S UTC")
        return [
            {
                "id": version_id,
                "name": f"Rev {version_id[-8:]} ({time_str})",
                "microversion": version_id[-16:],
                "createdAt": datetime.fromtimestamp(epoch, tz=UTC).isoformat(),
            }
        ]

    def get_assembly(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> AssemblyHierarchy:
        data = self._load()
        meta = self._meta(data)
        asm_data = self._asm(data)
        doc_name = meta.get("document_name", document_reference)
        return self._build_assembly_hierarchy(asm_data, doc_name)

    def _build_assembly_hierarchy(self, asm_data: dict[str, Any], doc_name: str) -> AssemblyHierarchy:
        instances_raw: list[dict[str, Any]] = asm_data.get("instances", [])
        krama_instances: list[InstanceNode] = []
        instance_counts: dict[str, int] = {}
        root_instance_ids: list[str] = []

        # First pass: map of instance IDs
        for idx, raw in enumerate(instances_raw):
            inst_name = raw.get("instance_name", f"inst_{idx}")
            inst_label = raw.get("instance_label", inst_name)
            source_obj = raw.get("source_object") or {}
            src_name = source_obj.get("name", inst_name)
            component_id = f"freecad_part_{src_name}"

            # Transform matrix in meters
            mat16_raw = None
            plm = raw.get("placement")
            if plm:
                mat16_raw = plm.get("transform_matrix_4x4")
            mat16 = _transform_mm_to_m(mat16_raw)

            # Unique instance_id
            instance_id = f"{doc_name}_{inst_label}"

            # Support nested parent-child hierarchies
            parent_id = raw.get("parent_instance_id")
            is_sub = bool(
                raw.get("is_subassembly", False)
                or raw.get("type_id") in ("App::Part", "Assembly::AssemblyObject", "App::DocumentObjectGroup", "App::LinkGroup")
            )

            node = InstanceNode(
                instance_id=instance_id,
                name=inst_label,
                component_id=component_id,
                parent_instance_id=parent_id,
                is_subassembly=is_sub,
                transform=mat16,
                suppressed=False,
            )
            krama_instances.append(node)

            if parent_id is None:
                root_instance_ids.append(instance_id)

            if not is_sub:
                instance_counts[component_id] = instance_counts.get(component_id, 0) + 1

        overall_extents: BoundingBox3D | None = None
        og = asm_data.get("overall_geometry", {})
        bb_mm = og.get("bounding_box_mm")
        if bb_mm and bb_mm.get("min") and bb_mm.get("max"):
            overall_extents = _bbox_mm_to_m(bb_mm)

        return AssemblyHierarchy(
            assembly_id=f"freecad_{doc_name}_assembly",
            name=asm_data.get("root_label", doc_name),
            instances=krama_instances,
            instance_counts=instance_counts,
            root_instances=root_instance_ids,
            overall_extents=overall_extents,
        )

    def get_components(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> list[ComponentDefinition]:
        data = self._load()
        components, _ = self._build_components(self._asm(data))
        return components

    def _build_components(
        self,
        asm_data: dict[str, Any],
    ) -> tuple[list[ComponentDefinition], list[MissingValueRecord]]:
        instances_raw: list[dict[str, Any]] = asm_data.get("instances", [])
        part_defs: dict[str, dict[str, Any]] = asm_data.get("part_definitions", {})
        missing_values: list[MissingValueRecord] = []
        seen: dict[str, ComponentDefinition] = {}

        for raw in instances_raw:
            source_obj = raw.get("source_object") or {}
            src_name = source_obj.get("name", raw.get("instance_name", "unknown"))
            component_id = f"freecad_part_{src_name}"
            if component_id in seen:
                continue

            src_label = source_obj.get("label", src_name)
            part_def = part_defs.get(src_name, {})
            custom_props = raw.get("custom_properties", {})

            # 1. Bounding boxes
            local_bb: BoundingBox3D | None = None
            def_bb_mm = part_def.get("bounding_box_mm")
            if def_bb_mm and def_bb_mm.get("min"):
                local_bb = _bbox_mm_to_m(def_bb_mm)

            inst_bb_mm = raw.get("geometry", {}).get("bounding_box_mm")
            world_bb: BoundingBox3D | None = None
            if inst_bb_mm and inst_bb_mm.get("min"):
                world_bb = _bbox_mm_to_m(inst_bb_mm)

            # 2. Geometry Volume and Centroid
            vol_mm3 = raw.get("geometry", {}).get("volume_mm3")
            vol_m3 = vol_mm3 * MM3_TO_M3 if vol_mm3 is not None else None
            geom_com_mm = raw.get("geometry", {}).get("geometric_center_of_mass_mm")
            geom_com_m = _mm_vec_to_m(geom_com_mm) if geom_com_mm else None

            # 3. Resolve Part Identity from attributes and custom properties
            part_num = (
                raw.get("part_number")
                or custom_props.get("PartNumber")
                or custom_props.get("part_number")
                or custom_props.get("Part_Number")
                or custom_props.get("PartNo")
                or custom_props.get("ItemNumber")
            )
            if not part_num:
                missing_values.append(
                    MissingValueRecord(
                        entity_id=component_id,
                        entity_type="part",
                        property_name="part_number",
                        reason="Part number not assigned in FreeCAD object properties",
                    )
                )

            rev = (
                raw.get("revision")
                or custom_props.get("Revision")
                or custom_props.get("revision")
                or custom_props.get("Rev")
                or custom_props.get("Version")
            )
            if not rev:
                missing_values.append(
                    MissingValueRecord(
                        entity_id=component_id,
                        entity_type="part",
                        property_name="revision",
                        reason="Revision not tracked in FreeCAD object properties",
                    )
                )

            material_name = (
                raw.get("material")
                or custom_props.get("Material")
                or custom_props.get("material")
                or custom_props.get("MaterialName")
            )
            if not material_name:
                missing_values.append(
                    MissingValueRecord(
                        entity_id=component_id,
                        entity_type="part",
                        property_name="material",
                        reason="No material card assigned to part in FreeCAD",
                    )
                )

            raw_density = (
                raw.get("density")
                or custom_props.get("Density")
                or custom_props.get("density")
                or custom_props.get("MaterialDensity")
            )
            density_kg_m3: float | None = float(raw_density) if isinstance(raw_density, (int, float)) else None

            # 4. Resolve Physical Mass Properties vs Missing Audit
            physical_mass_kg: float | None = None
            inertia_tensor: InertiaTensor | None = None

            if vol_m3 is not None and density_kg_m3 is not None and density_kg_m3 > 0:
                physical_mass_kg = vol_m3 * density_kg_m3

                # Compute physical moments of inertia from geometric inertia matrix if available
                raw_inertia = raw.get("geometry", {}).get("matrix_of_inertia")
                if raw_inertia and len(raw_inertia) >= 6:
                    # Geometric inertia mm^5 -> scale by density (kg/m^3) * 1e-15 to get kg*m^2
                    scale = density_kg_m3 * 1e-15
                    inertia_tensor = InertiaTensor(
                        ixx=raw_inertia[0] * scale,
                        iyy=raw_inertia[1] * scale,
                        izz=raw_inertia[2] * scale,
                        ixy=raw_inertia[3] * scale if len(raw_inertia) > 3 else 0.0,
                        ixz=raw_inertia[4] * scale if len(raw_inertia) > 4 else 0.0,
                        iyz=raw_inertia[5] * scale if len(raw_inertia) > 5 else 0.0,
                    )

                mass_props = MassProperties(
                    mass=physical_mass_kg,
                    volume=vol_m3,
                    surface_area=None,
                    center_of_mass=geom_com_m,  # homogeneous physical CoM equals geometric centroid
                    inertia_tensor=inertia_tensor,
                    principal_moments=None,
                    provenance=ProvenanceRecord(
                        source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
                        description="Physical mass and CoM computed from FreeCAD solid geometry and assigned density",
                        confidence=1.0,
                        raw_source_field="Shape.Volume * Material.Density",
                    ),
                )
            else:
                # Honestly preserve missing mass
                missing_values.append(
                    MissingValueRecord(
                        entity_id=component_id,
                        entity_type="part",
                        property_name="mass",
                        reason="No material density assigned in FreeCAD — physical mass is indeterminate",
                    )
                )
                missing_values.append(
                    MissingValueRecord(
                        entity_id=component_id,
                        entity_type="part",
                        property_name="physical_center_of_mass",
                        reason="Cannot compute without density; center_of_mass field holds geometric centroid only",
                    )
                )
                mass_props = MassProperties(
                    mass=None,
                    volume=vol_m3,
                    surface_area=None,
                    center_of_mass=geom_com_m,  # geometric centroid, NOT physical CoM
                    inertia_tensor=None,
                    principal_moments=None,
                    provenance=ProvenanceRecord(
                        source=ProvenanceSource.SOURCE_UNAVAILABLE,
                        description="Geometric centroid only. Physical mass unavailable without assigned material density.",
                        confidence=1.0,
                        raw_source_field="Shape.Volume / Shape.CenterOfGravity",
                    ),
                )

            comp = ComponentDefinition(
                component_id=component_id,
                name=src_label,
                part_number=part_num,
                revision=rev,
                material=material_name,
                material_density=density_kg_m3,
                is_standard_content=False,
                mass_properties=mass_props,
                local_bounding_box=local_bb,
                world_bounding_box=world_bb,
                custom_properties=custom_props,
                source_element_id=None,
                source_part_id=src_name,
            )
            seen[component_id] = comp

        return list(seen.values()), missing_values

    def get_mass_properties(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> MassProperties:
        data = self._load()
        asm_data = self._asm(data)
        og = asm_data.get("overall_geometry", {})
        total_vol_mm3 = og.get("total_volume_mm3")
        total_vol_m3 = total_vol_mm3 * MM3_TO_M3 if total_vol_mm3 else None
        geom_com_mm = og.get("geometric_center_of_mass_mm")
        geom_com_m = _mm_vec_to_m(geom_com_mm) if geom_com_mm else None

        # Check if components have assigned densities
        components, _ = self._build_components(asm_data)
        has_densities = any(c.material_density for c in components)

        if has_densities:
            total_mass = sum(
                (c.mass_properties.mass or 0.0)
                for c in components
                if c.mass_properties and c.mass_properties.mass is not None
            )
            return MassProperties(
                mass=total_mass,
                volume=total_vol_m3,
                surface_area=None,
                center_of_mass=geom_com_m,
                inertia_tensor=None,
                provenance=ProvenanceRecord(
                    source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
                    description="Aggregate mass computed from component densities and geometries",
                    confidence=1.0,
                ),
            )

        return MassProperties(
            mass=None,
            volume=total_vol_m3,
            surface_area=None,
            center_of_mass=geom_com_m,  # volume-weighted geometric centroid
            inertia_tensor=None,
            provenance=ProvenanceRecord(
                source=ProvenanceSource.SOURCE_UNAVAILABLE,
                description=(
                    "Assembly geometric centroid from FreeCAD B-Rep shapes. "
                    "Physical mass is None: no material density is assigned."
                ),
                confidence=1.0,
            ),
        )

    def extract_snapshot(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> Snapshot:
        data = self._load()
        meta = self._meta(data)
        asm_data = self._asm(data)
        doc_name = meta.get("document_name", document_reference)
        version_id = _version_id_from_data(meta, asm_data)
        epoch = meta.get("extracted_at_epoch", 0)
        time_str = datetime.fromtimestamp(epoch, tz=UTC).strftime("%H:%M:%S UTC")

        assembly = self._build_assembly_hierarchy(asm_data, doc_name)
        components, missing_values = self._build_components(asm_data)
        assembly_mass = self.get_mass_properties(document_reference, version_reference)

        warnings: list[WarningRecord] = []
        if assembly_mass.mass is None:
            warnings.append(
                WarningRecord(
                    code="WARN_NO_PHYSICAL_MASS",
                    message="Physical mass unavailable: no material density assigned in FreeCAD model",
                    entity_id=assembly.assembly_id,
                )
            )

        doc_ref = DocumentReference(
            document_id=f"freecad_{doc_name}",
            document_name=meta.get("document_label", doc_name),
            element_id=assembly.assembly_id,
            element_name=assembly.name,
            version_id=version_id,
            version_name=f"Rev {version_id[-8:]} ({time_str})",
            microversion_id=version_id[-16:],
        )

        return Snapshot(
            snapshot_id=str(hashlib.md5(f"{doc_name}:{version_id}".encode()).hexdigest()),
            source="freecad",
            document=doc_ref,
            units=UnitsSchema(
                length="meter",
                mass="kilogram",
                volume="cubic_meter",
            ),
            assembly=assembly,
            components=components,
            assembly_properties={
                "model_type": meta.get("model_type", "FreeCAD"),
                "joints_count": len(asm_data.get("joints", [])),
                "file_path": meta.get("file_path", ""),
            },
            assembly_mass_properties=assembly_mass,
            provenance={
                "adapter": "FreeCADConnector",
                "watch_file": str(self.watch_file),
                "model_type": meta.get("model_type", "FreeCAD"),
            },
            warnings=warnings,
            missing_values=missing_values,
        )

    def detect_changes(
        self,
        document_reference: str,
        previous_version_ref: str,
        current_version_ref: str,
    ) -> dict[str, Any]:
        return {
            "document_id": document_reference,
            "previous_version": previous_version_ref,
            "current_version": current_version_ref,
            "has_version_change": previous_version_ref != current_version_ref,
        }
