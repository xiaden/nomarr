#!/usr/bin/env python3
import json

data = json.load(open("scripts/outputs/code_graph.json", encoding="utf-8"))
node = [n for n in data["nodes"] if n["id"] == "nomarr.persistence.database.meta_sql.MetaOperations.delete"][0]
print(f"Node: {node['id']}")
print(f"Layer: {node['layer']}")
print(f"Kind: {node['kind']}")
print(f"Reachable: {node.get('reachable_from_interface', False)}")
