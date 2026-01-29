"""Trace path from any node to its entrypoint(s).

This script performs reverse BFS from a target node to find all paths
back to interface entrypoints, showing why a node is reachable.

Usage:
    python scripts/trace_to_entrypoint.py <node_id>
    python scripts/trace_to_entrypoint.py --search <pattern>
    python scripts/trace_to_entrypoint.py --unreachable
"""

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path


def load_graph(graph_path: Path) -> dict:
    """Load code graph from JSON."""
    return json.loads(graph_path.read_text(encoding="utf-8"))


def build_reverse_edges(graph: dict) -> dict[str, list[tuple[str, str, str]]]:
    """Build reverse edge map: target -> [(source, edge_type, ast_case), ...]"""
    reverse_edges = defaultdict(list)

    # Only follow edges that contribute to reachability
    REACHABLE_EDGE_TYPES = {
        "CALLS",
        "CALLS_FUNCTION",
        "CALLS_METHOD",
        "CALLS_CLASS",
        "CALLS_ATTRIBUTE",
        "CALLS_DEPENDENCY",
        "CALLS_THREAD_TARGET",
        "USES_TYPE",
        "IMPORTS",
    }

    for edge in graph["edges"]:
        if edge["type"] in REACHABLE_EDGE_TYPES:
            reverse_edges[edge["target_id"]].append((edge["source_id"], edge["type"], edge.get("ast_case", "Unknown")))

    return reverse_edges


def find_entrypoints(graph: dict) -> set[str]:
    """Find all interface entrypoint nodes."""
    entrypoints = set()
    for node in graph["nodes"]:
        node_id = node["id"]
        # API entrypoint
        if node_id == "nomarr.interfaces.api.api_app":
            entrypoints.add(node_id)
        # CLI entrypoints
        if node_id.startswith("nomarr.interfaces.cli.") and (node_id.endswith(".main") or ".cmd_" in node_id):
            entrypoints.add(node_id)
        # Worker entrypoints
        if ".run" in node_id and "Worker" in node_id:
            entrypoints.add(node_id)

    return entrypoints


def trace_to_entrypoints(
    target_id: str, reverse_edges: dict, entrypoints: set[str], max_paths: int = 10, max_depth: int = 50
) -> list[list[tuple[str, str, str]]]:
    """Find paths from target to entrypoints using reverse BFS.

    Returns list of paths, where each path is a list of (node_id, edge_type, ast_case) tuples.
    """
    # BFS from target backwards to entrypoints
    queue = deque([(target_id, [(target_id, None, None)])])
    visited_paths = set()
    found_paths = []

    while queue and len(found_paths) < max_paths:
        current_id, path = queue.popleft()

        # Skip if path too long
        if len(path) > max_depth:
            continue

        # Found an entrypoint!
        if current_id in entrypoints:
            found_paths.append(path)
            continue

        # Explore parents (nodes that call/use this node)
        for source_id, edge_type, ast_case in reverse_edges.get(current_id, []):
            # Avoid cycles
            path_key = (source_id, tuple(n[0] for n in path))
            if path_key in visited_paths:
                continue
            visited_paths.add(path_key)

            # Build new path
            new_path = [(source_id, edge_type, ast_case)] + path
            queue.append((source_id, new_path))

    return found_paths


def format_path(path: list[tuple[str, str, str]], nodes_by_id: dict) -> str:
    """Format a path for display."""
    lines = []
    for i, (node_id, edge_type, ast_case) in enumerate(path):
        node = nodes_by_id.get(node_id)
        if not node:
            lines.append(f"  {'  ' * i}❌ {node_id} (NOT FOUND)")
            continue

        # Node info
        kind_icon = {"module": "📦", "class": "🏛️", "function": "⚙️", "method": "🔧"}.get(node["kind"], "❓")
        layer = node.get("layer", "unknown")

        if i == 0:
            # Entrypoint
            lines.append(f"  🎯 {node_id}")
            lines.append(f"      [{kind_icon} {node['kind']} | {layer}]")
        else:
            # Intermediate node with edge info
            prev_edge_type = path[i - 1][1]
            prev_ast_case = path[i - 1][2]

            edge_icon = {
                "CALLS_FUNCTION": "📞",
                "CALLS_METHOD": "📞",
                "CALLS_CLASS": "🏗️",
                "CALLS_DEPENDENCY": "💉",
                "CALLS_ATTRIBUTE": "🔗",
                "CALLS_THREAD_TARGET": "🧵",
                "USES_TYPE": "📝",
                "IMPORTS": "📥",
                "CALLS": "📞",
            }.get(prev_edge_type, "➡️")

            lines.append(f"  {'  ' * i}{edge_icon} via {prev_edge_type} ({prev_ast_case})")
            lines.append(f"  {'  ' * i}↓")
            lines.append(f"  {'  ' * i}{node_id}")
            lines.append(f"  {'  ' * i}  [{kind_icon} {node['kind']} | {layer}]")

    return "\n".join(lines)


def search_nodes(graph: dict, pattern: str) -> list[dict]:
    """Search for nodes matching pattern."""
    pattern_lower = pattern.lower()
    matches = []
    for node in graph["nodes"]:
        if pattern_lower in node["id"].lower() or pattern_lower in node.get("name", "").lower():
            matches.append(node)
    return matches


def main():
    parser = argparse.ArgumentParser(description="Trace paths from nodes to entrypoints")
    parser.add_argument("node_id", nargs="?", help="Node ID to trace")
    parser.add_argument("--search", "-s", help="Search for nodes matching pattern")
    parser.add_argument("--unreachable", "-u", action="store_true", help="Show unreachable nodes")
    parser.add_argument("--max-paths", type=int, default=5, help="Maximum paths to show (default: 5)")
    parser.add_argument("--graph", type=Path, default=Path("scripts/outputs/code_graph.json"))
    args = parser.parse_args()

    # Load graph
    print(f"Loading graph from {args.graph}...")
    graph = load_graph(args.graph)
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    print(f"  {len(graph['nodes'])} nodes, {len(graph['edges'])} edges\n")

    # Build reverse edges
    reverse_edges = build_reverse_edges(graph)
    entrypoints = find_entrypoints(graph)

    print(f"Found {len(entrypoints)} entrypoints:")
    for ep in sorted(entrypoints):
        print(f"  🎯 {ep}")
    print()

    # Search mode
    if args.search:
        matches = search_nodes(graph, args.search)
        if not matches:
            print(f"❌ No nodes found matching '{args.search}'")
            sys.exit(1)

        print(f"Found {len(matches)} nodes matching '{args.search}':\n")
        for i, node in enumerate(matches[:20], 1):
            reachable = "✅" if node.get("reachable_from_interface") else "❌"
            print(f"  {i}. {reachable} {node['id']}")
            print(f"      [{node['kind']} | {node.get('layer', 'unknown')}]")

        if len(matches) > 20:
            print(f"\n  ... and {len(matches) - 20} more")

        sys.exit(0)

    # Unreachable mode
    if args.unreachable:
        unreachable = [n for n in graph["nodes"] if not n.get("reachable_from_interface")]
        print(f"Found {len(unreachable)} unreachable nodes:\n")

        by_layer = defaultdict(list)
        for node in unreachable:
            by_layer[node.get("layer", "unknown")].append(node)

        for layer in sorted(by_layer.keys()):
            nodes = by_layer[layer]
            print(f"\n{layer}: {len(nodes)} nodes")
            for node in sorted(nodes, key=lambda n: n["id"])[:10]:
                print(f"  ❌ {node['id']}")
                print(f"      [{node['kind']}]")
            if len(nodes) > 10:
                print(f"  ... and {len(nodes) - 10} more")

        sys.exit(0)

    # Trace mode
    if not args.node_id:
        print("❌ Error: Must provide node_id or use --search/--unreachable")
        parser.print_help()
        sys.exit(1)

    target_id = args.node_id

    # Check if node exists
    if target_id not in nodes_by_id:
        print(f"❌ Node not found: {target_id}")
        print(f"\nTry searching: python scripts/trace_to_entrypoint.py --search {target_id.split('.')[-1]}")
        sys.exit(1)

    target_node = nodes_by_id[target_id]
    print(f"Tracing: {target_id}")
    print(f"  Kind: {target_node['kind']}")
    print(f"  Layer: {target_node.get('layer', 'unknown')}")
    print(f"  Reachable: {'✅ Yes' if target_node.get('reachable_from_interface') else '❌ No'}")
    print()

    # Find paths
    paths = trace_to_entrypoints(target_id, reverse_edges, entrypoints, max_paths=args.max_paths)

    if not paths:
        print(f"❌ No paths found from {target_id} to any entrypoint")
        print("\nThis node is unreachable from interfaces.")

        # Show what calls this node
        callers = reverse_edges.get(target_id, [])
        if callers:
            print(f"\nNodes that reference this node ({len(callers)}):")
            for source_id, edge_type, ast_case in callers[:10]:
                reachable = "✅" if nodes_by_id.get(source_id, {}).get("reachable_from_interface") else "❌"
                print(f"  {reachable} {source_id}")
                print(f"      via {edge_type} ({ast_case})")
        else:
            print("\n⚠️  No nodes reference this node - it may be dead code!")
    else:
        print(f"Found {len(paths)} path(s) to entrypoints:\n")
        for i, path in enumerate(paths, 1):
            print(f"{'=' * 80}")
            print(f"Path {i} ({len(path)} hops):")
            print(f"{'=' * 80}")
            print(format_path(path, nodes_by_id))
            print()


if __name__ == "__main__":
    main()
