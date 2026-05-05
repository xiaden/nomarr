"""Shared schema-era enums and errors used during the persistence transition."""

from __future__ import annotations

from enum import StrEnum


class CollectionType(StrEnum):
    """Types of ArangoDB collections."""

    DOCUMENT = "document"
    EDGE = "edge"
    STATE_GRAPH = "state_graph"
    TEMPLATE = "template"
    INFRASTRUCTURE = "infrastructure"


class SchemaValidationError(RuntimeError):
    """Raised when legacy schema declarations are internally inconsistent."""


class CapabilityError(RuntimeError):
    """Raised when a legacy namespace method is called without the required capability."""
