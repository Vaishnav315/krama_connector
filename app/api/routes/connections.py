"""Onshape account connection endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.connection import Connection
from app.schemas.api import ConnectionCreateRequest, ConnectionResponse

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
    # Create masked access key display
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
