#!/usr/bin/env python3
"""Fix LOG015: Convert root logger calls to module loggers.

Transforms:
    import logging
    logging.info("message")

Into:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("message")
"""

import ast
import sys
from pathlib import Path


class RootLoggerFixer(ast.NodeTransformer):
    """Replace logging.X() with logger.X() and track if logger needs to be added."""

    def __init__(self):
        self.needs_logger = False
        self.has_logger_import = False
        self.has_logger_var = False
        self.logging_methods = {"debug", "info", "warning", "error", "critical", "exception"}

    def visit_Import(self, node):
        """Check if 'import logging' exists."""
        for alias in node.names:
            if alias.name == "logging":
                self.has_logger_import = True
        return node

    def visit_ImportFrom(self, node):
        """Check if 'from logging import ...' exists."""
        if node.module == "logging":
            self.has_logger_import = True
        return node

    def visit_Assign(self, node):
        """Check if 'logger = logging.getLogger(...)' already exists."""
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute):
                if (
                    isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "logging"
                    and node.value.func.attr == "getLogger"
                ):
                    # Found logger = logging.getLogger(...)
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "logger":
                            self.has_logger_var = True
        return node

    def visit_Expr(self, node):
        """Transform logging.X() calls into logger.X()."""
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute):
                if (
                    isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "logging"
                    and node.value.func.attr in self.logging_methods
                ):
                    # Found logging.X() call
                    self.needs_logger = True
                    # Change logging to logger
                    node.value.func.value.id = "logger"
        return node

    def visit_Call(self, node):
        """Transform logging.X() calls in expressions."""
        if isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logging"
                and node.func.attr in self.logging_methods
            ):
                # Found logging.X() call
                self.needs_logger = True
                # Change logging to logger
                node.func.value.id = "logger"
        self.generic_visit(node)
        return node


def fix_file(file_path: Path, dry_run: bool = False) -> bool:
    """Fix root logger calls in a single file.

    Args:
        file_path: Path to Python file to fix
        dry_run: If True, report changes but don't write files

    Returns:
        True if file would be/was modified, False otherwise
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Skip {file_path}: Cannot read file - {e}", file=sys.stderr)
        return False
    
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        print(f"Skip {file_path}: Syntax error - {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Skip {file_path}: Parse error - {e}", file=sys.stderr)
        return False

    # Transform the tree
    fixer = RootLoggerFixer()
    new_tree = fixer.visit(tree)

    # If no root logger calls found, skip
    if not fixer.needs_logger:
        return False

    # If logger already exists, just unparse
    if fixer.has_logger_var:
        try:
            # Ensure all nodes have location info
            ast.fix_missing_locations(new_tree)
            new_source = ast.unparse(new_tree)
            if dry_run:
                print(f"[DRY RUN] Would fix {file_path} (logger var exists)")
            else:
                file_path.write_text(new_source, encoding="utf-8")
                print(f"Fixed {file_path} (logger var exists)")
            return True
        except Exception as e:
            print(f"Error unparsing {file_path}: {e}", file=sys.stderr)
            return False

    # Need to add logger = logging.getLogger(__name__)
    if not fixer.has_logger_import:
        print(f"Skip {file_path}: no logging import", file=sys.stderr)
        return False

    # Find insertion point (after imports, before first non-import statement)
    insert_pos = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_pos = i + 1
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # Skip module docstring
            if i == 0:
                insert_pos = 1
        else:
            break

    # Create logger assignment: logger = logging.getLogger(__name__)
    logger_assign = ast.Assign(
        targets=[ast.Name(id="logger", ctx=ast.Store())],
        value=ast.Call(
            func=ast.Attribute(value=ast.Name(id="logging", ctx=ast.Load()), attr="getLogger", ctx=ast.Load()),
            args=[ast.Name(id="__name__", ctx=ast.Load())],
            keywords=[],
        ),
    )

    # Insert into tree
    new_tree.body.insert(insert_pos, logger_assign)
    
    # Fix missing line numbers and other location info
    ast.fix_missing_locations(new_tree)

    # Unparse and write
    try:
        new_source = ast.unparse(new_tree)
        if dry_run:
            print(f"[DRY RUN] Would fix {file_path}")
        else:
            file_path.write_text(new_source, encoding="utf-8")
            print(f"Fixed {file_path}")
        return True
    except Exception as e:
        print(f"Error unparsing {file_path}: {e}", file=sys.stderr)
        return False


def main():
    """Fix all Python files in nomarr/ and scripts/."""
    root = Path(__file__).parent.parent

    paths = [root / "nomarr", root / "scripts"]

    files_checked = 0
    files_modified = 0

    for search_path in paths:
        if not search_path.exists():
            continue

        for py_file in search_path.rglob("*.py"):
            # Skip cache and venv
            if any(part.startswith(".") or part == "__pycache__" for part in py_file.parts):
                continue

            files_checked += 1
            if fix_file(py_file):
                files_modified += 1

    print(f"\nChecked {files_checked} files, modified {files_modified}")


if __name__ == "__main__":
    main()
