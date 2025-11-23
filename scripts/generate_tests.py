#!/usr/bin/env python3
"""
Test Generator - Auto-generate test scaffolds with smart assertions.

This tool discovers a module's API and generates comprehensive test files
with fixtures, assertions, and proper structure following project conventions.

Usage:
    # Generate tests for a module
    python scripts/generate_tests.py nomarr.services.queue --output tests/unit/services/test_queue_service.py

    # Preview without writing
    python scripts/generate_tests.py nomarr.data.queue --preview

    # Generate with specific layer (auto-selects fixtures)
    python scripts/generate_tests.py nomarr.services.queue --layer services
"""

import argparse
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


def mock_dependencies():
    """Mock Docker-only dependencies for discovery."""
    mock_modules = [
        "essentia",
        "essentia.standard",
        "tensorflow",
        "tensorflow.lite",
        "tensorflow.lite.python",
        "tensorflow.lite.python.interpreter",
        "scipy",
        "scipy.stats",
        "scipy.signal",
    ]
    for mock_module in mock_modules:
        if mock_module not in sys.modules:
            sys.modules[mock_module] = MagicMock()


def discover_module_api(module_name: str) -> dict[str, Any]:
    """Discover module API (classes, methods, functions)."""
    mock_dependencies()

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        print(f"[ERROR] Failed to import {module_name}: {e}")
        return {}

    api = {"classes": {}, "functions": {}}

    for name in dir(module):
        if name.startswith("_"):
            continue

        obj = getattr(module, name)

        if inspect.ismodule(obj):
            continue

        # Classes
        if inspect.isclass(obj):
            if obj.__module__ != module_name:
                continue

            methods = {}
            for method_name in dir(obj):
                if method_name.startswith("_") and method_name != "__init__":
                    continue

                method = getattr(obj, method_name)
                if callable(method):
                    try:
                        sig = inspect.signature(method)
                        methods[method_name] = {
                            "signature": sig,
                            "doc": inspect.getdoc(method) or "",
                        }
                    except (ValueError, TypeError):
                        methods[method_name] = {"signature": None, "doc": ""}

            api["classes"][name] = {
                "methods": methods,
                "doc": inspect.getdoc(obj) or "",
            }

        # Functions
        elif inspect.isfunction(obj):
            if obj.__module__ != module_name:
                continue

            try:
                sig = inspect.signature(obj)
                api["functions"][name] = {
                    "signature": sig,
                    "doc": inspect.getdoc(obj) or "",
                }
            except (ValueError, TypeError):
                api["functions"][name] = {"signature": None, "doc": ""}

    return api


def detect_operation_type(method_name: str) -> str:
    """Detect operation type from method name."""
    method_lower = method_name.lower()

    if any(x in method_lower for x in ["add", "create", "insert", "queue"]):
        return "add"
    elif any(x in method_lower for x in ["get", "find", "fetch", "retrieve"]):
        return "get"
    elif any(x in method_lower for x in ["delete", "remove", "clear"]):
        return "delete"
    elif any(x in method_lower for x in ["list", "all", "filter", "search"]):
        return "list"
    elif any(x in method_lower for x in ["update", "set", "change", "modify", "mark"]):
        return "update"
    elif any(x in method_lower for x in ["reset", "cleanup", "purge"]):
        return "reset"
    elif any(x in method_lower for x in ["wait", "poll"]):
        return "wait"
    elif any(x in method_lower for x in ["count", "depth", "size"]):
        return "count"
    elif any(x in method_lower for x in ["start", "stop", "pause", "resume", "enable", "disable"]):
        return "control"
    else:
        return "other"


def infer_return_type(sig) -> str:
    """Infer return type from signature."""
    if sig is None:
        return "Any"

    return_annotation = sig.return_annotation

    if return_annotation == inspect.Signature.empty:
        return "Any"

    # Handle string annotations
    if isinstance(return_annotation, str):
        return return_annotation

    # Handle type objects
    try:
        return return_annotation.__name__
    except AttributeError:
        return str(return_annotation)


def generate_assertions(method_name: str, operation_type: str, return_type: str, sig) -> list[str]:
    """Generate smart assertions based on operation type and return type."""
    assertions = []
    method_lower = method_name.lower()

    # Type-based assertions - check dict/list first before int (since dict[str, int] contains "int")
    if "dict" in return_type.lower():
        assertions.append("assert isinstance(result, dict)")

    elif "list" in return_type.lower():
        assertions.append("assert isinstance(result, list)")

    elif "bool" in return_type.lower():
        assertions.append("assert isinstance(result, bool)")

    elif "int" in return_type.lower():
        assertions.append("assert isinstance(result, int)")
        # Only assert > 0 for actual ID returns, not counts/depths
        if (operation_type == "add" and "id" in method_lower) or (
            operation_type == "get"
            and "id" in method_lower
            and "depth" not in method_lower
            and "status" not in method_lower
            and "count" not in method_lower
        ):
            assertions.append("assert result > 0  # IDs are positive")
        elif any(x in method_lower for x in ["depth", "status", "count", "cleanup", "remove", "reset"]):
            assertions.append("assert result >= 0  # Non-negative count")

    elif "none" in return_type.lower():
        # Check if it's explicitly None (not Optional)
        if "|" not in return_type and "optional" not in return_type.lower():
            # Void method - just verify no exception
            assertions.append("# Method returns None - verify it completes without exception")
        else:
            # Optional return
            assertions.append("assert result is not None  # Success case")

    # Operation-specific assertions
    if operation_type == "add":
        assertions.extend(
            [
                "# Verify item was added",
                "# TODO: Check item can be retrieved",
                "# TODO: Verify count/depth increased",
            ]
        )

    elif operation_type == "get":
        if "none" in return_type.lower() or "|" in return_type:
            assertions.extend(
                [
                    "# TODO: Verify returned object has expected attributes",
                ]
            )
        else:
            assertions.extend(
                [
                    "# TODO: Verify returned data is correct",
                ]
            )

    elif operation_type == "delete":
        assertions.extend(
            [
                "# TODO: Verify item was removed",
                "# TODO: Verify get() returns None after delete",
            ]
        )

    elif operation_type == "list":
        assertions.extend(
            [
                "# TODO: Verify list contents",
                "# TODO: Test with filters if applicable",
            ]
        )

    elif operation_type == "update":
        assertions.extend(
            [
                "# TODO: Verify state changed",
                "# TODO: Verify get() reflects new state",
            ]
        )

    elif operation_type == "count":
        assertions.extend(
            [
                "assert result >= 0  # Count is non-negative",
            ]
        )

    return assertions


def generate_param_values(param_name: str, param_type: str) -> str:
    """Generate realistic parameter values based on name and type."""
    # File paths
    if "path" in param_name.lower() or "file" in param_name.lower():
        if "list" in param_type.lower():
            return "[str(temp_audio_file)]"
        return "str(temp_audio_file)"

    # IDs
    if "id" in param_name.lower():
        if "job" in param_name.lower():
            return "1"  # Valid job ID - removed inline comment
        return "1"

    # Booleans
    if "bool" in param_type.lower():
        if "force" in param_name.lower():
            return "True"
        if "recursive" in param_name.lower():
            return "True"
        return "False"

    # Integers
    if "int" in param_type.lower():
        if "timeout" in param_name.lower():
            return "30"
        if "max" in param_name.lower() or "age" in param_name.lower():
            return "24"
        return "1"

    # Status strings
    if "status" in param_name.lower():
        return '"pending"'

    # Default
    if "str" in param_type.lower():
        return '"test_value"'

    return "None"


def generate_test_cases(class_name: str, method_name: str, method_info: dict) -> list[dict]:
    """Generate test cases for a method."""
    sig = method_info["signature"]
    operation_type = detect_operation_type(method_name)
    return_type = infer_return_type(sig)
    method_lower = method_name.lower()

    # Parse parameters (skip self)
    params = []
    param_list = []
    if sig:
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type_str = str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any"

            # Required parameter or methods that need specific optional params
            if param.default == inspect.Parameter.empty:
                # Required parameter
                param_value = generate_param_values(param_name, param_type_str)
                params.append(f"{param_name}={param_value}")
                param_list.append((param_name, param_type_str, param_value, True))
            else:
                # Optional parameter - include for certain methods
                # remove_jobs needs one of: job_id, status, or all=True
                if (method_lower == "remove_jobs" and param_name == "all") or (
                    method_lower == "reset_jobs" and param_name == "stuck"
                ):
                    params.append(f"{param_name}=True")
                    param_list.append((param_name, param_type_str, "True", True))
                else:
                    param_list.append((param_name, param_type_str, "", False))

    test_cases = []

    # Success case
    success_case = {
        "name": f"test_{method_name}_success",
        "doc": f"Should successfully {method_name.replace('_', ' ')}.",
        "operation": operation_type,
        "params": params,
        "param_list": param_list,
        "assertions": generate_assertions(method_name, operation_type, return_type, sig),
    }
    test_cases.append(success_case)

    # None/not found case for Optional return types
    if (
        "none" in return_type.lower() or "|" in return_type or "optional" in return_type.lower()
    ) and operation_type == "get":
        # For not_found, use invalid ID
        not_found_params = []
        for param_name, param_type, _, _ in param_list:
            if "id" in param_name.lower():
                not_found_params.append(f"{param_name}=99999")  # Non-existent ID
            else:
                param_value = generate_param_values(param_name, param_type)
                not_found_params.append(f"{param_name}={param_value}")

        not_found_case = {
            "name": f"test_{method_name}_not_found",
            "doc": "Should return None when item not found.",
            "operation": "get_none",
            "params": not_found_params,
            "param_list": param_list,
            "assertions": ["assert result is None"],
        }
        test_cases.append(not_found_case)

    # Error case for operations that might raise exceptions
    if operation_type in ["add", "delete", "update"] and sig:
        # Check if parameters suggest file paths
        has_path_param = any("path" in p[0] or "file" in p[0] for p in param_list)
        if has_path_param:
            error_params = []
            for param_name, param_type, _, _ in param_list:
                if "path" in param_name.lower() or "file" in param_name.lower():
                    if "list" in param_type.lower():
                        error_params.append(f'{param_name}=["/nonexistent.mp3"]')
                    else:
                        error_params.append(f'{param_name}="/nonexistent.mp3"')
                else:
                    param_value = generate_param_values(param_name, param_type)
                    error_params.append(f"{param_name}={param_value}")

            error_case = {
                "name": f"test_{method_name}_invalid_path_raises_error",
                "doc": "Should raise error for invalid file path.",
                "operation": "error",
                "params": error_params,
                "param_list": param_list,
                "assertions": [
                    "with pytest.raises(FileNotFoundError):",
                    "    pass  # Call happens in with block",
                ],
            }
            test_cases.append(error_case)

    return test_cases


def discover_conftest_fixtures(test_path: Path | None = None) -> dict[str, str]:
    """Discover fixtures available in conftest.py files.

    Returns dict mapping fixture names to their file paths.
    """
    if test_path is None:
        test_path = Path("tests")

    fixtures = {}

    # Walk up from test path to find conftest files
    current = test_path
    while current.name != "":
        conftest_path = current / "conftest.py"
        if conftest_path.exists():
            content = conftest_path.read_text(encoding="utf-8")
            # Find all @pytest.fixture decorated functions
            import re

            pattern = r"@pytest\.fixture.*?\ndef\s+(\w+)\s*\("
            for match in re.finditer(pattern, content, re.DOTALL):
                fixture_name = match.group(1)
                fixtures[fixture_name] = str(conftest_path)

        # Move up one directory
        if current.parent == current:
            break
        current = current.parent

    return fixtures


def determine_fixtures(
    module_name: str,
    class_name: str,
    layer: str | None = None,
    available_fixtures: dict | None = None,
) -> tuple[list[str], str | None]:
    """Determine which fixtures are needed based on module/class.

    Returns tuple of (fixture_list, preferred_fixture_name).
    If a real fixture exists for this class, preferred_fixture_name will be set.
    """
    if available_fixtures is None:
        available_fixtures = {}

    fixtures = []
    preferred_fixture = None

    # Check if there's a real fixture for this class
    # Map class names to expected fixture names
    class_to_fixture_map = {
        "QueueService": "real_queue_service",
        "LibraryService": "real_library_service",
        "ProcessingService": "real_processing_service",
        "WorkerService": "real_worker_service",
        "HealthMonitor": "real_health_monitor",
        "ProcessingQueue": "test_db",  # ProcessingQueue needs test_db directly
        "Database": "test_db",  # Database is test_db itself
    }

    # Check if we have a real fixture for this class
    if class_name in class_to_fixture_map:
        fixture_name = class_to_fixture_map[class_name]
        if fixture_name in available_fixtures:
            preferred_fixture = fixture_name
            # Don't need to create instance fixture - use the real one directly
            return [], preferred_fixture

    # Auto-detect layer if not specified
    if layer is None:
        if "data" in module_name:
            layer = "data"
        elif "services" in module_name:
            layer = "services"
        elif "ml" in module_name:
            layer = "ml"
        elif "interfaces" in module_name:
            layer = "interfaces"
        else:
            layer = "other"

    # Layer-specific fixtures (only if no preferred fixture)
    if layer == "data":
        fixtures.extend(["test_db"])
    elif layer == "services":
        # For services, we want the real service fixtures
        if "queue" in class_name.lower() and "real_queue_service" in available_fixtures:
            preferred_fixture = "real_queue_service"
        elif "library" in class_name.lower() and "real_library_service" in available_fixtures:
            preferred_fixture = "real_library_service"
        elif "processing" in class_name.lower() and "real_processing_service" in available_fixtures:
            preferred_fixture = "real_processing_service"
        elif "worker" in class_name.lower() and "real_worker_service" in available_fixtures:
            preferred_fixture = "real_worker_service"
        elif "health" in class_name.lower() and "real_health_monitor" in available_fixtures:
            preferred_fixture = "real_health_monitor"
        else:
            fixtures.extend(["test_db"])
    elif layer == "ml":
        fixtures.extend(["skip_if_no_essentia", "skip_if_no_tensorflow"])

    # Additional fixtures for file operations
    # Only add these if we don't have a preferred fixture (which would handle them)
    if preferred_fixture is None:
        if ("file" in class_name.lower() or "audio" in class_name.lower()) and "temp_audio_file" in available_fixtures:
            fixtures.append("temp_audio_file")
        if "library" in class_name.lower() and "temp_music_library" in available_fixtures:
            fixtures.append("temp_music_library")

    return fixtures, preferred_fixture


def generate_test_file(module_name: str, api: dict, layer: str | None = None, output_path: str | None = None) -> str:
    """Generate complete test file content."""
    lines = []

    # Discover available fixtures from conftest
    if output_path:
        test_dir = Path(output_path).parent
    else:
        test_dir = Path("tests")

    available_fixtures = discover_conftest_fixtures(test_dir)

    # Header
    lines.append('"""')
    lines.append(f"Unit tests for {module_name} module.")
    lines.append("")
    lines.append("Tests use REAL fixtures from conftest.py - no redundant mocks.")
    lines.append('"""')
    lines.append("")

    # Imports
    lines.append("import pytest")
    lines.append("")
    lines.append(f"from {module_name} import (")

    # Import all classes and functions
    imports = []
    if api.get("classes"):
        imports.extend(sorted(api["classes"].keys()))
    if api.get("functions"):
        imports.extend(sorted(api["functions"].keys()))

    for imp in imports:
        lines.append(f"    {imp},")
    lines.append(")")
    lines.append("")
    lines.append("")

    # Generate tests for each class
    for class_name, class_info in sorted(api.get("classes", {}).items()):
        fixture_list, preferred_fixture = determine_fixtures(module_name, class_name, layer, available_fixtures)

        # Only create instance fixture if no preferred fixture exists
        if preferred_fixture is None:
            # Need to create an instance fixture
            lines.append("@pytest.fixture")
            lines.append(f"def {class_name.lower()}_instance({', '.join(fixture_list)}):")
            lines.append(f'    """Provide a {class_name} instance for testing."""')
            if "test_db" in fixture_list:
                lines.append(f"    return {class_name}(test_db)")
            else:
                lines.append(f"    return {class_name}()")
            lines.append("")
            lines.append("")
            fixture_to_use = f"{class_name.lower()}_instance"
        else:
            # Use the existing real fixture from conftest
            fixture_to_use = preferred_fixture

        # Generate test classes for each method
        for method_name, method_info in sorted(class_info["methods"].items()):
            if method_name == "__init__":
                continue

            # Create test class
            test_class_name = f"Test{class_name}{method_name.title().replace('_', '')}"
            lines.append(f"class {test_class_name}:")
            lines.append(f'    """Test {class_name}.{method_name}() operations."""')
            lines.append("")

            # Generate test cases
            test_cases = generate_test_cases(class_name, method_name, method_info)

            for test_case in test_cases:
                extra_fixtures = []

                # Add extra fixtures based on test case parameter usage
                params_str = ", ".join(test_case.get("params", []))
                if "temp_audio_file" in params_str and "temp_audio_file" in available_fixtures:
                    extra_fixtures.append("temp_audio_file")
                if "temp_music_library" in params_str and "temp_music_library" in available_fixtures:
                    extra_fixtures.append("temp_music_library")

                all_fixtures = [fixture_to_use, *extra_fixtures]
                fixture_str = ", ".join(all_fixtures)

                lines.append(f"    def {test_case['name']}(self, {fixture_str}):")
                lines.append(f'        """{test_case["doc"]}"""')
                lines.append("        # Arrange")
                lines.append("")

                # Act section with proper parameters
                params_str = ", ".join(test_case.get("params", []))

                # Handle error cases differently
                if test_case["operation"] == "error":
                    lines.append("        # Act & Assert")
                    for assertion in test_case["assertions"]:
                        if "with pytest" in assertion:
                            lines.append(f"        {assertion}")
                        elif "pass" in assertion:
                            lines.append(f"            {fixture_to_use}.{method_name}({params_str})")
                else:
                    lines.append("        # Act")
                    lines.append(f"        result = {fixture_to_use}.{method_name}({params_str})")
                    lines.append("")
                    lines.append("        # Assert")

                    for assertion in test_case["assertions"]:
                        if not assertion.startswith("with"):
                            lines.append(f"        {assertion}")

                lines.append("")
                lines.append("")

    # Generate tests for standalone functions
    if api.get("functions"):
        lines.append("# === STANDALONE FUNCTION TESTS ===")
        lines.append("")

        for func_name, func_info in sorted(api.get("functions", {}).items()):
            test_func_name = f"test_{func_name}"
            lines.append(f"def {test_func_name}():")
            doc_summary = func_info["doc"].split("\n")[0] if func_info["doc"] else f"Test {func_name}"
            lines.append(f'    """{doc_summary}"""')
            lines.append("    # Arrange")
            lines.append("")
            lines.append("    # Act")
            lines.append(f"    result = {func_name}()")
            lines.append("")
            lines.append("    # Assert")
            lines.append("    # TODO: Add assertions")
            lines.append("    pass")
            lines.append("")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate test scaffolds with smart assertions")
    parser.add_argument("module", help="Module name (e.g., nomarr.services.queue)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--layer", choices=["data", "services", "ml", "interfaces"], help="Layer type (auto-detected if not specified)"
    )
    parser.add_argument("--preview", action="store_true", help="Preview without writing file")

    args = parser.parse_args()

    # Add current directory to path
    sys.path.insert(0, str(Path.cwd()))

    print(f"Discovering API for {args.module}...")
    api = discover_module_api(args.module)

    if not api or (not api.get("classes") and not api.get("functions")):
        print(f"[ERROR] No public API found in {args.module}")
        return 1

    print(f"[OK] Found {len(api.get('classes', {}))} classes, {len(api.get('functions', {}))} functions")

    print("Generating tests...")
    test_content = generate_test_file(args.module, api, args.layer)

    if args.preview:
        print("\n" + "=" * 80)
        print("PREVIEW:")
        print("=" * 80 + "\n")
        print(test_content)
        return 0

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Auto-generate path
        module_parts = args.module.split(".")
        short_name = module_parts[-1]
        output_path = Path(f"tests/unit/{module_parts[1]}/test_{short_name}.py")

    # Create directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write file
    output_path.write_text(test_content, encoding="utf-8")
    print(f"[OK] Generated test file: {output_path}")
    print("Review and enhance with domain-specific assertions!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
