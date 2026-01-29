#!/usr/bin/env python3
"""Simplify code graph by aggregating methods under classes.

Takes the detailed method-level graph and creates a coarse class-level view
suitable for visualization, while preserving method information in edge metadata.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tools.build_code_graph.models import CodeGraph, Edge, Node


def get_parent_id(node_id: str, node_kind: str) -> str:
    """Get the parent container for a node.

    Methods -> their class
    Functions -> their module
    Classes -> their module
    Modules -> keep as-is
    """
    if node_kind == "method":
        # Remove method name: "module.Class.method" -> "module.Class"
        parts = node_id.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else node_id
    elif node_kind == "function":
        # Remove function name: "module.function" -> "module"
        parts = node_id.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else node_id
    else:
        # Classes and modules stay as-is
        return node_id


def simplify_graph(detailed_graph: CodeGraph) -> CodeGraph:
    """Create simplified graph with methods aggregated under classes.

    Process:
    1. Keep module and class nodes as-is
    2. Keep top-level function nodes as-is
    3. Remove method nodes (merge into parent class)
    4. Aggregate edges by (source_parent, target_parent)
    5. Store method names in edge details
    """
    # Track which nodes to keep
    simplified_nodes: dict[str, Node] = {}

    # Map from detailed node_id -> parent node_id
    node_to_parent: dict[str, str] = {}

    # Build parent mapping and collect nodes to keep
    for node in detailed_graph.nodes:
        if node.kind in ("module", "class", "function"):
            # Keep these nodes - they are their own parent in the simplified graph
            simplified_nodes[node.id] = node
            node_to_parent[node.id] = node.id
        else:
            # Methods get aggregated to their parent class
            parent_id = get_parent_id(node.id, node.kind)
            node_to_parent[node.id] = parent_id

    # Aggregate edges
    # Key: (source_parent, target_parent, edge_type)
    # Value: list of (source_method, target_method, lineno, ast_case)
    edge_groups: dict[tuple[str, str, str], list[tuple[str, str, int, str | None]]] = defaultdict(list)

    for edge in detailed_graph.edges:
        # Skip CONTAINS edges - they're structural, not calls
        if edge.type == "CONTAINS":
            continue

        source_parent = node_to_parent.get(edge.source_id, edge.source_id)
        target_parent = node_to_parent.get(edge.target_id, edge.target_id)

        # Skip self-loops at parent level (class calling its own methods)
        if source_parent == target_parent:
            continue

        # Extract method names from full IDs
        source_method = edge.source_id.split(".")[-1] if edge.source_id != source_parent else None
        target_method = edge.target_id.split(".")[-1] if edge.target_id != target_parent else None

        lineno = edge.linenos[0] if edge.linenos else 0

        edge_groups[(source_parent, target_parent, edge.type)].append(
            (source_method, target_method, lineno, edge.ast_case)
        )

    # Create simplified edges
    simplified_edges: list[Edge] = []

    for (source_id, target_id, edge_type), method_calls in edge_groups.items():
        # Aggregate line numbers
        all_linenos = [lineno for _, _, lineno, _ in method_calls if lineno]

        # Collect unique methods (filter out __init__ and __call__ as they're implicit)
        source_methods = list({src for src, _, _, _ in method_calls if src and src not in ("__init__", "__call__")})
        target_methods = list({tgt for _, tgt, _, _ in method_calls if tgt and tgt not in ("__init__", "__call__")})

        # Collect AST cases
        ast_cases = list({case for _, _, _, case in method_calls if case})

        # Build edge details
        details = {}
        if source_methods:
            details["source_methods"] = sorted(source_methods)
        if target_methods:
            details["target_methods"] = sorted(target_methods)
        if ast_cases:
            details["ast_cases"] = sorted(ast_cases)
        details["call_count"] = len(method_calls)

        simplified_edges.append(
            Edge(
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                linenos=sorted(set(all_linenos)),
                details=details,
            )
        )

    # Update reachability: class is reachable if ANY of its methods are reachable
    class_reachability: dict[str, bool] = {}
    for node in detailed_graph.nodes:
        if node.reachable_from_interface:
            parent_id = node_to_parent[node.id]
            class_reachability[parent_id] = True

    # Apply reachability to simplified nodes
    for node_id, node in simplified_nodes.items():
        if node_id in class_reachability:
            node.reachable_from_interface = True

    return CodeGraph(
        nodes=list(simplified_nodes.values()),
        edges=simplified_edges,
    )


def main() -> int:
    """Main entry point."""
    # Load detailed graph
    detailed_path = SCRIPT_DIR / "outputs" / "code_graph.json"
    if not detailed_path.exists():
        print(f"Error: Detailed graph not found at {detailed_path}", file=sys.stderr)
        print("Run 'python scripts/build_code_graph.py' first", file=sys.stderr)
        return 1

    print("Loading detailed graph...")
    with open(detailed_path, encoding="utf-8") as f:
        data = json.load(f)

    detailed_graph = CodeGraph(
        nodes=[Node(**n) for n in data["nodes"]],
        edges=[Edge(**e) for e in data["edges"]],
    )

    print(f"  {len(detailed_graph.nodes)} nodes")
    print(f"  {len(detailed_graph.edges)} edges")
    print()

    # Simplify
    print("Simplifying graph...")
    simplified_graph = simplify_graph(detailed_graph)

    reachable = sum(1 for n in simplified_graph.nodes if n.reachable_from_interface)

    print(
        f"  {len(simplified_graph.nodes)} nodes (reduced by {len(detailed_graph.nodes) - len(simplified_graph.nodes)})"
    )
    print(f"  {len(simplified_graph.edges)} edges")
    print(f"  {reachable} nodes reachable from interface")
    print()

    # Write simplified graph
    output_path = SCRIPT_DIR / "outputs" / "code_graph_simplified.json"
    print(f"Writing simplified graph to {output_path.relative_to(SCRIPT_DIR)}...")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "nodes": [asdict(n) for n in simplified_graph.nodes],
                "edges": [asdict(e) for e in simplified_graph.edges],
            },
            f,
            indent=2,
        )

    print("✓ Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
