import json

with open("scripts/outputs/code_graph.json", encoding="utf-8") as f:
    data = json.load(f)
self_refs = [e for e in data["edges"] if e["source_id"] == e["target_id"] and e["type"] == "CALLS"]
print(f"Self-referencing CALLS edges: {len(self_refs)}")
for e in self_refs[:20]:
    print(f"  - {e['source_id']}")
