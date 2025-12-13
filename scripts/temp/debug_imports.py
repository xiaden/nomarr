import ast

# Read the service file
with open("nomarr/services/domain/library_svc.py", encoding="utf-8") as f:
    source = f.read()

tree = ast.parse(source)

# Find the LibraryService class
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "LibraryService":
        # Find the reconcile_library_paths method
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "reconcile_library_paths":
                print("Found method: reconcile_library_paths")
                print("Method body:")

                # Extract imports
                imports = {}
                for child in ast.walk(item):
                    if isinstance(child, ast.ImportFrom) and child.module:
                        for alias in child.names:
                            if alias.name != "*":
                                local_name = alias.asname if alias.asname else alias.name
                                full_path = f"{child.module}.{alias.name}"
                                imports[local_name] = full_path
                                print(f"  Import: {local_name} = {full_path}")

                # Find calls
                for child in ast.walk(item):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            func_name = child.func.id
                            if func_name == "reconcile_library_paths":
                                print(f"\n  Found call to: {func_name}")
                                print(f"  Imported path: {imports.get(func_name, 'NOT IMPORTED')}")
