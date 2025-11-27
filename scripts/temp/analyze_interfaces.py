"""Analyze what's unreachable in interfaces layer."""

import json
from collections import defaultdict
from pathlib import Path

# Load graph
graph_path = Path(__file__).parent.parent / "outputs" / "code_graph.json"
with open(graph_path, encoding="utf-8") as f:
    data = json.load(f)

# Filter to interfaces layer
interfaces_nodes = [n for n in data["nodes"] if n["layer"] == "interfaces"]
reachable = [n for n in interfaces_nodes if n.get("reachable_from_interface")]
unreachable = [n for n in interfaces_nodes if not n.get("reachable_from_interface")]

print("Interfaces Layer Analysis")
print("=" * 60)
print(f"Total nodes: {len(interfaces_nodes)}")
print(f"Reachable: {len(reachable)} ({len(reachable) / len(interfaces_nodes) * 100:.1f}%)")
print(f"Unreachable: {len(unreachable)} ({len(unreachable) / len(interfaces_nodes) * 100:.1f}%)")
print()

# Break down by kind
by_kind = defaultdict(lambda: {"total": 0, "reachable": 0, "unreachable": 0})
for node in interfaces_nodes:
    kind = node["kind"]
    by_kind[kind]["total"] += 1
    if node.get("reachable_from_interface"):
        by_kind[kind]["reachable"] += 1
    else:
        by_kind[kind]["unreachable"] += 1

print("Breakdown by Kind:")
print(f"{'Kind':<12} {'Total':<8} {'Reachable':<10} {'Unreachable':<12} {'% Reach':<8}")
print("-" * 60)
for kind in sorted(by_kind.keys()):
    stats = by_kind[kind]
    pct = (stats["reachable"] / stats["total"] * 100) if stats["total"] > 0 else 0
    print(f"{kind:<12} {stats['total']:<8} {stats['reachable']:<10} {stats['unreachable']:<12} {pct:>6.1f}%")

print()
print("=" * 60)

# Show unreachable callables (functions/methods)
unreachable_callables = [n for n in unreachable if n["kind"] in {"function", "method"}]
if unreachable_callables:
    print(f"\nUnreachable Callables ({len(unreachable_callables)} total):")
    print("-" * 60)
    for node in unreachable_callables[:20]:
        print(f"  {node['id']}")
        print(f"    File: {node['file']}:{node['lineno']}")
        print()
else:
    print("\n✓ All interface functions/methods are reachable!")

# Show unreachable classes
unreachable_classes = [n for n in unreachable if n["kind"] == "class"]
if unreachable_classes:
    print(f"\nUnreachable Classes ({len(unreachable_classes)} total):")
    print("-" * 60)

    # Check if these are Pydantic models or other types
    for node in unreachable_classes[:10]:
        print(f"  {node['id']}")
        print(f"    File: {node['file']}:{node['lineno']}")

        # Check edges to see if class is imported/used
        edges = data["edges"]
        imports = [e for e in edges if e["target_id"] == node["id"] and e["type"] == "IMPORTS"]
        calls = [e for e in edges if e["target_id"] == node["id"] and e["type"] == "CALLS"]

        if imports:
            print(f"    Imported by: {len(imports)} modules")
        if calls:
            print(f"    Called by: {len(calls)} callers")

        print()
