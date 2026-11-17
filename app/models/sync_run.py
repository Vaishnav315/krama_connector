"""SQLAlchemy model for sync execution history and auditing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyncRun(Base):
    """Audit record for a synchronization execution against Onshape."""

    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("linked_documents.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    version_id: Mapped[str] = mapped_column(String(128), nullable=False)
    microversion_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    records_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    project = relationship("Project", back_populates="sync_runs")
    document = relationship("LinkedDocument", back_populates="sync_runs")
