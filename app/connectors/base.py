"""Abstract CAD/PLM Connector Base Interface.

KRAMA connects to multiple CAD and PLM systems (Onshape, Teamcenter, SolidWorks PDM, etc.).
All system-specific implementations must inherit from CADConnector to ensure the rest of the
application remains completely decoupled from vendor-specific response payloads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.assembly import AssemblyHierarchy
from app.schemas.component import ComponentDefinition
from app.schemas.mass_properties import MassProperties
from app.schemas.snapshot import Snapshot


class CADConnector(ABC):
    """Abstract interface defining the standard capabilities of any CAD/PLM connector."""

    @abstractmethod
    def connect(self) -> bool:
        """Verify authentication and network connectivity to the CAD system.

        Returns:
            True if connection and authentication succeed, False otherwise.
        """
        ...

    @abstractmethod
    def get_document(self, document_reference: str) -> dict[str, Any]:
        """Retrieve top-level document metadata.

        Args:
            document_reference: Vendor-specific document identifier.
        """
        ...

    @abstractmethod
    def get_versions(self, document_reference: str) -> list[dict[str, Any]]:
        """List all committed/immutable versions of the document.

        Args:
            document_reference: Vendor-specific document identifier.
        """
        ...

    @abstractmethod
    def get_assembly(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> AssemblyHierarchy:
        """Extract complete assembly structure, subassemblies, and instances.

        Args:
            document_reference: Document ID.
            version_reference: Version or workspace identifier.
            element_reference: Specific assembly tab or model element ID.
        """
        ...

    @abstractmethod
    def get_components(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> list[ComponentDefinition]:
        """Extract deduplicated component definitions, metadata, and materials."""
        ...

    @abstractmethod
    def get_mass_properties(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> MassProperties:
        """Extract assembly mass properties, center of mass, and inertia with provenance."""
        ...

    @abstractmethod
    def extract_snapshot(
        self,
        document_reference: str,
        version_reference: str,
        element_reference: str | None = None,
    ) -> Snapshot:
        """Generate a complete canonical Snapshot from the CAD system."""
        ...

    @abstractmethod
    def detect_changes(
        self,
        document_reference: str,
        previous_version_ref: str,
        current_version_ref: str,
    ) -> dict[str, Any]:
        """Query source CAD system for change records between two versions."""
        ...
