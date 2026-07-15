"""SQLAlchemy declarative base for all PostgreSQL ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for Nomarr SQLAlchemy models."""
