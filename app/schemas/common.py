"""Common schemas for units, provenance, warnings, and missing values."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProvenanceSource(StrEnum):
    """Provenance origin classification for physical and metadata measurements."""

    COMPUTED_FROM_GEOMETRY = "computed_from_geometry"
    ENTERED_MANUALLY = "entered_manually"
    SOURCE_UNAVAILABLE = "source_unavailable"
    NOT_YET_VERIFIED = "not_yet_verified"
    INFERRED = "inferred"


class ProvenanceRecord(BaseModel):
    """Provenance tracking for a specific property or entity."""

    source: ProvenanceSource
    description: str = Field(description="Human-readable explanation of property origin")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_source_field: str | None = None


class MissingValueRecord(BaseModel):
    """Explicit audit record for any expected property missing from the source CAD model."""

    entity_id: str
    entity_type: str = Field(description="e.g., 'part', 'assembly', 'instance'")
    property_name: str
    reason: str = Field(description="Clear explanation why the value is absent in the source")
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WarningRecord(BaseModel):
    """Non-fatal diagnostic warning encountered during snapshot extraction."""

    code: str
    message: str
    entity_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CustomProperty(BaseModel):
    """User-defined or metadata property defined in Onshape."""

    name: str
    value: Any
    data_type: str | None = None
    property_id: str | None = None
    source: str = "onshape_metadata"


class UnitsSchema(BaseModel):
    """Explicit units declaration for all numerical physical quantities in the snapshot."""

    length: str = "meter"
    mass: str = "kilogram"
    time: str = "second"
    inertia: str = "kilogram * meter^2"
    volume: str = "meter^3"
    surface_area: str = "meter^2"
    angle: str = "radian"
