"""Entrypoint detection for code graph builder."""

from __future__ import annotations

from .models import CodeGraph


def find_interface_entrypoints(graph: CodeGraph) -> set[str]:
    """
    Find all FastAPI endpoints and CLI commands.

    These are the actual entry points that external clients/users can invoke.
    Used to identify dead code by computing what's reachable from real endpoints.

    Returns a set of node IDs that are interface entrypoints.
    """
    entrypoints = set()

    for node in graph.nodes:
        if node.layer != "interfaces":
            continue

        if node.kind not in {"function", "method"}:
            continue

        # FastAPI entrypoints: functions in *_if.py files
        if "_if.py" in node.file or node.file.endswith("_if.py"):
            entrypoints.add(node.id)

        # CLI entrypoints: cmd_* functions in CLI commands
        if node.kind == "function" and node.name.startswith("cmd_"):
            entrypoints.add(node.id)

        # CLI main entrypoint
        if node.name == "main" and "cli" in node.file:
            entrypoints.add(node.id)

    return entrypoints
