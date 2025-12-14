"""Verify code graph integrity: all call-based edges must have ast_case.

This script validates that every edge representing a function/method call or
type usage has an ast_case field set. Missing ast_case values indicate a bug
in edge creation logic.

Usage:
    python scripts/verify_graph_integrity.py [--graph PATH]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Verify code graph edge integrity")
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("scripts/outputs/code_graph.json"),
        help="Path to code graph JSON file",
    )
    args = parser.parse_args()

    if not args.graph.exists():
        print(f"❌ Error: Graph file not found: {args.graph}")
        sys.exit(1)

    # Load graph
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    print(f"Loaded graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges\n")

    # All edge types (all should have ast_case now)
    ALL_EDGE_TYPES = {
        "CALLS",
        "CALLS_FUNCTION",
        "CALLS_METHOD",
        "CALLS_CLASS",
        "CALLS_ATTRIBUTE",
        "CALLS_DEPENDENCY",
        "CALLS_THREAD_TARGET",
        "USES_TYPE",
        "CONTAINS",
        "IMPORTS",
    }

    # Categorize edges
    known_edges = []
    unknown_edges = []

    for edge in graph["edges"]:
        edge_type = edge["type"]
        if edge_type in ALL_EDGE_TYPES:
            known_edges.append(edge)
        else:
            unknown_edges.append(edge)

    print(f"Edge type breakdown:")
    print(f"  Known edge types: {len(known_edges)}")
    if unknown_edges:
        print(f"  ⚠️  Unknown edge types: {len(unknown_edges)}")

    # Check for missing ast_case in ALL edges
    missing_ast_case = [e for e in graph["edges"] if not e.get("ast_case")]

    print(f"\nIntegrity check:")
    if missing_ast_case:
        print(f"❌ FAILED: {len(missing_ast_case)} edges missing ast_case\n")

        # Group by edge type
        by_type = defaultdict(list)
        for edge in missing_ast_case:
            by_type[edge["type"]].append(edge)

        print("Breakdown by type:")
        for edge_type, edges in sorted(by_type.items()):
            print(f"\n  {edge_type}: {len(edges)} edges")
            # Show examples
            for edge in edges[:5]:
                print(f"    {edge['source_id']}")
                print(f"      -> {edge['target_id']}")

        sys.exit(1)

    print(f"✓ PASSED: All {len(graph['edges'])} edges have ast_case set!")

    # Show distribution
    by_type = defaultdict(int)
    by_ast_case = defaultdict(int)
    for edge in graph["edges"]:
        by_type[edge["type"]] += 1
        by_ast_case[edge.get("ast_case", "None")] += 1

    print("\nEdge type distribution:")
    for edge_type, count in sorted(by_type.items()):
        print(f"  {edge_type}: {count}")

    print("\nAST case distribution:")
    for ast_case, count in sorted(by_ast_case.items(), key=lambda x: -x[1]):
        print(f"  {ast_case}: {count}")

    # Check for unknown edge types
    if unknown_edges:
        print(f"\n⚠️  Warning: {len(unknown_edges)} edges with unknown types:")
        unknown_types = defaultdict(int)
        for edge in unknown_edges:
            unknown_types[edge["type"]] += 1
        for edge_type, count in sorted(unknown_types.items()):
            print(f"  {edge_type}: {count}")

    print("\n✓ Graph integrity verified!")


if __name__ == "__main__":
    main()
