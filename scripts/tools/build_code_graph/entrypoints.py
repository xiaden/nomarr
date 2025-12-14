"""Entrypoint detection for code graph builder."""

from __future__ import annotations

from .models import CodeGraph


def find_interface_entrypoints(graph: CodeGraph) -> set[str]:
    """
    Find application-level entrypoints.

    These are the top-level modules/objects that external runners (uvicorn, CLI, process spawners)
    directly invoke. Everything else must be reachable from these to be considered live code.

    Strategy:
    - API: api_app module (uvicorn entrypoint that wires all routers)
    - CLI: main() and cmd_* functions (Click entrypoints)
    - Workers: BaseWorker.run() methods (multiprocessing entrypoints)

    This lets us detect dead *_if files that aren't wired into api_app,
    and dead routers that aren't included anywhere.

    Returns a set of node IDs that are entrypoints.
    """
    entrypoints = set()

    for node in graph.nodes:
        # API entrypoint: The FastAPI app module
        if node.layer == "interfaces" and node.kind == "module":
            if node.id == "nomarr.interfaces.api.api_app":
                entrypoints.add(node.id)

        # CLI entrypoints
        if node.layer == "interfaces" and node.kind == "function":
            # CLI main() function
            if node.name == "main" and "cli" in node.file:
                entrypoints.add(node.id)
            # CLI cmd_* commands
            if node.name.startswith("cmd_"):
                entrypoints.add(node.id)

        # Background worker entrypoints (services layer)
        # Workers are multiprocessing.Process subclasses with run() method as entrypoint
        if node.layer == "services" and node.kind == "method" and node.name == "run":
            # BaseWorker.run() and its subclasses (TaggerWorker, LibraryScanWorker, RecalibrationWorker)
            if "workers" in node.file and "Worker" in node.id:
                entrypoints.add(node.id)

    return entrypoints
