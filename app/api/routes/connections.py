"""CAD account connection endpoints (Onshape and FreeCAD)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.connectors.freecad.adapter import DEFAULT_WATCH_FILE
from app.database import get_db
from app.models.connection import Connection
from app.schemas.api import (
    ConnectionCreateRequest,
    ConnectionResponse,
    FreeCADConnectionCreateRequest,
)

router = APIRouter(prefix="/connections", tags=["Connections"])


@router.post("/onshape", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
def connect_onshape_account(
    request: ConnectionCreateRequest,
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """Register or reference an Onshape CAD connection.

    Safety: Secrets are never logged or stored in plain text.
    Masked identifiers are returned for auditing.
    """
    if request.access_key:
        masked = (
            f"{request.access_key[:4]}...{request.access_key[-4:]}"
            if len(request.access_key) > 8
            else "****"
        )
    elif request.oauth_token:
        masked = "OAuth2-Bearer-Token"
    else:
        masked = "ENV:ONSHAPE_ACCESS_KEY"

    conn = Connection(
        id=str(uuid.uuid4()),
        name=request.name,
        provider="onshape",
        base_url=request.base_url,
        access_key_masked=masked,
        secret_key_ref="ENV:ONSHAPE_SECRET_KEY",
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    return ConnectionResponse(
        id=conn.id,
        name=conn.name,
        provider=conn.provider,
        base_url=conn.base_url,
        access_key_masked=conn.access_key_masked,
        is_active=conn.is_active,
        created_at=conn.created_at,
    )


@router.post("/freecad", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
def connect_freecad(
    request: FreeCADConnectionCreateRequest,
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """Register a FreeCAD local bridge connection.

    The FreeCAD bridge reads design state from a live_state.json file written
    by the freecad_observer_bridge.FCMacro observer macro.  In headless production
    use, FreeCADCmd exports the state file on a cron/systemd schedule; the HTTP
    API then consumes it without requiring the GUI.

    The watch_file path is stored in base_url so that SyncService can dispatch
    FreeCADConnector(watch_file=connection.base_url) for POST /projects/{id}/sync.
    """
    watch_path = request.watch_file or str(DEFAULT_WATCH_FILE)

    conn = Connection(
        id=str(uuid.uuid4()),
        name=request.name,
        provider="freecad",
        base_url=watch_path,
        access_key_masked="FREECAD_LOCAL_BRIDGE",
        secret_key_ref="NONE",
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    return ConnectionResponse(
        id=conn.id,
        name=conn.name,
        provider=conn.provider,
        base_url=conn.base_url,
        access_key_masked=conn.access_key_masked,
        is_active=conn.is_active,
        created_at=conn.created_at,
    )
