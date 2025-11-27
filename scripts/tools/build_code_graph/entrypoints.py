"""Entrypoint detection for code graph builder."""

from __future__ import annotations

from .models import CodeGraph


def find_interface_entrypoints(graph: CodeGraph) -> set[str]:
    """
    Find all interface entrypoints (FastAPI routes, CLI commands, and modules).

    Returns a set of node IDs that are interface entrypoints.
    """
    entrypoints = set()

    for node in graph.nodes:
        if node.layer != "interfaces":
            continue

        # Module-level code in interfaces layer is an entrypoint
        # (handles FastAPI app setup, decorators, etc.)
        if node.kind == "module":
            entrypoints.add(node.id)

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
