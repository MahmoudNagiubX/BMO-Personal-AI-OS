"""SQLAlchemy declarative metadata for future domain models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base metadata; Phase 2 intentionally defines no product tables."""
