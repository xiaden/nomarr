#!/usr/bin/env python3
"""
filter_graph.py

Post-process a code2flow .gv output:
  - Strip nodes whose function name matches any exclusion pattern
  - Group nodes into architectural layer clusters (auto-detected from nomarr/ structure)
  - Render via Graphviz dot at configurable DPI/format

Usage:
    python scripts/tools/filter_graph.py [options]

Examples:
    # Regenerate, strip privates (default), render SVG
    python scripts/tools/filter_graph.py --regen

    # Strip additional patterns, render PNG at 200 DPI
    python scripts/tools/filter_graph.py --exclude "^_" "^test_" --dpi 200 --format png

    # Scope to one directory, top-down layout
    python scripts/tools/filter_graph.py --source ./nomarr/components --regen --rankdir TB
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
NOMARR_ROOT = REPO_ROOT / "nomarr"

LAYERS = ["interfaces", "services", "workflows", "components", "persistence", "helpers"]

LAYER_STYLE: dict[str, dict] = {
    "interfaces": {"color": "#2471A3", "fillcolor": "#D6EAF8", "label": "Interfaces"},
    "services": {"color": "#1E8449", "fillcolor": "#D5F5E3", "label": "Services"},
    "workflows": {"color": "#B9770E", "fillcolor": "#FDEBD0", "label": "Workflows"},
    "components": {"color": "#6C3483", "fillcolor": "#E8DAEF", "label": "Components"},
    "persistence": {"color": "#B7950B", "fillcolor": "#FEF9E7", "label": "Persistence"},
    "helpers": {"color": "#717D7E", "fillcolor": "#EAECEE", "label": "Helpers"},
}

# Exclude private/dunder functions by default
DEFAULT_EXCLUDES: list[str] = [r"^_"]


def build_module_layer_map() -> dict[str, str]:
    """Map Python module stem → layer name by scanning nomarr/."""
    mapping: dict[str, str] = {}
    for layer in LAYERS:
        layer_dir = NOMARR_ROOT / layer
        if layer_dir.exists():
            for py_file in layer_dir.rglob("*.py"):
                mapping[py_file.stem] = layer
    return mapping


def parse_gv(gv_path: Path) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    """
    Return (nodes, edges) from a code2flow .gv file.

    nodes: { node_id -> {attrs, name, module, symbol} }
    edges: [(src_id, dst_id), ...]
    """
    text = gv_path.read_text(encoding="utf-8")

    node_re = re.compile(r"^(node_\w+)\s*\[([^\]]+)\]\s*;", re.MULTILINE)
    nodes: dict[str, dict] = {}
    for m in node_re.finditer(text):
        node_id = m.group(1)
        attrs = m.group(2)
        name_m = re.search(r'name="([^"]+)"', attrs)
        name = name_m.group(1) if name_m else ""
        module, _, symbol = name.partition("::")
        nodes[node_id] = {
            "attrs": attrs,
            "name": name,
            "module": module,
            "symbol": symbol,
        }

    edge_re = re.compile(r"^(node_\w+)\s*->\s*(node_\w+)[^;]*;", re.MULTILINE)
    edges = [(m.group(1), m.group(2)) for m in edge_re.finditer(text)]

    return nodes, edges


def apply_filters(nodes: dict[str, dict], exclude_patterns: list[str]) -> set[str]:
    """Return node IDs to keep (those whose function name matches no exclusion pattern)."""
    compiled = [re.compile(p) for p in exclude_patterns]
    keep: set[str] = set()
    for node_id, info in nodes.items():
        symbol = info["symbol"]
        # e.g. "ClassName.method_name" → "method_name"
        func_name = symbol.split(".")[-1] if "." in symbol else symbol
        if not any(p.search(func_name) for p in compiled):
            keep.add(node_id)
    return keep


def reconnect_edges(
    edges: list[tuple[str, str]],
    keep: set[str],
) -> list[tuple[str, str]]:
    """
    Transitive edge reconnection.

    When a filtered-out node sits between two kept nodes (A→B→C, B excluded),
    stitch A→C directly.  Uses BFS from each excluded node's predecessors to
    find the nearest kept successors, avoiding cycles.
    """
    # Build forward and backward adjacency over ALL nodes
    fwd: dict[str, set[str]] = {}  # node → its direct successors
    bck: dict[str, set[str]] = {}  # node → its direct predecessors
    all_nodes: set[str] = set()
    for src, dst in edges:
        fwd.setdefault(src, set()).add(dst)
        bck.setdefault(dst, set()).add(src)
        all_nodes.update((src, dst))

    excluded = all_nodes - keep

    def kept_successors(start: str, visited: set[str]) -> set[str]:
        """BFS from start through excluded nodes; return first kept nodes reached."""
        result: set[str] = set()
        frontier = {start}
        while frontier:
            nxt: set[str] = set()
            for n in frontier:
                for succ in fwd.get(n, set()):
                    if succ in visited:
                        continue
                    visited.add(succ)
                    if succ in keep:
                        result.add(succ)
                    elif succ in excluded:
                        nxt.add(succ)
            frontier = nxt
        return result

    result_edges: set[tuple[str, str]] = set()

    # Direct kept→kept edges
    for src, dst in edges:
        if src in keep and dst in keep:
            result_edges.add((src, dst))

    # For each kept node, find kept successors through excluded intermediaries
    for node in keep:
        for succ in fwd.get(node, set()):
            if succ in excluded:
                visited = {node, succ}
                for reached in kept_successors(succ, visited):
                    if reached != node:  # no self-loops
                        result_edges.add((node, reached))

    return list(result_edges)


def emit_gv(
    nodes: dict[str, dict],
    edges: list[tuple[str, str]],
    keep: set[str],
    module_layer: dict[str, str],
    out_path: Path,
    rankdir: str = "LR",
) -> None:
    """Write a filtered, layer-clustered .gv file."""
    bucketed: dict[str, list[str]] = {layer: [] for layer in LAYERS}
    bucketed["(other)"] = []

    for node_id in keep:
        layer = module_layer.get(nodes[node_id]["module"])
        bucket = layer or "(other)"
        bucketed[bucket].append(node_id)

    lines = [
        "digraph G {",
        "    concentrate=false;",
        '    splines="ortho";',
        "    nodesep=0.5;",
        "    ranksep=1.2;",
        f'    rankdir="{rankdir}";',
        '    node [shape=rect style="rounded,filled" margin="0.15,0.08"];',
        "    edge [arrowsize=0.7];",
        "",
    ]

    for layer in LAYERS:
        nids = bucketed.get(layer, [])
        if not nids:
            continue
        style = LAYER_STYLE[layer]
        lines += [
            f"    subgraph cluster_{layer} {{",
            f'        label="{style["label"]}";',
            '        style="rounded,filled";',
            f'        color="{style["color"]}";',
            f'        fillcolor="{style["fillcolor"]}";',
            '        fontsize=14; fontname="Helvetica-Bold";',
        ]
        for node_id in nids:
            lines.append(f"        {node_id} [{nodes[node_id]['attrs']}];")
        lines += ["    }", ""]

    for node_id in bucketed["(other)"]:
        lines.append(f"    {node_id} [{nodes[node_id]['attrs']}];")

    lines.append("")

    kept_edges = reconnect_edges(edges, keep)
    for src, dst in kept_edges:
        lines.append(f"    {src} -> {dst};")

    lines.append("}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[filter_graph] wrote {out_path}  ({len(keep)} nodes, {len(kept_edges)} edges)")


def render(gv_path: Path, out_path: Path, fmt: str, dpi: int) -> None:
    cmd = ["dot", f"-T{fmt}", str(gv_path), "-o", str(out_path)]
    if fmt == "png":
        cmd += [f"-Gdpi={dpi}"]
    subprocess.run(cmd, check=True)
    print(f"[filter_graph] rendered → {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Filter and layer a code2flow .gv graph",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--source", default="./nomarr", help="Source path for code2flow (used with --regen)")
    ap.add_argument("--gv", default="out.gv", help="Input .gv file")
    ap.add_argument("--out-gv", default="out_filtered.gv", help="Filtered .gv output path")
    ap.add_argument("--output", "-o", default="out_filtered.svg", help="Rendered output path")
    ap.add_argument("--format", default="svg", choices=["svg", "png", "pdf"], help="Output format")
    ap.add_argument("--dpi", type=int, default=150, help="DPI (PNG only)")
    ap.add_argument(
        "--exclude",
        nargs="*",
        metavar="PATTERN",
        help=f"Regex patterns applied to function names (default: {DEFAULT_EXCLUDES}). "
        "Replaces the default list when supplied.",
    )
    ap.add_argument(
        "--extra-exclude",
        nargs="*",
        metavar="PATTERN",
        help="Additional patterns appended to (not replacing) the default list.",
    )
    ap.add_argument("--regen", action="store_true", help="Re-run code2flow before filtering")
    ap.add_argument("--rankdir", default="LR", choices=["LR", "TB", "RL", "BT"])
    args = ap.parse_args()

    gv_path = Path(args.gv)
    out_gv = Path(args.out_gv)
    out_render = Path(args.output)

    if args.regen:
        print(f"[filter_graph] running code2flow on {args.source} ...")
        subprocess.run(
            ["code2flow", args.source, "-o", str(gv_path), "--skip-parse-errors"],
            check=True,
        )

    if not gv_path.exists():
        print(f"ERROR: {gv_path} not found — run with --regen or generate manually first.", file=sys.stderr)
        sys.exit(1)

    exclude_patterns: list[str] = list(args.exclude) if args.exclude is not None else list(DEFAULT_EXCLUDES)
    if args.extra_exclude:
        exclude_patterns += args.extra_exclude

    print(f"[filter_graph] exclude patterns: {exclude_patterns}")

    module_layer = build_module_layer_map()
    nodes, edges = parse_gv(gv_path)
    print(f"[filter_graph] parsed: {len(nodes)} nodes, {len(edges)} edges")

    keep = apply_filters(nodes, exclude_patterns)
    print(f"[filter_graph] keeping {len(keep)}, excluded {len(nodes) - len(keep)}")

    emit_gv(nodes, edges, keep, module_layer, out_gv, rankdir=args.rankdir)
    render(out_gv, out_render, args.format, args.dpi)


if __name__ == "__main__":
    main()
