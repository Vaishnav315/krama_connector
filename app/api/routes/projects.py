"""Project and linked document endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.connection import Connection
from app.models.document import LinkedDocument
from app.models.project import Project
from app.schemas.api import LinkDocumentRequest, LinkedDocumentResponse

router = APIRouter(prefix="/projects", tags=["Projects & Documents"])


@router.post("/{project_id}/documents", response_model=LinkedDocumentResponse, status_code=status.HTTP_201_CREATED)
def link_document_to_project(
    project_id: str,
    request: LinkDocumentRequest,
    db: Session = Depends(get_db),
) -> LinkedDocumentResponse:
    """Link an Onshape document/assembly to a KRAMA project."""
    # Ensure project exists or create default project record
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        project = Project(
            id=project_id,
            name=f"Project {project_id}",
            description="Auto-provisioned KRAMA project",
        )
        db.add(project)
        db.commit()

    # Validate connection exists
    conn = db.query(Connection).filter(Connection.id == request.connection_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{request.connection_id}' not found",
        )

    # Check for existing document link
    existing = (
        db.query(LinkedDocument)
        .filter(
            (LinkedDocument.project_id == project_id)
            & (LinkedDocument.document_id == request.document_id)
            & (LinkedDocument.element_id == request.element_id)
        )
        .first()
    )
    if existing:
        return LinkedDocumentResponse(
            id=existing.id,
            project_id=existing.project_id,
            connection_id=existing.connection_id,
            document_id=existing.document_id,
            element_id=existing.element_id,
            workspace_id=existing.workspace_id,
            last_synced_version_id=existing.last_synced_version_id,
            last_synced_at=existing.last_synced_at,
            created_at=existing.created_at,
        )

    doc = LinkedDocument(
        id=str(uuid.uuid4()),
        project_id=project_id,
        connection_id=request.connection_id,
        document_id=request.document_id,
        element_id=request.element_id,
        workspace_id=request.workspace_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return LinkedDocumentResponse(
        id=doc.id,
        project_id=doc.project_id,
        connection_id=doc.connection_id,
        document_id=doc.document_id,
        element_id=doc.element_id,
        workspace_id=doc.workspace_id,
        last_synced_version_id=doc.last_synced_version_id,
        last_synced_at=doc.last_synced_at,
        created_at=doc.created_at,
    )
