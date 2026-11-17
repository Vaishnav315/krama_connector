"""Deterministic snapshot comparison and change detection engine.

Analyzes structural, physical, and metadata differences between two versioned snapshots.
Explicitly distinguishes between source-detected changes, snapshot-inferred changes,
and indeterminate comparisons resulting from missing measurements.
"""

from __future__ import annotations

import math

from app.schemas.diff import (
    AssemblyDelta,
    ChangeClassification,
    ComponentDiff,
    InstanceDiff,
    QuantityChange,
    SnapshotDiff,
    ValueChange,
)
from app.schemas.snapshot import Snapshot


class SnapshotDiffEngine:
    """Deterministic diff calculator for CAD snapshots."""

    def __init__(
        self,
        spatial_tolerance: float = 1e-4,  # 0.1 mm in meters
        mass_tolerance: float = 1e-4,     # 0.1 g in kg
    ):
        self.spatial_tolerance = spatial_tolerance
        self.mass_tolerance = mass_tolerance

    def _floats_equal(self, a: float | None, b: float | None, tol: float) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return abs(a - b) <= tol

    def _vectors_equal(self, v1: list[float] | None, v2: list[float] | None, tol: float) -> bool:
        if v1 is None and v2 is None:
            return True
        if v1 is None or v2 is None or len(v1) != len(v2):
            return False
        return all(abs(a - b) <= tol for a, b in zip(v1, v2, strict=False))

    def _euclidean_distance(self, p1: list[float] | None, p2: list[float] | None) -> float | None:
        if not p1 or not p2 or len(p1) < 3 or len(p2) < 3:
            return None
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1[:3], p2[:3], strict=False)))

    def compare(self, base: Snapshot, target: Snapshot) -> SnapshotDiff:
        """Compare base snapshot with target snapshot and produce deterministic SnapshotDiff."""
        added_instances: list[InstanceDiff] = []
        removed_instances: list[InstanceDiff] = []
        moved_instances: list[InstanceDiff] = []
        warnings: list[str] = []
        indeterminate_properties: list[ValueChange] = []

        # 1. Instance-level comparison
        base_instances_by_id = {inst.instance_id: inst for inst in base.assembly.instances}
        target_instances_by_id = {inst.instance_id: inst for inst in target.assembly.instances}

        all_instance_ids = set(base_instances_by_id.keys()).union(target_instances_by_id.keys())
        for i_id in sorted(all_instance_ids):
            b_inst = base_instances_by_id.get(i_id)
            t_inst = target_instances_by_id.get(i_id)

            if b_inst is None and t_inst is not None:
                added_instances.append(
                    InstanceDiff(
                        instance_id=t_inst.instance_id,
                        name=t_inst.name,
                        component_id=t_inst.component_id,
                        parent_instance_id=t_inst.parent_instance_id,
                        change_type="added",
                        new_transform=t_inst.transform,
                    )
                )
            elif b_inst is not None and t_inst is None:
                removed_instances.append(
                    InstanceDiff(
                        instance_id=b_inst.instance_id,
                        name=b_inst.name,
                        component_id=b_inst.component_id,
                        parent_instance_id=b_inst.parent_instance_id,
                        change_type="removed",
                        old_transform=b_inst.transform,
                    )
                )
            elif b_inst is not None and t_inst is not None:
                # Check if position/transform changed
                if not self._vectors_equal(b_inst.transform, t_inst.transform, self.spatial_tolerance):
                    moved_instances.append(
                        InstanceDiff(
                            instance_id=t_inst.instance_id,
                            name=t_inst.name,
                            component_id=t_inst.component_id,
                            parent_instance_id=t_inst.parent_instance_id,
                            change_type="moved",
                            old_transform=b_inst.transform,
                            new_transform=t_inst.transform,
                        )
                    )

        # 2. Instance count / quantity changes
        quantity_changes: list[QuantityChange] = []
        all_comp_ids_in_counts = set(base.assembly.instance_counts.keys()).union(target.assembly.instance_counts.keys())
        comp_names_map = {c.component_id: c.name for c in base.components + target.components}

        for c_id in sorted(all_comp_ids_in_counts):
            q_old = base.assembly.instance_counts.get(c_id, 0)
            q_new = target.assembly.instance_counts.get(c_id, 0)
            if q_old != q_new:
                quantity_changes.append(
                    QuantityChange(
                        component_id=c_id,
                        component_name=comp_names_map.get(c_id, c_id),
                        old_quantity=q_old,
                        new_quantity=q_new,
                        delta=q_new - q_old,
                    )
                )

        # 3. Component definitions changes
        changed_components: list[ComponentDiff] = []
        base_comps_by_id = {c.component_id: c for c in base.components}
        target_comps_by_id = {c.component_id: c for c in target.components}

        common_comp_ids = set(base_comps_by_id.keys()).intersection(target_comps_by_id.keys())
        for c_id in sorted(common_comp_ids):
            b_comp = base_comps_by_id[c_id]
            t_comp = target_comps_by_id[c_id]

            comp_diff = ComponentDiff(component_id=c_id, name=t_comp.name)
            has_comp_change = False

            # Part number
            if b_comp.part_number != t_comp.part_number:
                comp_diff.part_number_change = ValueChange(
                    property_name="part_number",
                    old_value=b_comp.part_number,
                    new_value=t_comp.part_number,
                    classification=ChangeClassification.SOURCE_DETECTED,
                )
                has_comp_change = True

            # Revision
            if b_comp.revision != t_comp.revision:
                comp_diff.revision_change = ValueChange(
                    property_name="revision",
                    old_value=b_comp.revision,
                    new_value=t_comp.revision,
                    classification=ChangeClassification.SOURCE_DETECTED,
                )
                has_comp_change = True

            # Material
            if b_comp.material != t_comp.material:
                comp_diff.material_change = ValueChange(
                    property_name="material",
                    old_value=b_comp.material,
                    new_value=t_comp.material,
                    classification=ChangeClassification.SOURCE_DETECTED,
                )
                has_comp_change = True

            # Mass properties comparison
            b_mass = b_comp.mass_properties.mass if b_comp.mass_properties else None
            t_mass = t_comp.mass_properties.mass if t_comp.mass_properties else None

            if b_mass is None or t_mass is None:
                if b_mass != t_mass:
                    # One was present and one was absent, or both absent
                    explanation = f"Mass measurement missing in {'base' if b_mass is None else 'target'} snapshot"
                    indet = ValueChange(
                        property_name=f"{c_id}.mass",
                        old_value=b_mass,
                        new_value=t_mass,
                        delta=None,
                        classification=ChangeClassification.INDETERMINATE,
                        explanation=explanation,
                    )
                    indeterminate_properties.append(indet)
                    comp_diff.mass_change = indet
                    has_comp_change = True
            elif not self._floats_equal(b_mass, t_mass, self.mass_tolerance):
                comp_diff.mass_change = ValueChange(
                    property_name="mass",
                    old_value=b_mass,
                    new_value=t_mass,
                    delta=t_mass - b_mass,
                    classification=ChangeClassification.SNAPSHOT_INFERRED,
                )
                has_comp_change = True

            # Center of mass comparison
            b_com = b_comp.mass_properties.center_of_mass if b_comp.mass_properties else None
            t_com = t_comp.mass_properties.center_of_mass if t_comp.mass_properties else None
            if b_com and t_com:
                if not self._vectors_equal(b_com, t_com, self.spatial_tolerance):
                    dist = self._euclidean_distance(b_com, t_com)
                    comp_diff.center_of_mass_change = ValueChange(
                        property_name="center_of_mass",
                        old_value=b_com,
                        new_value=t_com,
                        delta=dist,
                        classification=ChangeClassification.SNAPSHOT_INFERRED,
                    )
                    has_comp_change = True
            elif (b_com is None) ^ (t_com is None):
                indet_com = ValueChange(
                    property_name=f"{c_id}.center_of_mass",
                    old_value=b_com,
                    new_value=t_com,
                    classification=ChangeClassification.INDETERMINATE,
                    explanation="Center of mass missing in one snapshot",
                )
                indeterminate_properties.append(indet_com)
                comp_diff.center_of_mass_change = indet_com
                has_comp_change = True

            # Custom properties comparison
            all_custom_keys = set(b_comp.custom_properties.keys()).union(t_comp.custom_properties.keys())
            for k in sorted(all_custom_keys):
                v_old = b_comp.custom_properties.get(k)
                v_new = t_comp.custom_properties.get(k)
                if v_old != v_new:
                    comp_diff.custom_property_changes.append(
                        ValueChange(
                            property_name=k,
                            old_value=v_old,
                            new_value=v_new,
                            classification=ChangeClassification.SOURCE_DETECTED,
                        )
                    )
                    has_comp_change = True

            if has_comp_change:
                changed_components.append(comp_diff)

        # 4. Overall assembly delta
        b_asm_mass = base.assembly_mass_properties.mass if base.assembly_mass_properties else None
        t_asm_mass = target.assembly_mass_properties.mass if target.assembly_mass_properties else None

        mass_delta: float | None = None
        mass_class = ChangeClassification.SNAPSHOT_INFERRED
        mass_expl: str | None = None
        if b_asm_mass is not None and t_asm_mass is not None:
            mass_delta = t_asm_mass - b_asm_mass
        else:
            mass_class = ChangeClassification.INDETERMINATE
            mass_expl = "Overall assembly mass comparison indeterminate due to missing mass in one or both snapshots"
            warnings.append(mass_expl)

        b_asm_com = base.assembly_mass_properties.center_of_mass if base.assembly_mass_properties else None
        t_asm_com = target.assembly_mass_properties.center_of_mass if target.assembly_mass_properties else None
        com_shift = self._euclidean_distance(b_asm_com, t_asm_com) if b_asm_com and t_asm_com else None
        com_class = ChangeClassification.SNAPSHOT_INFERRED if com_shift is not None else ChangeClassification.INDETERMINATE

        # Assembly extents
        b_ext = base.assembly.overall_extents
        t_ext = target.assembly.overall_extents
        extents_changed = False
        if b_ext and t_ext:
            extents_changed = not (
                self._vectors_equal(b_ext.min_point, t_ext.min_point, self.spatial_tolerance)
                and self._vectors_equal(b_ext.max_point, t_ext.max_point, self.spatial_tolerance)
            )

        assembly_delta = AssemblyDelta(
            old_total_mass=b_asm_mass,
            new_total_mass=t_asm_mass,
            mass_delta=mass_delta,
            mass_classification=mass_class,
            mass_explanation=mass_expl,
            old_center_of_mass=b_asm_com,
            new_center_of_mass=t_asm_com,
            center_of_mass_shift_distance=com_shift,
            center_of_mass_classification=com_class,
            old_extents=b_ext,
            new_extents=t_ext,
            extents_changed=extents_changed,
        )

        # Summary statistics
        summary = {
            "added_instances": len(added_instances),
            "removed_instances": len(removed_instances),
            "moved_instances": len(moved_instances),
            "quantity_changes": len(quantity_changes),
            "changed_components": len(changed_components),
            "indeterminate_properties": len(indeterminate_properties),
        }

        return SnapshotDiff(
            base_snapshot_id=base.snapshot_id,
            target_snapshot_id=target.snapshot_id,
            base_version_name=base.document.version_name,
            target_version_name=target.document.version_name,
            base_extracted_at=base.extracted_at,
            target_extracted_at=target.extracted_at,
            summary=summary,
            added_instances=added_instances,
            removed_instances=removed_instances,
            moved_instances=moved_instances,
            quantity_changes=quantity_changes,
            changed_components=changed_components,
            assembly_delta=assembly_delta,
            indeterminate_properties=indeterminate_properties,
            warnings=warnings,
        )
