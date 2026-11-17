"""SQLAlchemy model for versioned snapshot records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SnapshotRecord(Base):
    """Database record for an extracted versioned CAD snapshot."""

    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("linked_documents.id"), nullable=False)

    version_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version_name: Mapped[str] = mapped_column(String(128), nullable=False)
    microversion_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    element_id: Mapped[str] = mapped_column(String(128), nullable=False)

    total_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    instance_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    component_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    project = relationship("Project", back_populates="snapshots")
    document = relationship("LinkedDocument", back_populates="snapshots")
