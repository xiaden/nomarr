import json

with open("scripts/outputs/code_graph.json", encoding="utf-8") as f:
    data = json.load(f)

service_method = "nomarr.services.domain.library_svc.LibraryService.reconcile_library_paths"
component_func = "nomarr.components.library.reconcile_paths_comp.reconcile_library_paths"

# Find all CALLS edges involving these nodes
edges_from_service = [e for e in data["edges"] if e["source_id"] == service_method and e["type"] == "CALLS"]
edges_to_component = [e for e in data["edges"] if e["target_id"] == component_func and e["type"] == "CALLS"]

print(f"CALLS edges FROM service method {service_method}:")
for e in edges_from_service:
    print(f"  → {e['target_id']}")

print(f"\nCALLS edges TO component function {component_func}:")
for e in edges_to_component:
    print(f"  ← {e['source_id']}")
