import ast

code = '''
def example():
    """
    Docstring with code: result = library_service.reconcile_library_paths()
    """
    from nomarr.components.library import reconcile_library_paths
    result = reconcile_library_paths()
'''

tree = ast.parse(code)
func = tree.body[0]

print("Function:", func.name)
print("\nDocstring (via ast.get_docstring):")
print(ast.get_docstring(func))

print("\nBody nodes:")
for i, node in enumerate(func.body):
    print(f"  {i}: {type(node).__name__}", end="")
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        print(f" (string: {node.value.value[:50]!r}...)")
    elif isinstance(node, ast.ImportFrom):
        print(f" (from {node.module} import ...)")
    elif isinstance(node, ast.Assign):
        print(" (assign)")
    else:
        print()

print("\nAll calls via ast.walk:")
for node in ast.walk(func):
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            print(f"  Direct call: {node.func.id}")
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                print(f"  Attribute call: {node.func.value.id}.{node.func.attr}")
