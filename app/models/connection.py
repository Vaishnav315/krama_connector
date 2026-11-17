"""SQLAlchemy model for connected Onshape account credentials."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Connection(Base):
    """Stores connection credentials reference.

    IMPORTANT: To maintain credential security, raw secrets are never committed
    or logged in plain text. Secret key references specify environment variable lookups.
    """

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="onshape", nullable=False)
    base_url: Mapped[str] = mapped_column(String(256), default="https://cad.onshape.com", nullable=False)
    access_key_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_key_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="ENV:ONSHAPE_SECRET_KEY")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    documents = relationship("LinkedDocument", back_populates="connection", cascade="all, delete-orphan")
