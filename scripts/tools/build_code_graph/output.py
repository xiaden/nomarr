"""Output generation for code graph builder."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import CodeGraph


def write_output(graph: CodeGraph, output_path: Path, project_root: Path, search_paths: list[Path]) -> None:
    """Write the complete graph to a JSON file."""
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build output structure
    output = {
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "project_root": str(project_root),
            "search_paths": [str(p) for p in search_paths],
            "version": 1,
        },
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"✓ Code graph written to: {output_path}")
    print(f"  - {len(graph.nodes)} nodes")
    print(f"  - {len(graph.edges)} edges")

    # Summary statistics
    reachable_count = sum(1 for node in graph.nodes if node.reachable_from_interface)
    print(f"  - {reachable_count} nodes reachable from interface entrypoints")
