"""Canonical Snapshot JSON schema.

Contains complete versioned assembly structure, component definitions,
mass properties, units, provenance, warnings, and missing value records.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.assembly import AssemblyHierarchy
from app.schemas.common import MissingValueRecord, UnitsSchema, WarningRecord
from app.schemas.component import ComponentDefinition
from app.schemas.mass_properties import MassProperties


class DocumentReference(BaseModel):
    """Exact identity and version tracking of the source CAD document."""

    document_id: str = Field(description="Onshape document ID (d/...)")
    document_name: str = Field(description="Document display title")
    element_id: str = Field(description="Onshape assembly element ID (e/...)")
    element_name: str | None = Field(default=None, description="Element tab name")
    version_id: str = Field(description="Onshape immutable version ID (v/...) or workspace ID (w/...)")
    version_name: str = Field(description="Display version name (e.g. 'V1.0', 'Main Workspace')")
    microversion_id: str | None = Field(default=None, description="Microversion ID (m/...) for granular state")
    workspace_id: str | None = Field(default=None, description="Workspace ID if snapshot was taken from active branch")


class Snapshot(BaseModel):
    """Canonical versioned CAD snapshot representing an Onshape assembly."""

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: Literal["onshape", "freecad"] = "onshape"
    document: DocumentReference
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    units: UnitsSchema = Field(default_factory=UnitsSchema)
    assembly: AssemblyHierarchy
    components: list[ComponentDefinition] = Field(default_factory=list)
    assembly_properties: dict[str, Any] = Field(default_factory=dict)
    assembly_mass_properties: MassProperties | None = Field(
        default=None,
        description="Overall aggregate assembly mass, CoM, and inertia",
    )
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[WarningRecord] = Field(default_factory=list)
    missing_values: list[MissingValueRecord] = Field(default_factory=list)

    def to_deterministic_json(self) -> str:
        """Serialize snapshot to deterministic, indented JSON with sorted keys."""
        return json.dumps(
            self.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )

    def partition_for_intake(self) -> list[tuple[str, bytes]]:
        """Partition snapshot into the minimal, structured set of files for KRAMA intake.

        Returns list of (relative_file_path, content_bytes) tuples:
        1. assembly_snapshot.json: core document identity, units, hierarchy
        2. components.json: deduplicated component definitions, metadata, materials
        3. properties.json: assembly mass properties and custom metadata
        4. provenance.json: provenance mapping, missing values, warnings audit
        """
        # 1. Assembly snapshot
        assembly_payload = {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "document": self.document.model_dump(mode="json"),
            "extracted_at": self.extracted_at.isoformat(),
            "units": self.units.model_dump(mode="json"),
            "assembly": self.assembly.model_dump(mode="json"),
        }
        assembly_bytes = json.dumps(assembly_payload, indent=2, sort_keys=True).encode("utf-8")

        # 2. Components
        components_payload = {
            "snapshot_id": self.snapshot_id,
            "component_count": len(self.components),
            "components": [c.model_dump(mode="json") for c in self.components],
        }
        components_bytes = json.dumps(components_payload, indent=2, sort_keys=True).encode("utf-8")

        # 3. Properties & Mass
        properties_payload = {
            "snapshot_id": self.snapshot_id,
            "assembly_properties": self.assembly_properties,
            "assembly_mass_properties": (
                self.assembly_mass_properties.model_dump(mode="json")
                if self.assembly_mass_properties
                else None
            ),
        }
        properties_bytes = json.dumps(properties_payload, indent=2, sort_keys=True).encode("utf-8")

        # 4. Provenance & Audit
        provenance_payload = {
            "snapshot_id": self.snapshot_id,
            "provenance": self.provenance,
            "missing_values": [m.model_dump(mode="json") for m in self.missing_values],
            "warnings": [w.model_dump(mode="json") for w in self.warnings],
        }
        provenance_bytes = json.dumps(provenance_payload, indent=2, sort_keys=True).encode("utf-8")

        return [
            ("assembly_snapshot.json", assembly_bytes),
            ("components.json", components_bytes),
            ("properties.json", properties_bytes),
            ("provenance.json", provenance_bytes),
        ]
