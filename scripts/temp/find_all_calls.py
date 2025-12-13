import ast

with open("nomarr/services/domain/library_svc.py", "r", encoding="utf-8") as f:
    source = f.read()

tree = ast.parse(source)

# Find LibraryService.reconcile_library_paths method
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "LibraryService":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "reconcile_library_paths":
                print(f"Found method at line {item.lineno}")
                print(f"Method has {len(item.body)} statements in body\n")
                
                # Find all Call nodes
                calls = []
                for child in ast.walk(item):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(("Direct", child.func.id, child.lineno))
                        elif isinstance(child.func, ast.Attribute):
                            if isinstance(child.func.value, ast.Name):
                                calls.append(("Attribute", f"{child.func.value.id}.{child.func.attr}", child.lineno))
                
                print(f"All calls in method ({len(calls)} total):")
                for call_type, name, lineno in calls:
                    if "reconcile" in name.lower():
                        print(f"  Line {lineno}: {call_type} call to '{name}' *** RECONCILE ***")
                    else:
                        print(f"  Line {lineno}: {call_type} call to '{name}'")
