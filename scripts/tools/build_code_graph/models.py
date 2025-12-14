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
    ast_context: str | None = None  # How this node was discovered (ModuleLevel, ClassMember, etc)


@dataclass
class Edge:
    """Represents a relationship between code entities.

    ALL edges MUST have ast_case set. Missing ast_case (None) indicates
    a bug in edge creation logic. This helps catch errors and track how
    each edge was created.
    """

    source_id: str
    target_id: str
    type: str  # Edge types: CONTAINS | IMPORTS | CALLS_* | USES_TYPE
    # CALLS_FUNCTION: direct function call
    # CALLS_METHOD: method call on object
    # CALLS_CLASS: class instantiation
    # CALLS_ATTRIBUTE: module attribute access
    # CALLS_DEPENDENCY: dependency injection
    # CALLS_THREAD_TARGET: thread target callable
    linenos: list[int] = field(default_factory=list)  # All line numbers where this edge occurs
    details: list[str] = field(default_factory=list)  # Additional details for each occurrence
    ast_case: str | None = None  # Which AST matching case created this edge (required for call-based edges)


@dataclass
class CodeGraph:
    """Complete code graph with nodes and edges."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
