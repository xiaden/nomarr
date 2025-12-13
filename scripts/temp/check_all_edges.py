import json

with open("scripts/outputs/code_graph.json", encoding="utf-8") as f:
    data = json.load(f)

service_method = "nomarr.services.domain.library_svc.LibraryService.reconcile_library_paths"

# Find all edges FROM this service method
edges = [e for e in data["edges"] if e["source_id"] == service_method]

print(f"All edges FROM {service_method}:")
print(f"Total: {len(edges)}\n")

# Group by type
by_type = {}
for e in edges:
    etype = e["type"]
    if etype not in by_type:
        by_type[etype] = []
    by_type[etype].append(e)

for etype, edge_list in sorted(by_type.items()):
    print(f"{etype} edges ({len(edge_list)}):")
    for e in edge_list:
        print(f"  Line {e.get('lineno', '?')}: → {e['target_id']}")
