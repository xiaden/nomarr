#!/usr/bin/env python3
"""Check edges in full detailed graph"""

import json
from pathlib import Path

graph_path = Path("scripts/outputs/code_graph.json")
data = json.load(graph_path.open(encoding="utf-8"))

print("Edge types in full graph:")
types = set(e["type"] for e in data["edges"])
for t in sorted(types):
    print(f"  {t}")

target = "nomarr.services.infrastructure.keys_svc.KeyManagementService"

print(f"\n\nEdges TO {target}:")
edges_to = [e for e in data["edges"] if e["target_id"] == target]
for e in edges_to[:20]:
    print(f"  {e['source_id']} -> {e['type']}")

print(f"\n\nEdges FROM {target}:")
edges_from = [e for e in data["edges"] if e["source_id"] == target]
for e in edges_from[:20]:
    print(f"  -> {e['target_id']} ({e['type']})")

print(f"\n\nLooking for admin_cache_refresh:")
edges_from_admin = [
    e for e in data["edges"] if e["source_id"] == "nomarr.interfaces.api.v1.admin_if.admin_cache_refresh"
]
print(f"Edges FROM admin_cache_refresh ({len(edges_from_admin)} total):")
for e in edges_from_admin[:25]:
    print(f"  -> {e['target_id']} ({e['type']})")
