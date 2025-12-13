import json

with open("scripts/outputs/code_graph.json", encoding="utf-8") as f:
    data = json.load(f)

# Find all nodes with "reconcile_library_paths" in the id
nodes_with_name = [n for n in data["nodes"] if "reconcile_library_paths" in n["id"]]

print(f"Found {len(nodes_with_name)} nodes with 'reconcile_library_paths':")
for node in nodes_with_name:
    print(f"  {node['id']}")
    print(f"    kind: {node['kind']}, layer: {node['layer']}")
