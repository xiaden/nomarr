import json

with open("scripts/outputs/code_graph.json", encoding="utf-8") as f:
    data = json.load(f)

# Find all nodes with "reconcile_library_paths"
nodes = {n["id"]: n for n in data["nodes"]}

reconcile_nodes = [nid for nid in nodes if "reconcile_library_paths" in nid]

print("All nodes with 'reconcile_library_paths':")
for nid in reconcile_nodes:
    print(f"  {nid}")

print("\n" + "=" * 80)
print("Testing matching logic:")
print("=" * 80)

imported_path = "nomarr.components.library.reconcile_library_paths"
print(f"\nImported path: {imported_path}")

import_parts = imported_path.rsplit(".", 1)
if len(import_parts) == 2:
    import_package, import_name = import_parts
    print(f"  Package: {import_package}")
    print(f"  Name: {import_name}")

    print("\nChecking candidates:")
    for candidate in reconcile_nodes:
        starts_with = candidate.startswith(import_package + ".")
        ends_with = candidate.endswith("." + import_name)

        print(f"\n  Candidate: {candidate}")
        print(f"    Starts with '{import_package}.'? {starts_with}")
        print(f"    Ends with '.{import_name}'? {ends_with}")
        print(f"    Match? {starts_with and ends_with}")
