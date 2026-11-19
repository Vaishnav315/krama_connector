"""Concrete Onshape Adapter implementing CADConnector interface.

Orchestrates document discovery, assembly hierarchy extraction,
metadata resolution, mass properties extraction, and canonical snapshot compilation.
Supports transparent offline fixture mode for automated testing without credentials.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.connectors.base import CADConnector
from app.connectors.onshape.assemblies import parse_onshape_assembly_hierarchy
from app.connectors.onshape.client import OnshapeClient
from app.connectors.onshape.mass_properties import parse_onshape_mass_properties
from app.connectors.onshape.properties import extract_component_definitions
from app.schemas.assembly import AssemblyHierarchy
from app.schemas.common import UnitsSchema, WarningRecord
from app.schemas.component import ComponentDefinition
from app.schemas.mass_properties import MassProperties
from app.schemas.snapshot import DocumentReference, Snapshot


class OnshapeConnector(CADConnector):
    """Adapter bridging Onshape REST APIs to KRAMA's CADConnector interface."""

    def __init__(
        self,
        client: OnshapeClient | None = None,
        use_fixtures: bool = False,
        fixtures_dir: Path | str | None = None,
    ):
        self.client = client
        self.use_fixtures = use_fixtures
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"

    def connect(self) -> bool:
        """Verify API connectivity or fixture availability."""
        if self.use_fixtures:
            return (self.fixtures_dir / "assembly_v1.json").exists()
        if self.client:
            return self.client.check_connection()
        return False

    def get_document(self, document_reference: str) -> dict[str, Any]:
        """Fetch document information."""
        if self.use_fixtures:
            meta_path = self.fixtures_dir / "metadata_v1.json"
            if meta_path.exists():
                with open(meta_path, encoding="utf-8") as f:
                    return json.load(f)
            return {"documentId": document_reference, "name": "Robotic Arm Assembly"}

        if not self.client:
            raise RuntimeError("No OnshapeClient provided for live connection")
        return self.client.get_document(document_reference)

    def get_versions(self, document_reference: str) -> list[dict[str, Any]]:
        """List all committed versions of the document."""
        if self.use_fixtures:
            versions_path = self.fixtures_dir / "versions.json"
            if versions_path.exists():
                with open(versions_path, encoding="utf-8") as f:
                    return json.load(f)
            return []

        if not self.client:
            raise RuntimeError("No OnshapeClient provided for live connection")
        return self.client.get_document_versions(document_reference)

    def _load_raw_assembly(self, document_id: str, version_id: str, element_id: str) -> dict[str, Any]:
        """Load raw assembly JSON from client or fixtures."""
        if self.use_fixtures:
            fixture_name = "assembly_v2.json" if version_id == "9c4d6e8a23f5b7a9c1d3f5b7" else "assembly_v1.json"
            fixture_path = self.fixtures_dir / fixture_name
            with open(fixture_path, encoding="utf-8") as f:
                return json.load(f)

        if not self.client:
            raise RuntimeError("No OnshapeClient configured")

        # All version references use wvm_type "v"
        wvm_type = "v"
        return self.client.get_assembly_definition(
            document_id=document_id,
            wvm_type=wvm_type,
            wvm_id=version_id,
            element_id=element_id,
        )

    def _load_raw_mass(self, document_id: str, version_id: str, element_id: str) -> dict[str, Any]:
        """Load raw mass properties JSON from client or fixtures."""
        if self.use_fixtures:
            fixture_name = "mass_properties_v2.json" if version_id == "9c4d6e8a23f5b7a9c1d3f5b7" else "mass_properties_v1.json"
            fixture_path = self.fixtures_dir / fixture_name
            if fixture_path.exists():
                with open(fixture_path, encoding="utf-8") as f:
                    return json.load(f)
            return {}

        if not self.client:
            return {}

        wvm_type = "v"
        return self.client.get_assembly_mass_properties(
            document_id=document_id,
            wvm_type=wvm_type,
            wvm_id=version_id,
            element_id=element_id,
        )

    def _load_raw_bbox(self, document_id: str, version_id: str, element_id: str) -> dict[str, Any]:
        """Load raw bounding box JSON from client or fixtures."""
        if self.use_fixtures:
            fixture_name = "bounding_boxes_v2.json" if version_id == "9c4d6e8a23f5b7a9c1d3f5b7" else "bounding_boxes_v1.json"
            fixture_path = self.fixtures_dir / fixture_name
            if fixture_path.exists():
                with open(fixture_path, encoding="utf-8") as f:
                    return json.load(f)
            return {}

        if not self.client:
            return {}

        wvm_type = "v"
        return self.client.get_assembly_bounding_boxes(
            document_id=document_id,
            wvm_type=wvm_type,
            wvm_id=version_id,
            element_id=element_id,
        )

    def get_assembly(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> AssemblyHierarchy:
        """Extract complete assembly structure, subassemblies, and instances."""
        elem_id = element_reference or "default_assembly"
        raw_asm = self._load_raw_assembly(document_reference, version_reference, elem_id)
        raw_bbox = self._load_raw_bbox(document_reference, version_reference, elem_id)
        return parse_onshape_assembly_hierarchy(raw_asm, overall_bounding_box_data=raw_bbox)

    def get_components(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> list[ComponentDefinition]:
        """Extract deduplicated component definitions, metadata, and materials."""
        elem_id = element_reference or "default_assembly"
        raw_asm = self._load_raw_assembly(document_reference, version_reference, elem_id)
        raw_mass = self._load_raw_mass(document_reference, version_reference, elem_id)
        components, _ = extract_component_definitions(raw_asm, raw_mass)
        return components

    def get_mass_properties(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> MassProperties:
        """Extract assembly mass properties, center of mass, and inertia."""
        elem_id = element_reference or "default_assembly"
        raw_mass = self._load_raw_mass(document_reference, version_reference, elem_id)
        return parse_onshape_mass_properties(raw_mass, is_assembly=True, entity_id=elem_id)

    def extract_snapshot(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> Snapshot:
        """Generate a complete canonical Snapshot from Onshape."""
        elem_id = element_reference or "default_assembly"
        raw_asm = self._load_raw_assembly(document_reference, version_reference, elem_id)
        raw_mass = self._load_raw_mass(document_reference, version_reference, elem_id)
        raw_bbox = self._load_raw_bbox(document_reference, version_reference, elem_id)

        # 1. Assembly hierarchy & occurrences
        assembly = parse_onshape_assembly_hierarchy(raw_asm, overall_bounding_box_data=raw_bbox)

        # 2. Components & missing value audit
        components, missing_values = extract_component_definitions(raw_asm, raw_mass)

        # 3. Assembly aggregate mass properties
        assembly_mass = parse_onshape_mass_properties(raw_mass, is_assembly=True, entity_id=assembly.assembly_id)

        warnings: list[WarningRecord] = []
        if assembly_mass.mass is None:
            warnings.append(
                WarningRecord(
                    code="WARN_MISSING_ASSEMBLY_MASS",
                    message="Overall assembly mass is unavailable from source CAD model",
                    entity_id=assembly.assembly_id,
                )
            )

        # Resolve version metadata
        version_name = f"Version {version_reference}"
        microversion_id: str | None = None
        versions = self.get_versions(document_reference)
        for v in versions:
            if v.get("id") == version_reference:
                version_name = v.get("name", version_name)
                microversion_id = v.get("microversion")
                break

        doc_ref = DocumentReference(
            document_id=document_reference,
            document_name=raw_asm.get("documentName", f"Document {document_reference}"),
            element_id=assembly.assembly_id,
            element_name=assembly.name,
            version_id=version_reference,
            version_name=version_name,
            microversion_id=microversion_id,
        )

        return Snapshot(
            snapshot_id=str(uuid.uuid4()),
            source="onshape",
            document=doc_ref,
            units=UnitsSchema(),
            assembly=assembly,
            components=components,
            assembly_properties={"assembly_element_id": assembly.assembly_id},
            assembly_mass_properties=assembly_mass,
            provenance={
                "extracted_from": "Onshape REST API",
                "adapter": "OnshapeConnector",
                "uses_fixtures": self.use_fixtures,
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
        """Check for changes between two versions."""
        return {
            "document_id": document_reference,
            "previous_version": previous_version_ref,
            "current_version": current_version_ref,
            "has_version_change": previous_version_ref != current_version_ref,
        }
