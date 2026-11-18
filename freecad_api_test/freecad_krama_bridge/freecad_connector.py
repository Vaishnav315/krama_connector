"""FreeCAD → KRAMA Connector.

Implements CADConnector (app.connectors.base.CADConnector) using the JSON
snapshot written by freecad_observer_bridge.FCMacro.

All new KRAMA code lives here, in freecad_api_test. The only KRAMA change
was the approved one-line schema extension:
  Snapshot.source: Literal["onshape", "freecad"] = "onshape"

Unit conventions
----------------
FreeCAD internal units are always millimetres (mm) and degrees.
KRAMA canonical units are metres (m) and radians.
This connector converts at the boundary:
  length  : mm → m  (÷ 1000)
  volume  : mm³ → m³  (÷ 1e9)
  transform translation columns: mm → m
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Ensure krama_onshape_connector and its virtualenv packages are on sys.path
# regardless of how this module is executed (directly, via watcher, or
# from any working directory, even without activating the venv).
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_KRAMA_ROOT = None
for candidate in [
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_onshape_connector")),
]:
    if os.path.exists(os.path.join(candidate, "app", "schemas")):
        _KRAMA_ROOT = candidate
        break

if not _KRAMA_ROOT:
    _KRAMA_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_onshape_connector"))

# Add KRAMA project root
if _KRAMA_ROOT not in sys.path:
    sys.path.insert(0, _KRAMA_ROOT)

# Add KRAMA .venv site-packages if available
_venv_site_packages = glob.glob(os.path.join(_KRAMA_ROOT, ".venv", "lib", "python*", "site-packages"))
for _sp in _venv_site_packages:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

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
from app.schemas.mass_properties import MassProperties
from app.schemas.snapshot import DocumentReference, Snapshot

# ---------------------------------------------------------------------------
# Default watch-file path (resolved relative to this file's directory)
# ---------------------------------------------------------------------------
_DEFAULT_WATCH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "live_state.json"
)

MM_TO_M = 1.0 / 1000.0
MM3_TO_M3 = 1.0 / 1_000_000_000.0


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def _mm_vec_to_m(vec_mm: list[float]) -> list[float]:
    return [v * MM_TO_M for v in vec_mm]


def _bbox_mm_to_m(bb_mm: dict) -> BoundingBox3D:
    """Convert a FreeCAD bounding-box dict (mm) to KRAMA BoundingBox3D (m)."""
    mn = _mm_vec_to_m(bb_mm["min"])
    mx = _mm_vec_to_m(bb_mm["max"])
    return BoundingBox3D.from_min_max(mn, mx, coordinate_system="world_space", units="meter")


def _transform_mm_to_m(mat16: list[float]) -> list[float]:
    """Convert a row-major 4×4 transform so the translation columns are in metres.

    FreeCAD's toMatrix().A is row-major:
      [ R00 R01 R02 Tx ]
      [ R10 R11 R12 Ty ]
      [ R20 R21 R22 Tz ]
      [  0   0   0   1 ]
    Indices 3, 7, 11 are the translation components.
    """
    out = list(mat16)
    for idx in (3, 7, 11):
        out[idx] = out[idx] * MM_TO_M
    return out


# ---------------------------------------------------------------------------
# Mapping from FreeCAD bridge JSON → KRAMA schemas
# ---------------------------------------------------------------------------

def _build_component_id(source_name: str) -> str:
    """Stable component_id derived from the Part::Feature source object name."""
    return f"freecad_part_{source_name}"


def _make_assembly_hierarchy(asm_data: dict, doc_name: str) -> AssemblyHierarchy:
    instances_raw: list[dict] = asm_data.get("instances", [])
    krama_instances: list[InstanceNode] = []
    instance_counts: dict[str, int] = {}
    root_instance_ids: list[str] = []

    for idx, raw in enumerate(instances_raw):
        inst_name: str = raw.get("instance_name", f"inst_{idx}")
        inst_label: str = raw.get("instance_label", inst_name)
        source_obj = raw.get("source_object") or {}
        src_name = source_obj.get("name", inst_name)
        component_id = _build_component_id(src_name)

        # Transform: convert mm translation columns → metres
        mat16_raw = None
        plm = raw.get("placement")
        if plm:
            mat16_raw = plm.get("transform_matrix_4x4")
        mat16 = _transform_mm_to_m(mat16_raw) if mat16_raw and len(mat16_raw) == 16 else [
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        ]

        # Unique instance_id: label is unique within an assembly
        instance_id = f"{doc_name}_{inst_label}"

        node = InstanceNode(
            instance_id=instance_id,
            name=inst_label,
            component_id=component_id,
            parent_instance_id=None,   # FreeCAD flat-link assemblies have no sub-assembly nesting
            is_subassembly=False,
            transform=mat16,
            suppressed=False,
        )
        krama_instances.append(node)
        root_instance_ids.append(instance_id)
        instance_counts[component_id] = instance_counts.get(component_id, 0) + 1

    # Overall bounding box
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


def _make_components(
    asm_data: dict,
) -> tuple[list[ComponentDefinition], list[MissingValueRecord]]:
    """Deduplicate App::Link instances into ComponentDefinition prototypes."""
    part_defs: dict[str, dict] = asm_data.get("part_definitions", {})
    instances_raw: list[dict] = asm_data.get("instances", [])
    missing_values: list[MissingValueRecord] = []

    # Group instances by source object name to build deduplicated definitions
    seen: dict[str, ComponentDefinition] = {}
    for raw in instances_raw:
        source_obj = raw.get("source_object") or {}
        src_name = source_obj.get("name", raw.get("instance_name", "unknown"))
        component_id = _build_component_id(src_name)
        if component_id in seen:
            continue

        src_label = source_obj.get("label", src_name)
        part_def = part_defs.get(src_name, {})

        # Bounding box (from part definition in local space, or from first instance in world)
        local_bb: BoundingBox3D | None = None
        def_bb_mm = part_def.get("bounding_box_mm")
        if def_bb_mm and def_bb_mm.get("min"):
            local_bb = _bbox_mm_to_m(def_bb_mm)

        inst_bb_mm = raw.get("geometry", {}).get("bounding_box_mm")
        world_bb: BoundingBox3D | None = None
        if inst_bb_mm and inst_bb_mm.get("min"):
            world_bb = _bbox_mm_to_m(inst_bb_mm)

        # Volume
        vol_mm3 = raw.get("geometry", {}).get("volume_mm3")
        vol_m3 = vol_mm3 * MM3_TO_M3 if vol_mm3 is not None else None

        # Geometric centre of mass (from B-Rep shape centroid — NOT physical CoM)
        geom_com_mm = raw.get("geometry", {}).get("geometric_center_of_mass_mm")
        geom_com_m = _mm_vec_to_m(geom_com_mm) if geom_com_mm else None

        # MassProperties: mass is None because no density is assigned in FreeCAD
        mass_props = MassProperties(
            mass=None,
            volume=vol_m3,
            surface_area=None,
            center_of_mass=geom_com_m,  # geometric centroid, NOT physical CoM
            inertia_tensor=None,
            provenance=ProvenanceRecord(
                source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
                description=(
                    "Volume and geometric centroid computed from FreeCAD B-Rep shape. "
                    "Physical mass and physical centre of mass are unavailable: "
                    "no material density is assigned in this FreeCAD document."
                ),
                confidence=1.0,
                raw_source_field="Shape.Volume / Shape.CenterOfGravity",
            ),
        )

        # Missing-value audit
        for prop_name, reason in [
            ("mass", "No material density assigned in FreeCAD — physical mass is indeterminate"),
            (
                "physical_center_of_mass",
                "Cannot compute without density; center_of_mass field holds geometric centroid only",
            ),
            ("surface_area", "FreeCAD Shape.Area API not queried in this bridge version"),
        ]:
            missing_values.append(
                MissingValueRecord(
                    entity_id=component_id,
                    entity_type="part",
                    property_name=prop_name,
                    reason=reason,
                )
            )

        comp = ComponentDefinition(
            component_id=component_id,
            name=src_label,
            part_number=None,
            revision=None,
            material=None,
            material_density=None,
            is_standard_content=False,
            mass_properties=mass_props,
            local_bounding_box=local_bb,
            world_bounding_box=world_bb,
            custom_properties=raw.get("custom_properties", {}),
            source_element_id=None,
            source_part_id=src_name,
        )
        seen[component_id] = comp

    return list(seen.values()), missing_values


def _make_assembly_mass(asm_data: dict) -> MassProperties:
    """Build aggregate assembly MassProperties from geometric data."""
    og = asm_data.get("overall_geometry", {})
    total_vol_mm3 = og.get("total_volume_mm3")
    total_vol_m3 = total_vol_mm3 * MM3_TO_M3 if total_vol_mm3 else None
    geom_com_mm = og.get("geometric_center_of_mass_mm")
    geom_com_m = _mm_vec_to_m(geom_com_mm) if geom_com_mm else None

    return MassProperties(
        mass=None,
        volume=total_vol_m3,
        surface_area=None,
        center_of_mass=geom_com_m,  # geometric centroid of entire assembly
        inertia_tensor=None,
        provenance=ProvenanceRecord(
            source=ProvenanceSource.COMPUTED_FROM_GEOMETRY,
            description=(
                "Assembly-level volume and geometric centroid from FreeCAD B-Rep shapes. "
                "Physical mass is None because no density is assigned. "
                "center_of_mass is the volume-weighted geometric centroid, "
                "NOT a physical centre of mass."
            ),
            confidence=0.9,
        ),
    )


def _version_id_from_data(meta: dict) -> str:
    """Derive a stable version identifier from the extraction timestamp."""
    epoch = meta.get("extracted_at_epoch", 0)
    # Round to 1-second buckets so tiny polling jitter doesn't create ghost versions
    return f"freecad_live_{int(epoch)}"


def _stable_doc_id(file_path: str) -> str:
    """Stable document ID from the file path SHA-256 prefix."""
    return "freecad_" + hashlib.sha256(file_path.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# FreeCADConnector — the CADConnector implementation
# ---------------------------------------------------------------------------

class FreeCADConnector(CADConnector):
    """CADConnector backed by the JSON watch file written by the FreeCAD observer macro.

    Parameters
    ----------
    watch_file : path to live_state.json (defaults to bridge directory)
    """

    def __init__(self, watch_file: str = _DEFAULT_WATCH_FILE):
        self.watch_file = watch_file
        self._last_data: dict | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        with open(self.watch_file, encoding="utf-8") as fh:
            data = json.load(fh)
        self._last_data = data
        return data

    def _meta(self, data: dict) -> dict:
        return data.get("metadata", {})

    def _asm(self, data: dict) -> dict:
        return data.get("assembly", {})

    # ------------------------------------------------------------------
    # CADConnector abstract methods
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        return os.path.isfile(self.watch_file)

    def get_document(self, document_reference: str) -> dict[str, Any]:
        data = self._load()
        meta = self._meta(data)
        return {
            "documentId": _stable_doc_id(meta.get("file_path", document_reference)),
            "name": meta.get("document_label", meta.get("document_name", document_reference)),
            "source": "FreeCAD",
            "file_path": meta.get("file_path", ""),
            "freecad_version": meta.get("freecad_version", "unknown"),
        }

    def get_versions(self, document_reference: str) -> list[dict[str, Any]]:
        """FreeCAD has no version history; return a single synthetic 'live' entry."""
        data = self._load()
        meta = self._meta(data)
        epoch = meta.get("extracted_at_epoch", 0)
        return [
            {
                "id": _version_id_from_data(meta),
                "name": f"Live – {datetime.fromtimestamp(epoch, tz=UTC).isoformat()}",
                "microversion": str(int(epoch)),
            }
        ]

    def get_assembly(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> AssemblyHierarchy:
        data = self._load()
        return _make_assembly_hierarchy(self._asm(data), self._meta(data).get("document_name", "doc"))

    def get_components(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> list[ComponentDefinition]:
        data = self._load()
        components, _ = _make_components(self._asm(data))
        return components

    def get_mass_properties(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> MassProperties:
        data = self._load()
        return _make_assembly_mass(self._asm(data))

    def extract_snapshot(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> Snapshot:
        data = self._load()
        meta = self._meta(data)
        asm_data = self._asm(data)
        doc_name = meta.get("document_name", "FreeCAD_Doc")
        file_path = meta.get("file_path", document_reference)
        doc_id = _stable_doc_id(file_path)
        epoch = meta.get("extracted_at_epoch", 0)
        version_id = _version_id_from_data(meta)
        version_name = f"Live – {datetime.fromtimestamp(epoch, tz=UTC).strftime('%H:%M:%S UTC')}"

        assembly = _make_assembly_hierarchy(asm_data, doc_name)
        components, missing_values = _make_components(asm_data)
        assembly_mass = _make_assembly_mass(asm_data)

        warnings: list[WarningRecord] = [
            WarningRecord(
                code="WARN_NO_PHYSICAL_MASS",
                message=(
                    "Physical mass is unavailable for all components: no material "
                    "density is assigned in this FreeCAD document. Mass-related diff "
                    "results will be classified as INDETERMINATE."
                ),
                entity_id=assembly.assembly_id,
            ),
            WarningRecord(
                code="INFO_GEOMETRIC_COM_ONLY",
                message=(
                    "center_of_mass in MassProperties is the geometric centroid "
                    "(volume-weighted B-Rep centroid), NOT a physical centre of mass."
                ),
                entity_id=assembly.assembly_id,
            ),
        ]

        doc_ref = DocumentReference(
            document_id=doc_id,
            document_name=meta.get("document_label", doc_name),
            element_id=f"freecad_{asm_data.get('root_name', 'Assembly')}",
            element_name=asm_data.get("root_label", "Assembly"),
            version_id=version_id,
            version_name=version_name,
            microversion_id=str(int(epoch)),
            workspace_id=None,
        )

        return Snapshot(
            snapshot_id=str(uuid.uuid4()),
            source="freecad",
            document=doc_ref,
            extracted_at=datetime.fromtimestamp(epoch, tz=UTC),
            units=UnitsSchema(
                length="meter",
                mass="kilogram",
                volume="meter^3",
                surface_area="meter^2",
                angle="radian",
                inertia="kilogram * meter^2",
            ),
            assembly=assembly,
            components=components,
            assembly_properties={
                "freecad_version": meta.get("freecad_version"),
                "freecad_revision": meta.get("freecad_revision"),
                "file_path": file_path,
                "assembly_root_type": asm_data.get("root_type"),
                "joint_count": asm_data.get("joint_count", 0),
                "total_volume_m3": (
                    (asm_data.get("overall_geometry", {}).get("total_volume_mm3") or 0.0)
                    * MM3_TO_M3
                ),
            },
            assembly_mass_properties=assembly_mass,
            provenance={
                "source": "FreeCAD",
                "bridge": "freecad_observer_bridge.FCMacro → freecad_connector.py",
                "watch_file": self.watch_file,
                "extracted_at_epoch": epoch,
                "note": (
                    "All transforms extracted from FreeCAD App::Link placements. "
                    "Translations converted mm→m. Geometry from Part::Feature Shape B-Rep."
                ),
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
            "note": "FreeCAD version IDs encode extraction timestamps; any change in the watch file represents a document edit.",
        }
