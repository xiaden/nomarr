"""Reachability analysis for code graph builder."""

from __future__ import annotations

from collections import defaultdict, deque

from .models import CodeGraph


def compute_reachability(graph: CodeGraph, entrypoints: set[str]) -> None:
    """Compute reachability from interface entrypoints using BFS.

    Updates node.reachable_from_interface in place.
    """
    from .edge_types import REACHABLE_EDGE_TYPES

    # Build adjacency list from all reachable edge types
    # Includes all CALLS_* variants, USES_TYPE, and IMPORTS
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.type in REACHABLE_EDGE_TYPES:
            adjacency[edge.source_id].add(edge.target_id)

    # BFS from all entrypoints
    visited = set()
    queue = deque(entrypoints)
    visited.update(entrypoints)

    while queue:
        current_id = queue.popleft()

        for neighbor_id in adjacency[current_id]:
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                queue.append(neighbor_id)

    # Also mark parent modules as reachable (for IMPORTS traversal)
    # If "module.Class.method" is reachable, so is "module" and "module.Class"
    expanded_visited = set(visited)
    for node_id in visited:
        parts = node_id.split(".")
        for i in range(1, len(parts)):
            parent_id = ".".join(parts[:i])
            expanded_visited.add(parent_id)

    # Update nodes
    node_map = {node.id: node for node in graph.nodes}
    for node_id in expanded_visited:
        if node_id in node_map:
            node_map[node_id].reachable_from_interface = True
