"""SQLAlchemy model for KRAMA engineering projects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """Represents a destination KRAMA engineering project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    documents = relationship("LinkedDocument", back_populates="project", cascade="all, delete-orphan")
    sync_runs = relationship("SyncRun", back_populates="project", cascade="all, delete-orphan")
    snapshots = relationship("SnapshotRecord", back_populates="project", cascade="all, delete-orphan")
