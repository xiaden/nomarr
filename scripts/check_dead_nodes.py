"""
Analyze potentially dead code using the code graph.

This script identifies unreachable nodes (functions, methods, classes) that are
not reachable from interface entrypoints and analyzes whether they're truly dead
by checking imports, calls, type usage, and raw grep hits.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


def analyze_dead_node(
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    """
    Analyze a single potentially dead node.

    Args:
        node: Node from code graph
        edges: All edges from code graph
        project_root: Project root path for grep search

    Returns:
        Analysis dict with metadata, edge counts, grep hits, and dead assessment
    """
    node_id = node["id"]
    node_name = node["name"]
    node_file = node["file"]

    # Count edges by type
    imports = [e for e in edges if e["target_id"] == node_id and e["type"] == "IMPORTS"]
    calls = [e for e in edges if e["target_id"] == node_id and e["type"] == "CALLS"]
    uses_type = [e for e in edges if e["target_id"] == node_id and e["type"] == "USES_TYPE"]
    inherits = [e for e in edges if e["target_id"] == node_id and e["type"] == "INHERITS"]
    creates_instance = [e for e in edges if e["target_id"] == node_id and e["type"] == "CREATES_INSTANCE"]

    # Raw grep search through codebase
    grep_files: list[str] = []
    grep_failed = False

    try:
        # Use git grep for fast search
        result = subprocess.run(
            ["git", "grep", "-l", node_name],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip():
            all_files = result.stdout.strip().split("\n")
            # Filter out the defining file itself
            grep_files = [f for f in all_files if f and not f.endswith(node_file)]
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        grep_failed = True

    # Determine if likely dead
    has_usage = bool(calls or uses_type or inherits or creates_instance)
    has_external_references = bool(grep_files)

    likely_dead = False
    reason = ""

    if not has_usage and not has_external_references:
        likely_dead = True
        if imports:
            reason = "imported but never called or used in types"
        else:
            reason = "no calls, no type uses, no grep hits"
    elif not has_usage and has_external_references:
        likely_dead = False
        reason = "grep hits exist but not in graph (may be dynamic or test usage)"
    else:
        likely_dead = False
        reason = "has usage in graph"

    return {
        "node": node,
        "edges": {
            "imports": len(imports),
            "calls": len(calls),
            "uses_type": len(uses_type),
            "inherits": len(inherits),
            "creates_instance": len(creates_instance),
        },
        "import_sources": [e["source_id"] for e in imports[:3]],
        "grep_files": grep_files[:3],
        "grep_failed": grep_failed,
        "likely_dead": likely_dead,
        "reason": reason,
    }


def should_analyze_node(node: dict[str, Any]) -> bool:
    """
    Determine if a node should be analyzed for dead code.

    Filters out:
    - Private names (start with "_")
    - Dunder methods (__init__, __repr__, etc.)
    - Test layer nodes
    - Module nodes (for now)
    """
    name = node["name"]
    kind = node["kind"]
    layer = node.get("layer", "")
    file_path = node.get("file", "")

    # Skip modules (analyzing files/modules differently)
    if kind == "module":
        return False

    # Skip test layer
    if layer == "tests" or "tests/" in file_path or "/test_" in file_path:
        return False

    # Skip private names
    if name.startswith("_"):
        return False

    return True


def main() -> int:
    """Main entry point."""
    # Load graph
    script_dir = Path(__file__).parent
    graph_path = script_dir / "outputs" / "code_graph.json"
    project_root = script_dir.parent

    print(f"Loading code graph from: {graph_path}")
    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)

    nodes = data["nodes"]
    edges = data["edges"]

    print(f"Total nodes: {len(nodes)}")
    print(f"Total edges: {len(edges)}")
    print()

    # Find unreachable nodes that should be analyzed
    candidates = [n for n in nodes if not n.get("reachable_from_interface") and should_analyze_node(n)]

    print(f"Unreachable nodes (after filtering): {len(candidates)}")
    print()

    # Analyze all candidates
    print("Analyzing unreachable nodes...")
    analyses = []
    for node in candidates:
        analysis = analyze_dead_node(node, edges, project_root)
        analyses.append(analysis)

    # Group by layer and kind
    by_layer_kind: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    dead_count = 0

    for analysis in analyses:
        node = analysis["node"]
        layer = node.get("layer", "unknown")
        kind = node["kind"]
        key = (layer, kind)
        by_layer_kind[key].append(analysis)

        if analysis["likely_dead"]:
            dead_count += 1

    # Print summary
    print()
    print("=" * 80)
    print("SUMMARY BY LAYER AND KIND")
    print("=" * 80)
    print()

    summary_items = sorted(by_layer_kind.items(), key=lambda x: (x[0][0], x[0][1]))
    for (layer, kind), items in summary_items:
        total = len(items)
        dead = sum(1 for item in items if item["likely_dead"])
        print(f"{layer:20} {kind:12} Total: {total:4}  Likely Dead: {dead:4}")

    print()
    print(f"Total unreachable: {len(candidates)}")
    print(f"Total likely dead: {dead_count}")
    print()

    # Print detailed analysis for likely dead nodes
    likely_dead_analyses = [a for a in analyses if a["likely_dead"]]

    if likely_dead_analyses:
        print("=" * 80)
        print("DETAILED ANALYSIS - LIKELY DEAD NODES")
        print("=" * 80)
        print()

        # Sort by file + lineno for stable output
        likely_dead_analyses.sort(key=lambda a: (a["node"]["file"], a["node"].get("lineno", 0)))

        for analysis in likely_dead_analyses:
            node = analysis["node"]
            edges_info = analysis["edges"]

            print(f"{node['id']}")
            print(f"  File: {node['file']}:{node.get('lineno', '?')}")
            print(f"  Kind: {node['kind']}")
            print(f"  Layer: {node.get('layer', 'unknown')}")
            print()
            print(f"  Imports: {edges_info['imports']}")
            print(f"  Calls: {edges_info['calls']}")
            print(f"  Type uses: {edges_info['uses_type']}")
            print(f"  Inherits: {edges_info['inherits']}")
            print(f"  Creates instance: {edges_info['creates_instance']}")

            if analysis["import_sources"]:
                print(f"  Import sources: {', '.join(analysis['import_sources'])}")

            if analysis["grep_failed"]:
                print("  Raw grep: (failed)")
            else:
                grep_count = len(analysis["grep_files"])
                print(f"  Raw grep mentions: {grep_count} files")
                if analysis["grep_files"]:
                    for file_path in analysis["grep_files"]:
                        print(f"    - {file_path}")

            print(f"  ⚠️  LIKELY DEAD - {analysis['reason']}")
            print()
    else:
        print("✓ No likely dead nodes found!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
