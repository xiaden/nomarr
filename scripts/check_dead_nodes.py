"""
Analyze potentially dead code using the code graph.

This script identifies unreachable nodes (functions, methods, classes) that are
not reachable from interface entrypoints and analyzes whether they're truly dead
by checking imports, calls, type usage, and raw grep hits.

Usage:
    python check_dead_nodes.py                      # Show summary and likely dead nodes
    python check_dead_nodes.py --verbose            # List all unreachable nodes
    python check_dead_nodes.py -v                   # Short form
    python check_dead_nodes.py --format=json        # JSON output (all analyses)
    python check_dead_nodes.py --format=json -v     # JSON output (verbose doesn't change JSON)
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

# Cache for AST parsing results per file
_ast_cache: dict[str, tuple[ast.AST | None, set[tuple[int, int]]]] = {}


def get_docstring_ranges(file_path: Path) -> set[tuple[int, int]]:
    """
    Get line ranges for all docstrings in a Python file.

    Returns a set of (start_line, end_line) tuples for module, class, and function docstrings.
    Uses cached results if available.
    """
    file_str = str(file_path)

    if file_str in _ast_cache:
        _, cached_ranges = _ast_cache[file_str]
        return cached_ranges

    docstring_ranges: set[tuple[int, int]] = set()

    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=str(file_path))

        # Check module docstring
        if (
            isinstance(tree, ast.Module)
            and tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            node = tree.body[0]
            if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                docstring_ranges.add((node.lineno, node.end_lineno or node.lineno))

        # Walk the AST for class and function docstrings
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and (
                ast_node.body
                and isinstance(ast_node.body[0], ast.Expr)
                and isinstance(ast_node.body[0].value, ast.Constant)
                and isinstance(ast_node.body[0].value.value, str)
            ):
                docstring_node = ast_node.body[0]
                if hasattr(docstring_node, "lineno") and hasattr(docstring_node, "end_lineno"):
                    docstring_ranges.add((docstring_node.lineno, docstring_node.end_lineno or docstring_node.lineno))

        _ast_cache[file_str] = (tree, docstring_ranges)
        return docstring_ranges

    except (SyntaxError, UnicodeDecodeError, OSError):
        # Cache failure result
        _ast_cache[file_str] = (None, set())
        return set()


def classify_grep_hit(hit: dict[str, Any], project_root: Path) -> str:
    """
    Classify a grep hit as: code, comment, docstring, non_code, or unknown.

    Args:
        hit: Dict with 'file', 'lineno', 'line' keys
        project_root: Project root path

    Returns:
        Classification string: "code", "comment", "docstring", "non_code", "unknown"
    """
    file_path = hit["file"]
    lineno = hit["lineno"]
    line_content = hit["line"]

    # Check file extension first
    if not file_path.endswith(".py"):
        return "non_code"

    # For Python files, check if it's a comment
    stripped = line_content.strip()
    if stripped.startswith("#"):
        return "comment"

    # Check if it's in a docstring
    full_path = project_root / file_path
    if full_path.exists():
        docstring_ranges = get_docstring_ranges(full_path)
        if docstring_ranges:
            for start, end in docstring_ranges:
                if start <= lineno <= end:
                    return "docstring"
            # Not in docstring and not a comment, must be code
            return "code"
        else:
            # AST parse failed, but we can still detect comments
            return "unknown"

    return "unknown"


def analyze_dead_node(
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    """
    Analyze a single potentially dead node.

    Args:
        node: Node from code graph
        edges: All edges from code graph
        nodes_by_id: Mapping of node IDs to node dicts
        project_root: Project root path for grep search

    Returns:
        Analysis dict with metadata, edge counts, detailed usages, grep hits, and dead assessment
    """
    node_id = node["id"]
    node_name = node["name"]
    node_file = node["file"]

    # Count edges by type and collect detailed samples
    imports = [e for e in edges if e["target_id"] == node_id and e["type"] == "IMPORTS"]
    calls = [e for e in edges if e["target_id"] == node_id and e["type"] == "CALLS"]
    uses_type = [e for e in edges if e["target_id"] == node_id and e["type"] == "USES_TYPE"]
    inherits = [e for e in edges if e["target_id"] == node_id and e["type"] == "INHERITS"]
    creates_instance = [e for e in edges if e["target_id"] == node_id and e["type"] == "CREATES_INSTANCE"]

    # Collect detailed usage samples (up to 5 each)
    def make_usage_list(edge_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        usages = []
        for e in edge_list[:5]:
            source_id = e.get("source_id", "")
            source_node = nodes_by_id.get(source_id, {})
            usages.append(
                {
                    "source_id": source_id,
                    "file": source_node.get("file", ""),
                    "lineno": e.get("lineno", 0),
                }
            )
        return usages

    import_usages = make_usage_list(imports)
    call_usages = make_usage_list(calls)
    type_usages = make_usage_list(uses_type)
    inherit_usages = make_usage_list(inherits)
    instance_usages = make_usage_list(creates_instance)

    # Raw grep search through codebase with line numbers
    grep_hits: list[dict[str, Any]] = []
    grep_failed = False

    # Normalize node file path for comparison
    node_file_resolved = (project_root / node_file).resolve()

    try:
        # Use git grep with line numbers for detailed hits
        result = subprocess.run(
            ["git", "grep", "-n", node_name],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # Replace invalid characters
            timeout=5,
        )
        if result.returncode == 0 and result.stdout and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            for line in lines[:5]:  # Take first 5 hits
                # Format: file:lineno:line_content
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    file_path = parts[0]
                    # Normalize and resolve file path for comparison
                    file_path_resolved = (project_root / file_path).resolve()
                    # Filter out hits in the defining file
                    if file_path_resolved != node_file_resolved:
                        hit = {
                            "file": file_path,
                            "lineno": int(parts[1]) if parts[1].isdigit() else 0,
                            "line": parts[2],
                        }
                        # Classify the grep hit
                        hit["classification"] = classify_grep_hit(hit, project_root)
                        grep_hits.append(hit)
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        grep_failed = True

    # Classify grep hits by type
    code_hits = [h for h in grep_hits if h.get("classification") == "code"]
    comment_hits = [h for h in grep_hits if h.get("classification") == "comment"]
    docstring_hits = [h for h in grep_hits if h.get("classification") == "docstring"]
    non_code_hits = [h for h in grep_hits if h.get("classification") == "non_code"]
    unknown_hits = [h for h in grep_hits if h.get("classification") == "unknown"]

    # Compute suspicion signals and score
    has_usage_edges = bool(calls or uses_type or inherits or creates_instance)
    has_code_grep_hits = bool(code_hits or unknown_hits)  # Unknown could be code

    signals: list[str] = []
    suspicion_score = 0

    if not has_usage_edges:
        signals.append("no_usage_edges")
        suspicion_score += 3

    if not code_hits and not unknown_hits:
        signals.append("no_code_grep_hits")
        suspicion_score += 2

    if grep_hits and not code_hits and not unknown_hits:
        if comment_hits or docstring_hits:
            signals.append("only_docstring_or_comment_hits")
            suspicion_score += 2
        if non_code_hits and not (comment_hits or docstring_hits):
            signals.append("only_non_python_file_hits")
            suspicion_score += 1

    # Determine if likely dead
    # Node is likely dead if it has no usage edges AND no code grep hits
    likely_dead = not has_usage_edges and not has_code_grep_hits

    # Generate human-readable reason
    if likely_dead:
        parts = []
        if not has_usage_edges:
            parts.append("no usage edges")
        if not code_hits:
            parts.append("no code grep hits")
        if comment_hits or docstring_hits:
            parts.append("only in comments/docs")
        if non_code_hits and not (comment_hits or docstring_hits):
            parts.append("only in non-Python files")
        reason = "; ".join(parts) if parts else "likely dead"
    else:
        if has_usage_edges:
            reason = "has usage edges in graph"
        elif code_hits or unknown_hits:
            reason = f"has {len(code_hits) + len(unknown_hits)} potential code references"
        else:
            reason = "unclear"

    return {
        "node": node,
        "edges": {
            "imports": len(imports),
            "calls": len(calls),
            "uses_type": len(uses_type),
            "inherits": len(inherits),
            "creates_instance": len(creates_instance),
        },
        "import_usages": import_usages,
        "call_usages": call_usages,
        "type_usages": type_usages,
        "inherit_usages": inherit_usages,
        "instance_usages": instance_usages,
        "grep_hits": grep_hits,
        "grep_failed": grep_failed,
        "suspicion_score": suspicion_score,
        "signals": signals,
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
    - The check_dead_nodes.py script itself
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

    # Skip this script itself
    if "check_dead_nodes.py" in file_path:
        return False

    # Skip private names
    return not name.startswith("_")


def print_analysis(analysis: dict[str, Any]) -> None:
    """
    Print detailed analysis for a single node.

    Args:
        analysis: Analysis dict from analyze_dead_node
    """
    node = analysis["node"]
    edges_info = analysis["edges"]

    # Header: node ID and location
    print(f"{node['id']}")
    print(f"  File: {node['file']}:{node.get('lineno', '?')}")
    print(f"  Kind: {node['kind']:<10} Layer: {node.get('layer', 'unknown')}")
    print()

    # Docstring summary (first line)
    docstring = node.get("docstring", "")
    if docstring:
        first_line = docstring.split("\n")[0].strip()
        if first_line:
            print(f"  Doc: {first_line}")
            print()

    # Edge counts
    print(f"  Imports: {edges_info['imports']}")
    print(f"  Calls: {edges_info['calls']}")
    print(f"  Type uses: {edges_info['uses_type']}")
    print(f"  Inherits: {edges_info['inherits']}")
    print(f"  Creates instance: {edges_info['creates_instance']}")
    print()

    # Detailed usage locations
    if analysis["import_usages"]:
        print("  Import locations:")
        for usage in analysis["import_usages"]:
            file_path = usage["file"]
            lineno = usage["lineno"]
            if lineno > 0:
                print(f"    {file_path}:{lineno}")
            else:
                print(f"    {file_path}")
        print()

    if analysis["call_usages"]:
        print("  Call locations:")
        for usage in analysis["call_usages"]:
            file_path = usage["file"]
            lineno = usage["lineno"]
            if lineno > 0:
                print(f"    {file_path}:{lineno}")
            else:
                print(f"    {file_path}")
        print()

    if analysis["type_usages"]:
        print("  Type usage locations:")
        for usage in analysis["type_usages"]:
            file_path = usage["file"]
            lineno = usage["lineno"]
            if lineno > 0:
                print(f"    {file_path}:{lineno}")
            else:
                print(f"    {file_path}")
        print()

    if analysis["inherit_usages"]:
        print("  Inherit locations:")
        for usage in analysis["inherit_usages"]:
            file_path = usage["file"]
            lineno = usage["lineno"]
            if lineno > 0:
                print(f"    {file_path}:{lineno}")
            else:
                print(f"    {file_path}")
        print()

    if analysis["instance_usages"]:
        print("  Instance creation locations:")
        for usage in analysis["instance_usages"]:
            file_path = usage["file"]
            lineno = usage["lineno"]
            if lineno > 0:
                print(f"    {file_path}:{lineno}")
            else:
                print(f"    {file_path}")
        print()

    # Grep hits
    if analysis["grep_failed"]:
        print("  Raw grep: (failed)")
        print()
    elif analysis["grep_hits"]:
        print(f"  Grep hits ({len(analysis['grep_hits'])} shown):")
        for hit in analysis["grep_hits"]:
            line_content = hit["line"].strip()
            classification = hit.get("classification", "unknown")
            if len(line_content) > 70:
                line_content = line_content[:67] + "..."
            # Handle potential encoding issues in grep output
            try:
                print(f"    [{classification}] {hit['file']}:{hit['lineno']}: {line_content}")
            except UnicodeEncodeError:
                # Fallback: encode with replace for characters that can't be printed
                safe_content = line_content.encode("ascii", errors="replace").decode("ascii")
                print(f"    [{classification}] {hit['file']}:{hit['lineno']}: {safe_content}")
        print()

    # Suspicion analysis
    suspicion_score = analysis.get("suspicion_score", 0)
    signals = analysis.get("signals", [])
    if suspicion_score > 0 or signals:
        print(f"  Suspicion score: {suspicion_score}")
        if signals:
            print(f"  Signals: {', '.join(signals)}")
        print()

    # Likely dead indicator
    if analysis["likely_dead"]:
        print(f"  ⚠️  LIKELY DEAD - {analysis['reason']}")
        print()


def main() -> int:
    """Main entry point."""
    # Set UTF-8 output for Windows
    import sys

    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except OSError:
            pass  # some Windows terminals reject reconfigure even when present

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Analyze potentially dead code using the code graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="List all unreachable nodes (not just likely dead)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    args = parser.parse_args()

    # Load graph
    script_dir = Path(__file__).parent
    graph_path = script_dir / "outputs" / "code_graph.json"
    project_root = script_dir.parent

    if args.format == "text":
        print(f"Loading code graph from: {graph_path}")
    with open(graph_path, encoding="utf-8") as f:
        data = json.load(f)

    nodes = data["nodes"]
    edges = data["edges"]

    if args.format == "text":
        print(f"Total nodes: {len(nodes)}")
        print(f"Total edges: {len(edges)}")
        print()

    # Build nodes_by_id mapping
    nodes_by_id = {n["id"]: n for n in nodes}

    # Find unreachable nodes that should be analyzed
    candidates = [n for n in nodes if not n.get("reachable_from_interface") and should_analyze_node(n)]

    if args.format == "text":
        print(f"Unreachable nodes (after filtering): {len(candidates)}")
        print()

    # Analyze all candidates
    if args.format == "text":
        print("Analyzing unreachable nodes...")
    analyses = []
    for node in candidates:
        analysis = analyze_dead_node(node, edges, nodes_by_id, project_root)
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

    # JSON output mode
    if args.format == "json":
        output = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "unreachable_count": len(candidates),
            "likely_dead_count": dead_count,
            "summary_by_layer_kind": [
                {
                    "layer": layer,
                    "kind": kind,
                    "total": len(items),
                    "likely_dead": sum(1 for item in items if item["likely_dead"]),
                }
                for (layer, kind), items in sorted(by_layer_kind.items(), key=lambda x: (x[0][0], x[0][1]))
            ],
            "analyses": analyses,
        }

        # Write to outputs directory
        output_path = script_dir / "outputs" / "dead_nodes_analysis.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"✓ Analysis written to: {output_path}")
        return 0

    # Text output mode
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

    # Most Suspicious Files section
    if dead_count > 0:
        print("=" * 80)
        print("MOST SUSPICIOUS FILES")
        print("=" * 80)
        print()

        # Group by file
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for analysis in analyses:
            file_path = analysis["node"]["file"]
            by_file[file_path].append(analysis)

        # Compute suspicion metrics per file
        file_stats = []
        for file_path, file_analyses in by_file.items():
            total = len(file_analyses)
            likely_dead = sum(1 for a in file_analyses if a["likely_dead"])
            if likely_dead > 0:
                suspicion_ratio = likely_dead / total
                file_stats.append((file_path, total, likely_dead, suspicion_ratio))

        # Sort by likely_dead count desc, then suspicion_ratio desc, then filepath
        file_stats.sort(key=lambda x: (-x[2], -x[3], x[0]))

        for file_path, total, likely_dead, suspicion_ratio in file_stats:
            print(f"{file_path}")
            print(f"  Unreachable: {total}  Likely dead: {likely_dead}  Ratio: {suspicion_ratio:.0%}")
            print()

        # Print concise details for each likely dead node
        likely_dead_analyses = [a for a in analyses if a["likely_dead"]]
        likely_dead_analyses.sort(key=lambda a: (a["node"]["file"], a["node"].get("lineno", 0)))

        print("=" * 80)
        print("LIKELY DEAD NODES (CONCISE)")
        print("=" * 80)
        print()

        for analysis in likely_dead_analyses:
            node = analysis["node"]
            layer = node.get("layer", "unknown")
            kind = node["kind"]
            name = node["name"]
            file_path = node["file"]
            lineno = node.get("lineno", "?")
            suspicion = analysis.get("suspicion_score", 0)
            reason = analysis.get("reason", "")
            print(f"{layer:12} {kind:10} {name:50} @ {file_path}:{lineno}")
            print(f"             suspicion={suspicion} — {reason}")
            print()

    # Verbose mode: list all unreachable nodes with full details
    if args.verbose:
        print("=" * 80)
        print("ALL UNREACHABLE NODES - DETAILED ANALYSIS")
        print("=" * 80)
        print()

        # Sort by layer, kind, file, lineno for stable output
        sorted_analyses = sorted(
            analyses,
            key=lambda a: (
                a["node"].get("layer", "unknown"),
                a["node"]["kind"],
                a["node"]["file"],
                a["node"].get("lineno", 0),
            ),
        )

        for analysis in sorted_analyses:
            print_analysis(analysis)

        print(f"Total unreachable nodes listed: {len(sorted_analyses)}")
        print()
        return 0

    # Non-verbose mode: print detailed analysis for likely dead nodes only
    likely_dead_analyses = [a for a in analyses if a["likely_dead"]]

    if likely_dead_analyses:
        print("=" * 80)
        print("DETAILED ANALYSIS - LIKELY DEAD NODES")
        print("=" * 80)
        print()

        # Sort by file + lineno for stable output
        likely_dead_analyses.sort(key=lambda a: (a["node"]["file"], a["node"].get("lineno", 0)))

        for analysis in likely_dead_analyses:
            print_analysis(analysis)
    else:
        print("✓ No likely dead nodes found!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
