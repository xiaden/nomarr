#!/usr/bin/env python3
"""Build code graph for dead code detection.

This script analyzes Python code using AST parsing to build a directed graph
of modules, classes, functions, and their relationships (CONTAINS, IMPORTS, CALLS).
It then computes reachability from interface entrypoints to identify dead code.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts directory to path for tools import
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Import after path setup
# ruff: noqa: E402
from tools.build_code_graph import (
    Edge,
    build_callable_index,
    build_graph_for_file,
    compute_reachability,
    discover_python_files,
    find_interface_entrypoints,
    load_config,
    merge_graphs,
    resolve_paths,
    write_output,
)


def main() -> int:
    """Main entry point."""
    print("Building code graph...")
    print()

    # Load configuration
    print("Loading configuration...")
    config = load_config()
    project_root, search_paths, output_path = resolve_paths(config)

    print(f"  Project root: {project_root}")
    print(f"  Search paths: {', '.join(str(p.relative_to(project_root)) for p in search_paths)}")
    print(f"  Output: {output_path.relative_to(SCRIPT_DIR)}")
    print()

    # Discover Python files
    print("Discovering Python files...")
    python_files = discover_python_files(search_paths)
    print(f"  Found {len(python_files)} Python files")
    print()

    # FIRST PASS: Parse files and build nodes only (no CALLS edges)
    print("First pass: Building nodes...")
    subgraphs = []
    for i, py_file in enumerate(python_files, 1):
        if i % 50 == 0:
            print(f"  Parsed {i}/{len(python_files)} files...")
        subgraph = build_graph_for_file(py_file, project_root, build_calls=False)
        subgraphs.append(subgraph)

    print(f"  Parsed {len(python_files)} files")
    print()

    # Merge subgraphs
    print("Merging subgraphs...")
    graph = merge_graphs(subgraphs)
    print(f"  Total nodes: {len(graph.nodes)}")
    print()

    # Build callable index for cross-module CALLS edge resolution
    print("Building callable index...")
    callable_index = build_callable_index(graph)
    print(f"  Indexed {len(callable_index)} callable names")
    print()

    # SECOND PASS: Re-parse files and build CALLS edges with global knowledge
    print("Second pass: Building CALLS edges...")
    calls_subgraphs = []
    for i, py_file in enumerate(python_files, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(python_files)} files...")
        subgraph = build_graph_for_file(py_file, project_root, build_calls=True, callable_index=callable_index)
        # Only keep the edges (nodes were already added in first pass)
        calls_subgraphs.append(subgraph)

    # Merge CALLS edges into main graph
    for sg in calls_subgraphs:
        graph.edges.extend(sg.edges)

    print(f"  Processed {len(python_files)} files")
    print(f"  Total edges (before deduplication): {len(graph.edges)}")

    # Deduplicate edges and collect line numbers
    print("Deduplicating edges...")
    edges_before = len(graph.edges)
    edge_map: dict[
        tuple[str, str, str], tuple[list[int], list[str], str | None]
    ] = {}  # (source, target, type) -> ([line numbers], [details], ast_case)

    for edge in graph.edges:
        key = (edge.source_id, edge.target_id, edge.type)
        if key not in edge_map:
            edge_map[key] = ([], [], edge.ast_case)

        linenos, details, ast_case = edge_map[key]
        # Collect all line numbers
        linenos.extend(edge.linenos)
        # Collect all details
        details.extend(edge.details)
        # Keep first ast_case (they should all be the same for duplicate edges)
        edge_map[key] = (linenos, details, ast_case)

    # Rebuild edges with deduplicated line numbers and details
    deduplicated_edges = []
    for (source_id, target_id, edge_type), (linenos, details, ast_case) in edge_map.items():
        # Remove duplicates and sort line numbers
        unique_linenos = sorted(set(linenos))
        # Remove duplicate details while preserving order
        seen_details = set()
        unique_details = []
        for d in details:
            if d not in seen_details:
                seen_details.add(d)
                unique_details.append(d)

        deduplicated_edges.append(
            Edge(
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                linenos=unique_linenos,
                details=unique_details,
                ast_case=ast_case,
            )
        )

    graph.edges = deduplicated_edges
    edges_after = len(graph.edges)
    duplicates_removed = edges_before - edges_after
    print(f"  Removed {duplicates_removed} duplicate edges ({edges_before} -> {edges_after})")
    print()

    # Find entrypoints
    print("Finding interface entrypoints...")
    entrypoints = find_interface_entrypoints(graph)
    print(f"  Found {len(entrypoints)} entrypoints")
    print()

    # Compute reachability
    print("Computing reachability from entrypoints...")
    compute_reachability(graph, entrypoints)
    reachable_count = sum(1 for node in graph.nodes if node.reachable_from_interface)
    print(f"  {reachable_count} nodes are reachable from interface entrypoints")
    print()

    # Write output
    print("Writing output...")
    write_output(graph, output_path, project_root, search_paths)
    print()

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
