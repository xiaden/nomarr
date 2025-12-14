#!/usr/bin/env python3
"""Check edges in simplified graph"""

import json
from pathlib import Path

graph_path = Path("scripts/outputs/code_graph_simplified.json")
data = json.load(graph_path.open())

target = "nomarr.services.infrastructure.keys_svc.KeyManagementService"

print(f"\nEdges TO {target}:")
edges_to = [e for e in data["edges"] if e["target_id"] == target]
for e in edges_to[:15]:
    print(f"  {e['source_id']} -> {e['type']}")

print(f"\nEdges FROM {target}:")
edges_from = [e for e in data["edges"] if e["source_id"] == target]
for e in edges_from[:15]:
    print(f"  -> {e['target_id']} ({e['type']})")

# Check if create_session exists
print(f"\n\nLooking for create_session method:")
method_id = f"{target}.create_session"
nodes = [n for n in data["nodes"] if n["id"] == method_id]
if nodes:
    print(f"  Found node: {nodes[0]}")
else:
    print(f"  NOT FOUND - methods are aggregated into parent class")

# Check edges from admin_cache_refresh
print(f"\n\nEdges FROM nomarr.interfaces.api.v1.admin_if.admin_cache_refresh:")
admin_edges = [e for e in data["edges"] if e["source_id"] == "nomarr.interfaces.api.v1.admin_if.admin_cache_refresh"]
for e in admin_edges[:15]:
    details = e.get("details", {})
    print(f"  -> {e['target_id']} ({e['type']})")
    if "source_methods" in details:
        print(f"     source_methods: {details['source_methods']}")
    if "target_methods" in details:
        print(f"     target_methods: {details['target_methods']}")
