#!/usr/bin/env python3
"""Check path from logout to MetaOperations.delete"""

import json
from collections import deque
from pathlib import Path

graph_path = Path("scripts/outputs/code_graph.json")
data = json.load(graph_path.open(encoding="utf-8"))

# Build edge maps
forward_edges = {}  # source -> [(target, type)]
reverse_edges = {}  # target -> [(source, type)]

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
        src, tgt, typ = edge["source_id"], edge["target_id"], edge["type"]

        if src not in forward_edges:
            forward_edges[src] = []
        forward_edges[src].append((tgt, typ))

        if tgt not in reverse_edges:
            reverse_edges[tgt] = []
        reverse_edges[tgt].append((src, typ))

# Forward BFS from logout
interface = "nomarr.interfaces.api.web.auth_if.logout"
target = "nomarr.persistence.database.meta_sql.MetaOperations.delete"

print(f"Forward BFS from {interface}:")
queue = deque([interface])
visited = set([interface])
forward_reachable = set([interface])

while queue:
    current = queue.popleft()
    for next_node, edge_type in forward_edges.get(current, []):
        if next_node not in visited:
            visited.add(next_node)
            forward_reachable.add(next_node)
            queue.append(next_node)
            if target in next_node or "MetaOperations" in next_node:
                print(f"  Found: {current} -> {next_node} ({edge_type})")

if target in forward_reachable:
    print(f"\n✅ {target} IS reachable via forward BFS")
else:
    print(f"\n❌ {target} NOT reachable via forward BFS")

# Reverse BFS from target
print(f"\n\nReverse BFS from {target} to {interface}:")
queue = deque([target])
visited = set([target])
found_path = False

while queue and not found_path:
    current = queue.popleft()
    if current == interface:
        print(f"✅ Found interface!")
        found_path = True
        break

    for prev_node, edge_type in reverse_edges.get(current, []):
        if prev_node not in visited:
            visited.add(prev_node)
            queue.append(prev_node)
            if "logout" in prev_node.lower() or prev_node == interface:
                print(f"  {prev_node} -> {current} ({edge_type})")

if found_path:
    print(f"\n✅ Path exists from {target} to {interface}")
else:
    print(f"\n❌ No path found from {target} to {interface}")
    print(f"   (Visited {len(visited)} nodes)")
