#!/usr/bin/env python3
"""List private helper functions with their docstrings.

Scans Python files in a given folder for private functions (prefixed with _)
and displays them with their docstrings, signatures, and locations.

Usage:
    python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging
    python scripts/human-scripts/list_private_helpers.py nomarr/components/ml --format=json
    python scripts/human-scripts/list_private_helpers.py nomarr/components --recursive
    python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging --no-docstring

Examples:
    # Show all private helpers in tagging components
    python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging

    # Include subdirectories
    python scripts/human-scripts/list_private_helpers.py nomarr/components --recursive

    # Only show helpers missing docstrings
    python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging --no-docstring

    # Machine-readable output
    python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging --format=json

"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


def _extract_signature(node: ast.FunctionDef) -> str:
    """Build a human-readable signature string from a FunctionDef node."""
    parts: list[str] = []
    args = node.args

    # Regular positional/keyword args
    num_args = len(args.args)
    num_defaults = len(args.defaults)
    first_default = num_args - num_defaults

    for i, arg in enumerate(args.args):
        name = arg.arg
        annotation = _format_annotation(arg.annotation) if arg.annotation else None
        default_idx = i - first_default
        default = _format_default(args.defaults[default_idx]) if default_idx >= 0 else None

        part = name
        if annotation:
            part = f"{name}: {annotation}"
        if default is not None:
            part = f"{part} = {default}"
        parts.append(part)

    # *args
    if args.vararg:
        va = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            va = f"*{args.vararg.arg}: {_format_annotation(args.vararg.annotation)}"
        parts.append(va)
    elif args.kwonlyargs:
        parts.append("*")

    # keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        name = arg.arg
        annotation = _format_annotation(arg.annotation) if arg.annotation else None
        default = _format_default(args.kw_defaults[i]) if args.kw_defaults[i] else None

        part = name
        if annotation:
            part = f"{name}: {annotation}"
        if default is not None:
            part = f"{part} = {default}"
        parts.append(part)

    # **kwargs
    if args.kwarg:
        kw = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            kw = f"**{args.kwarg.arg}: {_format_annotation(args.kwarg.annotation)}"
        parts.append(kw)

    sig = ", ".join(parts)

    # Return annotation
    ret = ""
    if node.returns:
        ret = f" -> {_format_annotation(node.returns)}"

    return f"({sig}){ret}"


def _format_annotation(node: ast.expr | None) -> str:
    """Format a type annotation AST node to a readable string."""
    if node is None:
        return ""
    return ast.unparse(node)


def _format_default(node: ast.expr | None) -> str | None:
    """Format a default value AST node to a readable string."""
    if node is None:
        return None
    return ast.unparse(node)


def _is_private_helper(node: ast.stmt) -> bool:
    """Check if an AST node is a private helper function (not dunder)."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    name = node.name
    return name.startswith("_") and not name.startswith("__")


def extract_private_helpers(file_path: Path) -> list[dict[str, Any]]:
    """Extract all private helper functions from a Python file.

    Args:
        file_path: Path to the Python file.

    Returns:
        List of dicts with keys: name, line, signature, docstring, file.

    """
    try:
        code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  Warning: could not parse {file_path}: {e}", file=sys.stderr)
        return []

    helpers: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not _is_private_helper(node):
            continue

        docstring = ast.get_docstring(node)
        signature = _extract_signature(node)  # type: ignore[arg-type]

        helpers.append({
            "name": node.name,
            "line": node.lineno,
            "signature": f"{node.name}{signature}",
            "docstring": docstring,
            "file": str(file_path).replace("\\", "/"),
        })

    # Sort by line number
    helpers.sort(key=lambda h: h["line"])
    return helpers


def scan_folder(
    folder: Path,
    *,
    recursive: bool = False,
    no_docstring_only: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Scan a folder for private helpers.

    Args:
        folder: Directory to scan.
        recursive: Whether to recurse into subdirectories.
        no_docstring_only: If True, only return helpers missing docstrings.

    Returns:
        Dict mapping relative file paths to their private helpers.

    """
    if recursive:
        py_files = sorted(folder.rglob("*.py"))
    else:
        py_files = sorted(folder.glob("*.py"))

    results: dict[str, list[dict[str, Any]]] = {}

    for py_file in py_files:
        if py_file.name.startswith("__"):
            continue

        helpers = extract_private_helpers(py_file)

        if no_docstring_only:
            helpers = [h for h in helpers if h["docstring"] is None]

        if helpers:
            name = str(py_file).replace("\\", "/")
            results[rel] = helpers

    return results


def format_text(results: dict[str, list[dict[str, Any]]]) -> str:
    """Format results as human-readable text."""
    if not results:
        return "No private helpers found."

    lines: list[str] = []
    total = sum(len(hs) for hs in results.values())
    undocumented = sum(1 for hs in results.values() for h in hs if h["docstring"] is None)

    lines.append(f"Private Helpers: {total} total, {undocumented} missing docstrings")
    lines.append("=" * 70)

    for file_path, helpers in results.items():
        lines.append(f"\n{file_path}")
        lines.append("-" * len(file_path))

        for h in helpers:
            lines.append(f"  L{h['line']:>4}  {h['signature']}")
            if h["docstring"]:
                # Show first line of docstring, indented
                first_line = h["docstring"].strip().split("\n")[0]
                lines.append(f"          {first_line}")
            else:
                lines.append("          (no docstring)")

    lines.append(f"\n{'=' * 70}")
    lines.append(f"Total: {total} private helpers across {len(results)} files")
    if undocumented:
        lines.append(f"Missing docstrings: {undocumented}")

    return "\n".join(lines)


def format_json(results: dict[str, list[dict[str, Any]]]) -> str:
    """Format results as JSON."""
    total = sum(len(hs) for hs in results.values())
    undocumented = sum(1 for hs in results.values() for h in hs if h["docstring"] is None)

    output = {
        "summary": {
            "total_helpers": total,
            "total_files": len(results),
            "missing_docstrings": undocumented,
        },
        "files": results,
    }
    return json.dumps(output, indent=2)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="List private helper functions with docstrings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging\n"
        "  python scripts/human-scripts/list_private_helpers.py nomarr/components --recursive\n"
        "  python scripts/human-scripts/list_private_helpers.py nomarr/components/tagging --no-docstring\n",
    )
    parser.add_argument("folder", help="Path to folder to scan")
    parser.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    parser.add_argument("--no-docstring", action="store_true", help="Only show helpers missing docstrings")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")

    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    results = scan_folder(folder, recursive=args.recursive, no_docstring_only=args.no_docstring)

    if args.format == "json":
        print(format_json(results))
    else:
        print(format_text(results))


if __name__ == "__main__":
    main()
