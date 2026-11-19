"""API request and response schemas for FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check status response."""

    status: str = "healthy"
    version: str
    environment: str
    timestamp: datetime


class ConnectionCreateRequest(BaseModel):
    """Request payload to connect a CAD account or credential reference."""

    name: str = Field(description="Display label for the connection", json_schema_extra={"example": "Engineering Team Onshape"})
    provider: str = Field(default="onshape", description="CAD provider type ('onshape' or 'freecad')")
    base_url: str = Field(default="https://cad.onshape.com", description="Onshape instance URL or FreeCAD bridge file path")
    access_key: str | None = Field(default=None, description="Onshape API access key (optional if using .env)")
    secret_key: str | None = Field(default=None, description="Onshape API secret key (optional if using .env)")
    oauth_token: str | None = Field(default=None, description="OAuth2 Bearer token (optional)")


class FreeCADConnectionCreateRequest(BaseModel):
    """Request payload to register a FreeCAD bridge connection."""

    name: str = Field(default="FreeCAD Local Bridge", description="Display label", json_schema_extra={"example": "FreeCAD Desktop Bridge"})
    watch_file: str | None = Field(default=None, description="Path to live_state.json state file", json_schema_extra={"example": "/path/to/live_state.json"})


class ConnectionResponse(BaseModel):
    """Safe connection representation concealing raw secret keys."""

    id: str
    name: str
    provider: str
    base_url: str
    access_key_masked: str
    is_active: bool
    created_at: datetime


class LinkDocumentRequest(BaseModel):
    """Request payload to link an Onshape assembly document to a KRAMA project."""

    connection_id: str = Field(description="UUID of the connected Onshape account")
    document_id: str = Field(description="Onshape document ID", json_schema_extra={"example": "65a1f2b3c4d5e6f7a8b9c0d1"})
    element_id: str = Field(description="Onshape assembly element ID", json_schema_extra={"example": "43210fedcba9876543210fed"})
    workspace_id: str | None = Field(default=None, description="Optional workspace ID")


class LinkedDocumentResponse(BaseModel):
    """Linked document response representation."""

    id: str
    project_id: str
    connection_id: str
    document_id: str
    element_id: str
    workspace_id: str | None
    last_synced_version_id: str | None
    last_synced_at: datetime | None
    created_at: datetime


class SyncRequest(BaseModel):
    """Request payload to trigger synchronization."""

    document_id: str = Field(description="Database linked document ID or Onshape document ID")
    version_id: str | None = Field(default=None, description="Specific version to snapshot; latest if omitted")
    force: bool = Field(default=False, description="Force sync even if version matches last sync")


class SyncResponse(BaseModel):
    """Synchronization execution result."""

    sync_run_id: str
    project_id: str
    document_id: str
    status: str
    version_id: str
    microversion_id: str | None
    snapshot_id: str | None
    records_synced: int
    duration_ms: float | None
    message: str


class SnapshotSummary(BaseModel):
    """Summary record for a snapshot in listings."""

    snapshot_id: str
    project_id: str
    document_id: str
    version_id: str
    version_name: str
    microversion_id: str | None
    element_id: str
    total_mass: float | None
    instance_count: int
    component_count: int
    extracted_at: datetime
    created_at: datetime


class ChangeCheckResponse(BaseModel):
    """Summary of source changes detected for a project's linked documents."""

    project_id: str
    documents_checked: int
    changes: list[dict[str, Any]]
