#!/usr/bin/env python3
"""
Refactor queue_svc.py to extract QueueService into a clean file.

This script uses AST to:
1. Extract the QueueService class (keep all methods)
2. Extract necessary imports
3. Remove legacy queue wrapper classes (BaseQueue, ProcessingQueue, etc.)
4. Write clean QueueService to new file
"""

import ast
import sys
from pathlib import Path


class ImportCollector(ast.NodeVisitor):
    """Collect all imports used by specific class."""

    def __init__(self):
        self.imports: list[ast.stmt] = []
        self.names_used: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.names_used.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Track module.attribute usage
        if isinstance(node.value, ast.Name):
            self.names_used.add(node.value.id)
        self.generic_visit(node)


class QueueServiceExtractor(ast.NodeVisitor):
    """Extract QueueService class and relevant imports."""

    def __init__(self):
        self.queue_service_class: ast.ClassDef | None = None
        self.all_imports: list[ast.stmt] = []
        self.module_docstring: str | None = None

    def visit_Module(self, node: ast.Module) -> None:
        # Extract module docstring if present
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            self.module_docstring = node.body[0].value.value

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.all_imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.all_imports.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == "QueueService":
            self.queue_service_class = node
            print(f"✓ Found QueueService class with {len(node.body)} members")
        self.generic_visit(node)


def filter_imports_for_class(all_imports: list[ast.stmt], class_node: ast.ClassDef) -> list[ast.stmt]:
    """Filter imports to only those used by the class."""

    # Collect all names used in the class
    collector = ImportCollector()
    collector.visit(class_node)
    names_used = collector.names_used

    # Always keep these imports
    always_keep = {
        "__future__",
        "logging",
        "time",
        "typing",
        "TYPE_CHECKING",
    }

    filtered = []
    for imp in all_imports:
        if isinstance(imp, ast.ImportFrom):
            # Keep if module is used or if any imported names are used
            module_name = imp.module or ""
            if module_name in always_keep:
                filtered.append(imp)
                continue

            # Check if any imported names are used
            if imp.names[0].name == "*":
                # Keep star imports if module is used
                if any(part in names_used for part in module_name.split(".")):
                    filtered.append(imp)
            else:
                # Keep if any imported name is used
                used_names = [
                    alias
                    for alias in imp.names
                    if alias.name in names_used or (alias.asname and alias.asname in names_used)
                ]
                if used_names:
                    # Create new import with only used names
                    new_imp = ast.ImportFrom(
                        module=imp.module,
                        names=used_names,
                        level=imp.level,
                    )
                    filtered.append(new_imp)

        elif isinstance(imp, ast.Import):
            # Keep if any imported module is used
            used_names = [
                alias
                for alias in imp.names
                if alias.name in names_used or (alias.asname and alias.asname in names_used)
            ]
            if used_names:
                new_imp = ast.Import(names=used_names)
                filtered.append(new_imp)

    return filtered


def generate_new_file_content(
    docstring: str | None,
    imports: list[ast.stmt],
    queue_service: ast.ClassDef,
) -> str:
    """Generate the new file content."""

    lines = []

    # Add new docstring
    new_docstring = """\"\"\"
Queue management service - orchestrates queue operations.

This service wraps queue components and workflows, adding:
- Business rules and validation
- Event broadcasting (SSE updates)  
- DTO transformation (components use dicts, service uses DTOs)
- Admin-friendly error handling and messaging
- Config-based feature checks

All heavy lifting is done by components (nomarr.components.queue) and
workflows (nomarr.workflows.queue). This service provides orchestration,
validation, and presentation logic.
\"\"\""""

    lines.append(new_docstring)
    lines.append("")

    # Add imports
    for imp in imports:
        lines.append(ast.unparse(imp))

    lines.append("")
    lines.append("")

    # Add QueueService class
    lines.append(ast.unparse(queue_service))
    lines.append("")

    return "\n".join(lines)


def main():
    # Paths
    repo_root = Path(__file__).parent.parent
    old_file = repo_root / "nomarr" / "services" / "queue_svc.py"
    new_file = repo_root / "nomarr" / "services" / "queue_service.py"

    if not old_file.exists():
        print(f"❌ Source file not found: {old_file}")
        sys.exit(1)

    # Read and parse old file
    print(f"📖 Reading {old_file.name}...")
    source = old_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Extract QueueService
    print("🔍 Extracting QueueService class...")
    extractor = QueueServiceExtractor()
    extractor.visit(tree)

    if not extractor.queue_service_class:
        print("❌ QueueService class not found in source file")
        sys.exit(1)

    # Filter imports
    print("📦 Filtering imports...")
    needed_imports = filter_imports_for_class(extractor.all_imports, extractor.queue_service_class)
    print(f"✓ Kept {len(needed_imports)} import statements")

    # Generate new file
    print("✍️  Generating new file...")
    new_content = generate_new_file_content(extractor.module_docstring, needed_imports, extractor.queue_service_class)

    # Write new file
    print(f"💾 Writing {new_file.name}...")
    new_file.write_text(new_content, encoding="utf-8")

    print(f"""
✅ Success! Created {new_file.name}

Next steps:
1. Review the generated file
2. Update imports to use queue components instead of queue wrappers
3. Fix any type annotations (QueueType literal)
4. Update interfaces to import from queue_service.py
5. Delete old queue_svc.py once everything works
""")


if __name__ == "__main__":
    main()
