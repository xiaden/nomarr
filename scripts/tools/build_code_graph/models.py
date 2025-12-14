"""Data models for code graph."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    """Represents a code entity (module, class, function, method)."""

    id: str
    kind: str  # "module" | "class" | "function" | "method"
    layer: str
    file: str
    name: str
    lineno: int
    end_lineno: int
    loc: int
    docstring: str | None = None
    attributes: list[str] = field(default_factory=list)  # For classes
    params: list[str] = field(default_factory=list)  # For functions/methods
    return_annotation: str | None = None  # For functions/methods
    return_var_names: list[str] = field(default_factory=list)  # For functions/methods
    reachable_from_interface: bool = False


@dataclass
class Edge:
    """Represents a relationship between code entities."""

    source_id: str
    target_id: str
    type: str  # "CONTAINS" | "IMPORTS" | "CALLS"
    linenos: list[int] = field(default_factory=list)  # All line numbers where this edge occurs
    details: list[str] = field(default_factory=list)  # Additional details for each occurrence


@dataclass
class CodeGraph:
    """Complete code graph with nodes and edges."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
