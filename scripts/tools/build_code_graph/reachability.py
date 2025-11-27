"""Reachability analysis for code graph builder."""

from __future__ import annotations

from collections import defaultdict, deque

from .models import CodeGraph


def compute_reachability(graph: CodeGraph, entrypoints: set[str]) -> None:
    """
    Compute reachability from interface entrypoints using BFS.

    Updates node.reachable_from_interface in place.
    """
    # Build adjacency list from CALLS and USES_TYPE edges
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.type in {"CALLS", "USES_TYPE"}:
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

    # Update nodes
    node_map = {node.id: node for node in graph.nodes}
    for node_id in visited:
        if node_id in node_map:
            node_map[node_id].reachable_from_interface = True
