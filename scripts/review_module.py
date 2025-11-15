"""
Module review assistant.

Helps systematically review Python modules against QC checklist.
"""

import ast
import sys
from pathlib import Path


def analyze_module(file_path: Path) -> dict:
    """
    Analyze a Python module for QC metrics.

    Args:
        file_path: Path to Python file

    Returns:
        Dictionary of metrics
    """
    metrics = {
        "file": str(file_path),
        "has_module_docstring": False,
        "functions": [],
        "classes": [],
        "missing_docstrings": [],
        "missing_type_hints": [],
        "has_todos": False,
        "has_fixmes": False,
        "has_print_statements": False,
        "line_count": 0,
    }

    try:
        code = file_path.read_text(encoding="utf-8")
        metrics["line_count"] = len(code.splitlines())

        # Check for TODOs/FIXMEs
        if "TODO" in code or "todo" in code:
            metrics["has_todos"] = True
        if "FIXME" in code or "fixme" in code:
            metrics["has_fixmes"] = True

        # Check for print statements (should use logging)
        if "print(" in code:
            metrics["has_print_statements"] = True

        # Parse AST
        tree = ast.parse(code)

        # Check module docstring
        if ast.get_docstring(tree):
            metrics["has_module_docstring"] = True

        # Analyze functions and classes
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "has_docstring": ast.get_docstring(node) is not None,
                    "has_return_type": node.returns is not None,
                    "arg_count": len(node.args.args),
                    "has_type_hints": False,
                }

                # Check if arguments have type hints
                if node.args.args:
                    typed_args = sum(1 for arg in node.args.args if arg.annotation)
                    func_info["has_type_hints"] = typed_args == len(node.args.args)

                metrics["functions"].append(func_info)

                # Track missing docstrings
                if not func_info["has_docstring"] and not node.name.startswith("_"):
                    metrics["missing_docstrings"].append(f"Function: {node.name} (line {node.lineno})")

                # Track missing type hints
                if not func_info["has_type_hints"] and not node.name.startswith("_"):
                    metrics["missing_type_hints"].append(f"Function: {node.name} (line {node.lineno})")

            elif isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "has_docstring": ast.get_docstring(node) is not None,
                    "method_count": sum(1 for n in node.body if isinstance(n, ast.FunctionDef)),
                }

                metrics["classes"].append(class_info)

                # Track missing docstrings
                if not class_info["has_docstring"] and not node.name.startswith("_"):
                    metrics["missing_docstrings"].append(f"Class: {node.name} (line {node.lineno})")

    except Exception as e:
        metrics["error"] = str(e)

    return metrics


def print_report(metrics: dict):
    """Print formatted QC report for a module."""
    print("\n" + "=" * 80)
    print(f"Module Review: {metrics['file']}")
    print("=" * 80)

    # Basic stats
    print("\n📊 Basic Statistics:")
    print(f"  Lines of code: {metrics['line_count']}")
    print(f"  Functions: {len(metrics['functions'])}")
    print(f"  Classes: {len(metrics['classes'])}")

    # Docstring coverage
    print("\n📝 Documentation:")
    if metrics["has_module_docstring"]:
        print("  ✅ Module docstring present")
    else:
        print("  ❌ Missing module docstring")

    if metrics["missing_docstrings"]:
        print(f"  ❌ Missing docstrings ({len(metrics['missing_docstrings'])}):")
        for item in metrics["missing_docstrings"]:
            print(f"     - {item}")
    else:
        print("  ✅ All public functions/classes documented")

    # Type hints
    print("\n🔤 Type Hints:")
    if metrics["missing_type_hints"]:
        print(f"  ⚠️  Missing type hints ({len(metrics['missing_type_hints'])}):")
        for item in metrics["missing_type_hints"]:
            print(f"     - {item}")
    else:
        print("  ✅ All public functions have type hints")

    # Code quality flags
    print("\n⚡ Code Quality:")
    if metrics["has_todos"]:
        print("  ⚠️  Contains TODO comments")
    if metrics["has_fixmes"]:
        print("  ⚠️  Contains FIXME comments")
    if metrics["has_print_statements"]:
        print("  ⚠️  Contains print() statements (should use logging)")

    if not any([metrics["has_todos"], metrics["has_fixmes"], metrics["has_print_statements"]]):
        print("  ✅ No quality flags")

    # Overall score
    print("\n📈 QC Score:")
    score = 0
    max_score = 5

    if metrics["has_module_docstring"]:
        score += 1
    if not metrics["missing_docstrings"]:
        score += 1
    if not metrics["missing_type_hints"]:
        score += 1
    if not metrics["has_todos"] and not metrics["has_fixmes"]:
        score += 1
    if not metrics["has_print_statements"]:
        score += 1

    print(f"  Score: {score}/{max_score} ({int(score / max_score * 100)}%)")

    if score == max_score:
        print("  ✅ Excellent quality!")
    elif score >= 4:
        print("  👍 Good quality")
    elif score >= 3:
        print("  ⚠️  Needs improvement")
    else:
        print("  ❌ Requires attention")


def main():
    """Review a module or directory."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/review_module.py <file_or_directory>")
        print("\nExamples:")
        print("  python scripts/review_module.py nomarr/core/processor.py")
        print("  python scripts/review_module.py nomarr/services/")
        return 1

    path = Path(sys.argv[1])

    if not path.exists():
        print(f"Error: {path} does not exist")
        return 1

    # Collect files to review
    if path.is_file():
        files = [path]
    else:
        files = sorted(path.rglob("*.py"))
        files = [f for f in files if not f.name.startswith("__")]

    print(f"Reviewing {len(files)} file(s)...")

    # Review each file
    all_metrics = []
    for file in files:
        metrics = analyze_module(file)
        all_metrics.append(metrics)
        print_report(metrics)

    # Summary
    if len(files) > 1:
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)

        total_funcs = sum(len(m["functions"]) for m in all_metrics)
        total_classes = sum(len(m["classes"]) for m in all_metrics)
        total_missing_docs = sum(len(m["missing_docstrings"]) for m in all_metrics)
        total_missing_hints = sum(len(m["missing_type_hints"]) for m in all_metrics)

        print(f"Files reviewed: {len(files)}")
        print(f"Total functions: {total_funcs}")
        print(f"Total classes: {total_classes}")
        print(f"Missing docstrings: {total_missing_docs}")
        print(f"Missing type hints: {total_missing_hints}")

        files_with_todos = sum(1 for m in all_metrics if m["has_todos"])
        files_with_fixmes = sum(1 for m in all_metrics if m["has_fixmes"])
        files_with_prints = sum(1 for m in all_metrics if m["has_print_statements"])

        if files_with_todos:
            print(f"Files with TODOs: {files_with_todos}")
        if files_with_fixmes:
            print(f"Files with FIXMEs: {files_with_fixmes}")
        if files_with_prints:
            print(f"Files with print(): {files_with_prints}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
