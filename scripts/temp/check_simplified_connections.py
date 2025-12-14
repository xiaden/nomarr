#!/usr/bin/env python3
"""Check connections in simplified graph"""

import json
from collections import deque
from pathlib import Path

graph_path = Path("scripts/outputs/code_graph_simplified.json")
data = json.load(graph_path.open(encoding="utf-8"))

# Build forward edge map (only reachable types)
forward_edges = {}

REACHABLE_TYPES = {
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

for edge in data["edges"]:
    if edge["type"] in REACHABLE_TYPES:
        src = edge["source_id"]
        tgt = edge["target_id"]

        if src not in forward_edges:
            forward_edges[src] = []
        forward_edges[src].append((tgt, edge["type"]))

# Pick first interface
interfaces = [n for n in data["nodes"] if "interfaces" in n["id"] and "_if." in n["id"]]
if not interfaces:
    print("No interfaces found!")
    exit(1)

interface = interfaces[0]["id"]
print(f"Testing interface: {interface}\n")

# Forward BFS
queue = deque([interface])
visited = set([interface])
reachable = set([interface])

while queue:
    current = queue.popleft()
    for next_node, edge_type in forward_edges.get(current, []):
        if next_node not in visited:
            visited.add(next_node)
            reachable.add(next_node)
            queue.append(next_node)

print(f"Nodes reachable from {interface}: {len(reachable)}")
print("\nFirst 20 reachable nodes:")
for i, node_id in enumerate(sorted(reachable)[:20]):
    print(f"  {node_id}")

# Check if interface itself has outgoing edges
direct_edges = forward_edges.get(interface, [])
print(f"\n\nDirect edges from interface: {len(direct_edges)}")
for target, edge_type in direct_edges[:10]:
    print(f"  -> {target} ({edge_type})")
