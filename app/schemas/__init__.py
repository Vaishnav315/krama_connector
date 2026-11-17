"""Pydantic schemas package for CAD domain modeling."""

from app.schemas.assembly import AssemblyHierarchy, InstanceNode
from app.schemas.common import (
    CustomProperty,
    MissingValueRecord,
    ProvenanceRecord,
    ProvenanceSource,
    UnitsSchema,
    WarningRecord,
)
from app.schemas.component import ComponentDefinition
from app.schemas.diff import (
    AssemblyDelta,
    ChangeClassification,
    ComponentDiff,
    InstanceDiff,
    QuantityChange,
    SnapshotDiff,
    ValueChange,
)
from app.schemas.geometry import BoundingBox3D
from app.schemas.mass_properties import InertiaTensor, MassProperties
from app.schemas.snapshot import DocumentReference, Snapshot

__all__ = [
    "AssemblyDelta",
    "AssemblyHierarchy",
    "BoundingBox3D",
    "ChangeClassification",
    "ComponentDefinition",
    "ComponentDiff",
    "CustomProperty",
    "DocumentReference",
    "InertiaTensor",
    "InstanceDiff",
    "InstanceNode",
    "MassProperties",
    "MissingValueRecord",
    "ProvenanceRecord",
    "ProvenanceSource",
    "QuantityChange",
    "Snapshot",
    "SnapshotDiff",
    "UnitsSchema",
    "ValueChange",
    "WarningRecord",
]
