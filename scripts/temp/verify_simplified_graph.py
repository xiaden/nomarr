#!/usr/bin/env python3
"""Verify simplified graph structure for viewer"""

import json
from pathlib import Path

graph_path = Path("scripts/outputs/code_graph_simplified.json")
data = json.load(graph_path.open(encoding="utf-8"))

print(f"Total nodes: {len(data['nodes'])}")
print(f"Total edges: {len(data['edges'])}")

# Count edge types
from collections import Counter

edge_types = Counter(e["type"] for e in data["edges"])
print(f"\nEdge types:")
for typ, count in edge_types.most_common():
    print(f"  {typ}: {count}")

# Check if CONTAINS edges exist
contains_edges = [e for e in data["edges"] if e["type"] == "CONTAINS"]
print(f"\n⚠️  CONTAINS edges: {len(contains_edges)}")
if contains_edges[:3]:
    print("Sample CONTAINS edges:")
    for e in contains_edges[:3]:
        print(f"  {e['source_id']} -> {e['target_id']}")

# Find interfaces
interface_nodes = [n for n in data["nodes"] if "interfaces" in n["id"] and "_if." in n["id"]]
print(f"\n\nInterface nodes: {len(interface_nodes)}")

# Check first interface
if interface_nodes:
    iface = interface_nodes[0]
    print(f"\nFirst interface: {iface['id']}")

    # Count outgoing edges
    outgoing = [e for e in data["edges"] if e["source_id"] == iface["id"]]
    print(f"Outgoing edges: {len(outgoing)}")

    if outgoing:
        print("Sample outgoing edges:")
        for e in outgoing[:5]:
            print(f"  -> {e['target_id']} ({e['type']})")
