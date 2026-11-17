"""SQLAlchemy model for linked Onshape documents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LinkedDocument(Base):
    """Represents an Onshape assembly document linked to a KRAMA project."""

    __tablename__ = "linked_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("connections.id"), nullable=False)

    document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    last_synced_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_microversion_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    project = relationship("Project", back_populates="documents")
    connection = relationship("Connection", back_populates="documents")
    sync_runs = relationship("SyncRun", back_populates="document", cascade="all, delete-orphan")
    snapshots = relationship("SnapshotRecord", back_populates="document", cascade="all, delete-orphan")
