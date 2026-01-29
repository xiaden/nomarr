"""Architecture and code quality tests.

These tests enforce architectural boundaries and code patterns through static analysis.
They should be fast, deterministic, and safe to run on every commit.

NOTE: Many of these tests overlap with import-linter rules (which we also use).
The duplication is intentional - these pytest tests provide:
- Faster feedback during development (run with pytest)
- Better error messages with specific line numbers
- Integration with CI test suites
- Additional checks beyond import boundaries (like raw SQL usage)

Architecture rules enforced:
1. Only persistence layer may use raw SQL (db.conn.execute) - NOT in import-linter
2. Workflows must not import services or app - ALSO in import-linter
3. Helpers must not import upward layers - ALSO in import-linter
4. Leaf slices (ml/tagging/analytics) must not import orchestration layers - ALSO in import-linter
5. Essentia imports ONLY in ml/backend_essentia.py - NOT in import-linter
"""

import re
from collections.abc import Generator
from pathlib import Path

import pytest

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
NOMARR_DIR = PROJECT_ROOT / "nomarr"


def find_python_files(directory: Path, exclude_dirs: set[str] | None = None) -> Generator[Path, None, None]:
    """Find all Python files in a directory, excluding specified subdirectories.

    Args:
        directory: Directory to search
        exclude_dirs: Set of directory names to exclude (e.g., {"__pycache__", "migrations"})

    Yields:
        Path objects for Python files

    """
    exclude_dirs = exclude_dirs or {"__pycache__", "migrations", ".pytest_cache"}

    for path in directory.rglob("*.py"):
        # Skip if any parent directory is in exclude list
        if any(part in exclude_dirs for part in path.parts):
            continue
        yield path


def find_import_violations(file_path: Path, forbidden_imports: list[str]) -> list[tuple[int, str]]:
    """Find lines that import forbidden modules.

    Args:
        file_path: Path to Python file
        forbidden_imports: List of module patterns to forbid (e.g., ["nomarr.services", "nomarr.app"])

    Returns:
        List of (line_number, line_content) tuples for violations

    """
    violations = []

    try:
        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                stripped = line.strip()

                # Skip comments and empty lines
                if not stripped or stripped.startswith("#"):
                    continue

                # Check for forbidden imports
                for forbidden in forbidden_imports:
                    # Match "import nomarr.services" or "from nomarr.services"
                    if re.match(rf"^(import|from)\s+{re.escape(forbidden)}\b", stripped):
                        violations.append((line_num, line.rstrip()))
                    # Also catch "from nomarr import services"
                    elif "from nomarr import" in stripped:
                        parts = stripped.split("import", 1)
                        if len(parts) == 2:
                            imported = parts[1].strip().split(",")
                            for imp in imported:
                                imp_clean = imp.strip().split()[0]  # Get first word (handles "as" aliases)
                                if forbidden.endswith(f".{imp_clean}") or forbidden == f"nomarr.{imp_clean}":
                                    violations.append((line_num, line.rstrip()))

    except Exception as e:
        # If we can't read the file, report it as a test failure
        pytest.fail(f"Failed to read {file_path}: {e}")

    return violations


@pytest.mark.code_smell
def test_no_raw_db_execute_outside_persistence():
    """Test 1: Ensure raw SQL (db.conn.execute) is only used in persistence layer.

    Raw SQL queries should be encapsulated in the persistence layer for:
    - Maintainability (centralized SQL changes)
    - Security (consistent parameterization)
    - Testing (easier to mock persistence layer)

    Note: This is a code smell test, not a functional test.
    Marked with @pytest.mark.code_smell to skip in CI.
    """
    violations = []

    for py_file in find_python_files(NOMARR_DIR):
        # Skip if file is in persistence directory
        if "persistence" in py_file.parts:
            continue

        try:
            with open(py_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    # Look for db.conn.execute pattern
                    if re.search(r"\bdb\.conn\.execute\s*\(", line):
                        rel_path = py_file.relative_to(PROJECT_ROOT)
                        violations.append(f"  {rel_path}:{line_num}: {line.strip()}")
        except Exception as e:
            pytest.fail(f"Failed to read {py_file}: {e}")

    if violations:
        msg = (
            "Found raw SQL (db.conn.execute) outside persistence layer.\n"
            "Raw SQL is only allowed in nomarr/persistence/ modules.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


def test_workflows_do_not_import_services_or_app():
    """Test 2: Ensure workflows don't import services or app.

    Workflows should be pure domain operations that:
    - Accept dependencies as parameters (dependency injection)
    - Don't know about service orchestration
    - Don't depend on the application container

    This keeps workflows testable and reusable.
    """
    workflows_dir = NOMARR_DIR / "workflows"
    if not workflows_dir.exists():
        pytest.skip("No workflows directory found")

    forbidden_imports = ["nomarr.services", "nomarr.app"]
    violations = []

    for py_file in find_python_files(workflows_dir):
        file_violations = find_import_violations(py_file, forbidden_imports)
        if file_violations:
            rel_path = py_file.relative_to(PROJECT_ROOT)
            for line_num, line in file_violations:
                violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found workflows importing services or app.\n"
            "Workflows must not import nomarr.services or nomarr.app.\n"
            "Use dependency injection instead (pass dependencies as parameters).\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


def test_helpers_do_not_import_upwards():
    """Test 3: Ensure helpers don't import upward layers.

    Helpers should be pure utilities that only depend on:
    - Standard library
    - Third-party libraries
    - Other helpers

    They must NOT depend on:
    - interfaces (presentation layer)
    - services (orchestration layer)
    - workflows (domain operations)
    - app (application container)
    """
    helpers_dir = NOMARR_DIR / "helpers"
    if not helpers_dir.exists():
        pytest.skip("No helpers directory found")

    forbidden_imports = [
        "nomarr.interfaces",
        "nomarr.services",
        "nomarr.workflows",
        "nomarr.app",
    ]
    violations = []

    for py_file in find_python_files(helpers_dir):
        file_violations = find_import_violations(py_file, forbidden_imports)
        if file_violations:
            rel_path = py_file.relative_to(PROJECT_ROOT)
            for line_num, line in file_violations:
                violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found helpers importing upward layers.\n"
            "Helpers must not import interfaces/services/workflows/app.\n"
            "Helpers should only use stdlib and third-party libraries.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


def test_leaf_slices_do_not_depend_on_higher_layers():
    """Test 4: Ensure leaf domain slices don't import orchestration layers.

    Leaf slices (ml, tagging, analytics) should be independent domain logic:
    - Pure computation and transformations
    - No knowledge of services, workflows, or interfaces
    - Receive data as parameters, return results

    This keeps them:
    - Testable in isolation
    - Reusable across different contexts
    - Free from circular dependencies
    """
    leaf_slices = ["ml", "tagging", "analytics"]
    forbidden_imports = [
        "nomarr.services",
        "nomarr.workflows",
        "nomarr.interfaces",
        "nomarr.app",
    ]
    violations = []

    for slice_name in leaf_slices:
        slice_dir = NOMARR_DIR / slice_name
        if not slice_dir.exists():
            continue

        for py_file in find_python_files(slice_dir):
            file_violations = find_import_violations(py_file, forbidden_imports)
            if file_violations:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                for line_num, line in file_violations:
                    violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found leaf slices (ml/tagging/analytics) importing orchestration layers.\n"
            "Leaf slices must not import services/workflows/interfaces/app.\n"
            "These should be pure domain logic that receives data as parameters.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


def test_no_essentia_imports_outside_backend():
    """Test 5: Ensure Essentia is ONLY imported in components/ml/ml_backend_essentia_comp.py.

    Essentia is an optional dependency and must be completely isolated:
    - ONLY components/ml/ml_backend_essentia_comp.py may import essentia/essentia_tensorflow
    - All other code must use the backend module's interface
    - Dependencies are passed via function parameters (dependency injection)

    This ensures:
    - Single point of Essentia integration
    - Clear boundary for optional dependency
    - Easy to mock/test without Essentia
    - No scattered try/except blocks throughout codebase
    """
    violations = []
    backend_file = NOMARR_DIR / "components" / "ml" / "ml_backend_essentia_comp.py"

    for py_file in find_python_files(NOMARR_DIR):
        # Skip test files and the dedicated backend module
        if "test" in py_file.parts or py_file == backend_file:
            continue

        try:
            with open(py_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    stripped = line.strip()

                    # Skip comments and empty lines
                    if not stripped or stripped.startswith("#"):
                        continue

                    # Check for any Essentia imports
                    if re.match(r"^(import\s+essentia|from\s+essentia)", stripped):
                        rel_path = py_file.relative_to(PROJECT_ROOT)
                        violations.append(f"  {rel_path}:{line_num}: {line.rstrip()}")

        except Exception as e:
            pytest.fail(f"Failed to read {py_file}: {e}")

    if violations:
        msg = (
            "Found Essentia imports outside components/ml/ml_backend_essentia_comp.py.\n\n"
            "Essentia must ONLY be imported in the dedicated backend module:\n"
            "  - components/ml/ml_backend_essentia_comp.py is the ONLY file allowed to import Essentia\n"
            "  - All other code must use ml_backend_essentia_comp.py's interface\n"
            "  - Pass dependencies via parameters (dependency injection)\n\n"
            "This maintains a single integration point and clear boundaries.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


# === Additional helper tests for architecture validation ===


def test_persistence_layer_structure():
    """Sanity check: Verify persistence layer exists and has expected structure.

    This test documents the expected structure of the persistence layer.
    """
    persistence_dir = NOMARR_DIR / "persistence"
    assert persistence_dir.exists(), "Persistence directory should exist"
    assert (persistence_dir / "db.py").exists(), "Main db.py should exist"

    # Check for database operations subdirectory
    database_dir = persistence_dir / "database"
    if database_dir.exists():
        # If database/ exists, verify it has operation modules
        py_files = list(database_dir.glob("*.py"))
        assert len(py_files) > 0, "database/ directory should contain operation modules"


def test_workflows_layer_structure():
    """Sanity check: Verify workflows layer exists and follows naming convention.

    Workflows should be named as verb_object.py (e.g., process_file.py, scan_library.py)
    """
    workflows_dir = NOMARR_DIR / "workflows"
    if not workflows_dir.exists():
        pytest.skip("No workflows directory found")

    py_files = [f for f in workflows_dir.glob("*.py") if f.name not in ("__init__.py", "WORKFLOWS.md")]

    # Check that workflow files follow verb_object pattern or are reasonable exceptions
    for py_file in py_files:
        name = py_file.stem
        # Should contain underscore (verb_object pattern) or be a clear workflow name
        assert "_" in name or name in ["processor", "scanner"], (
            f"Workflow {py_file.name} should follow verb_object.py naming (e.g., process_file.py)"
        )


def test_services_do_not_import_interfaces():
    """Additional check: Ensure services don't import interfaces.

    Services should orchestrate workflows and domain logic, but:
    - Must not import interfaces (presentation layer)
    - Should be called BY interfaces, not call them
    """
    services_dir = NOMARR_DIR / "services"
    if not services_dir.exists():
        pytest.skip("No services directory found")

    forbidden_imports = ["nomarr.interfaces"]
    violations = []

    for py_file in find_python_files(services_dir):
        file_violations = find_import_violations(py_file, forbidden_imports)
        if file_violations:
            rel_path = py_file.relative_to(PROJECT_ROOT)
            for line_num, line in file_violations:
                violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found services importing interfaces.\n"
            "Services must not import nomarr.interfaces.\n"
            "Services should be called BY interfaces, not import them.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)
