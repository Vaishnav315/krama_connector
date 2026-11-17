"""SQLAlchemy database engine and session dependency.

Supports SQLite for local development and test automation,
and PostgreSQL for production environments via DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy database models."""


def create_db_engine(db_url: str | None = None):
    """Create SQLAlchemy engine with appropriate dialect arguments."""
    settings = get_settings()
    url = db_url or settings.DATABASE_URL

    connect_args = {}
    if url.startswith("sqlite"):
        # SQLite requires check_same_thread=False for multi-threaded FastAPI execution
        connect_args["check_same_thread"] = False

    return create_engine(
        url,
        connect_args=connect_args,
        echo=settings.DEBUG,
    )


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """Create all configured database tables."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a SQLAlchemy database session with automatic teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
