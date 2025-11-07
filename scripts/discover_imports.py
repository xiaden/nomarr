#!/usr/bin/env python3
"""
Quick import discovery tool for test writing.
Shows what a module imports and uses, so you know what to mock.
"""

import ast
import sys
from pathlib import Path


def discover_imports(file_path: str) -> dict:
    """Parse a Python file and extract import information."""
    with open(file_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)

    imports = {
        "from_imports": [],  # from X import Y
        "direct_imports": [],  # import X
        "function_calls": set(),  # Functions called in the code
        "class_instantiations": set(),  # Classes instantiated
    }

    # Extract imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports["from_imports"].append({"module": module, "name": alias.name, "alias": alias.asname})

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports["direct_imports"].append({"name": alias.name, "alias": alias.asname})

        # Find function calls (what gets called)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                imports["function_calls"].add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # obj.method() - track the method name
                imports["function_calls"].add(node.func.attr)

    # Convert sets to sorted lists for display
    imports["function_calls"] = sorted(imports["function_calls"])

    return imports


def format_output(module_path: str, imports: dict) -> str:
    """Format import info for display."""
    output = []
    output.append("=" * 80)
    output.append(f"Module: {module_path}")
    output.append("=" * 80)
    output.append("")

    # From imports (most important for mocking)
    if imports["from_imports"]:
        output.append("📦 FROM IMPORTS (likely need mocking):")
        output.append("")
        for imp in imports["from_imports"]:
            alias_str = f" as {imp['alias']}" if imp["alias"] else ""
            output.append(f"  from {imp['module']} import {imp['name']}{alias_str}")
        output.append("")

    # Direct imports
    if imports["direct_imports"]:
        output.append("📦 DIRECT IMPORTS:")
        output.append("")
        for imp in imports["direct_imports"]:
            alias_str = f" as {imp['alias']}" if imp["alias"] else ""
            output.append(f"  import {imp['name']}{alias_str}")
        output.append("")

    # Function calls (what actually gets used)
    if imports["function_calls"]:
        output.append("🔧 FUNCTIONS/METHODS CALLED (top 20):")
        output.append("")
        for func in imports["function_calls"][:20]:
            output.append(f"  {func}()")
        if len(imports["function_calls"]) > 20:
            output.append(f"  ... and {len(imports['function_calls']) - 20} more")
        output.append("")

    return "\n".join(output)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python discover_imports.py <module.path.to.file>")
        print("Example: python discover_imports.py nomarr.interfaces.cli.commands.queue")
        sys.exit(1)

    module_path = sys.argv[1]

    # Convert module path to file path
    file_path = Path(module_path.replace(".", "/") + ".py")

    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    imports = discover_imports(str(file_path))
    print(format_output(module_path, imports))
