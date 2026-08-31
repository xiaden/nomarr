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
5. Essentia imports ONLY in ml_audio_comp.py and ml_preprocess_comp.py - NOT in import-linter
6. Higher layers must not import Tier 1/Tier 2 persistence internals - NOT in import-linter
"""

import importlib.util
import io
import json
import re
import shutil
import subprocess
import tokenize
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
NOMARR_DIR = PROJECT_ROOT / "nomarr"
PERSISTENCE_TIER_BOOTSTRAP_ALLOWLIST: set[Path] = set()

# Grandfathered ArangoDB field-name references (_id/_key) outside persistence.
# Key: (relative file path, line number). Value: ISO-format expiry date.
# Migrated from .arango-field-allowlist.yaml (Part E, P1-S1). Expiry policy:
# default 90 days from generation (2026-10-15); interface-boundary entries
# (Pydantic Field descriptions documenting the API contract) 365 days
# (2027-07-17). The test fails if a reference is NOT in this allowlist, or if
# an allowlist entry's expiry has passed.
ARANGO_FIELD_ALLOWLIST: dict[tuple[str, int], str] = {
    ("nomarr/components/library/move_detection_comp.py", 31): "2026-10-15",
    ("nomarr/components/library/reconcile_paths_comp.py", 38): "2026-10-15",
    ("nomarr/components/library/tag_hydration_comp.py", 87): "2026-10-15",
    ("nomarr/components/library/tag_hydration_comp.py", 136): "2026-10-15",
    ("nomarr/components/ml/vectors/ml_vector_retrieve_comp.py", 29): "2026-10-15",
    ("nomarr/components/workers/worker_tag_comp.py", 33): "2026-10-15",
    ("nomarr/helpers/dto/navidrome_dto.py", 222): "2026-10-15",
    ("nomarr/interfaces/api/types/info_types.py", 176): "2027-07-17",
    ("nomarr/interfaces/api/types/info_types.py", 195): "2027-07-17",
    ("nomarr/interfaces/api/types/playlist_import_types.py", 44): "2027-07-17",
    ("nomarr/services/domain/analytics_svc.py", 201): "2026-10-15",
    ("nomarr/services/domain/library_svc/songs.py", 116): "2026-10-15",
    ("nomarr/services/domain/playlist_import_svc.py", 59): "2026-10-15",
    ("nomarr/services/domain/tagging_svc/query.py", 96): "2026-10-15",
    ("nomarr/services/domain/tagging_svc/query.py", 133): "2026-10-15",
    ("nomarr/workflows/library/reconcile_paths_wf.py", 31): "2026-10-15",
    ("nomarr/workflows/library/scan_library_full_wf.py", 76): "2026-10-15",
    ("nomarr/workflows/library/scan_library_quick_wf.py", 72): "2026-10-15",
    ("nomarr/workflows/library/scan_setup_wf.py", 43): "2026-10-15",
    ("nomarr/workflows/navidrome/generate_playlists_wf.py", 82): "2026-10-15",
    ("nomarr/workflows/processing/process_file_wf.py", 60): "2026-10-15",
    ("nomarr/workflows/processing/write_file_tags_wf.py", 48): "2026-10-15",
    ("nomarr/workflows/processing/write_file_tags_wf.py", 121): "2026-10-15",
    ("nomarr/workflows/vectors/get_track_vector_wf.py", 32): "2026-10-15",
}


def _docstring_lines(content: str) -> set[int]:
    """Return 1-based line numbers that fall inside triple-quoted docstrings.

    Uses the ``tokenize`` module so prose inside docstrings is excluded from
    scans without hiding genuine string-literal references (e.g. a
    ``__tablename__ = "file_tags"`` line is NOT a docstring and is still
    detected). Mirrors tests/sabotage/test_no_arango_naming.py.
    """
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type == tokenize.STRING and (tok.string.startswith('"""') or tok.string.startswith("'''")):
                for ln in range(tok.start[0], tok.end[0] + 1):
                    lines.add(ln)
    except (tokenize.TokenError, IndentationError, UnicodeDecodeError):
        pass
    return lines


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


def find_import_violations(file_path: Path, forbidden_imports: tuple[str, ...] | list[str]) -> list[tuple[int, str]]:
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
@pytest.mark.slow
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


@pytest.mark.code_smell
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


@pytest.mark.code_smell
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


@pytest.mark.code_smell
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


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_essentia_imports_outside_backend():
    """Test 5: Ensure Essentia is only imported in its two permitted components.

    Essentia is no longer the ML inference backend — it is a thin library used for:
    - Audio loading (MonoLoader): audio/ml_audio_comp.py
    - Mel spectrogram preprocessing: audio/ml_preprocess_comp.py

    All other code must remain essentia-free. The ML inference backend is ONNX.
    """
    violations = []
    # The only two files permitted to import essentia
    allowed_files = {
        NOMARR_DIR / "components" / "ml" / "audio" / "ml_audio_comp.py",
        NOMARR_DIR / "components" / "ml" / "audio" / "ml_preprocess_comp.py",
    }

    for py_file in find_python_files(NOMARR_DIR):
        if "test" in py_file.parts or py_file in allowed_files:
            continue

        try:
            with open(py_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    stripped = line.strip()

                    if not stripped or stripped.startswith("#"):
                        continue

                    if re.match(r"^(import\s+essentia|from\s+essentia)", stripped):
                        rel_path = py_file.relative_to(PROJECT_ROOT)
                        violations.append(f"  {rel_path}:{line_num}: {line.rstrip()}")

        except Exception as e:
            pytest.fail(f"Failed to read {py_file}: {e}")

    if violations:
        msg = (
            "Found Essentia imports outside the two permitted components.\n\n"
            "Essentia is only allowed in:\n"
            "  - components/ml/audio/ml_audio_comp.py  (MonoLoader — audio loading)\n"
            "  - components/ml/audio/ml_preprocess_comp.py  (mel spectrogram preprocessing)\n\n"
            "The ML inference backend is ONNX. Essentia is NOT the inference layer.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


# === Additional helper tests for architecture validation ===


@pytest.mark.code_smell
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


@pytest.mark.code_smell
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


@pytest.mark.code_smell
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


@pytest.mark.code_smell
@pytest.mark.slow
def test_higher_layers_do_not_import_persistence_collection_or_accessor_internals():
    """Test: Ensure higher layers use the `Database` facade, not persistence internals.

    Components, services, and workflows may depend on `Database`, but they must not
    import collection/accessor implementation modules directly. This keeps
    field-first compatibility shims and collection wrappers internal to
    `nomarr.persistence`.
    """
    forbidden_imports = [
        "nomarr.persistence.collections_base",
        "nomarr.persistence.accessors",
    ]
    violations = []

    for layer_name in ("components", "services", "workflows"):
        layer_dir = NOMARR_DIR / layer_name
        for py_file in find_python_files(layer_dir, exclude_dirs={"__pycache__", ".pytest_cache"}):
            file_violations = find_import_violations(py_file, forbidden_imports)
            if file_violations:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                for line_num, line in file_violations:
                    violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found higher-layer imports of persistence collection/accessor internals.\n"
            "Components, services, and workflows must import `Database` from `nomarr.persistence.db`\n"
            "instead of `nomarr.persistence.collections_base` or `nomarr.persistence.accessors`.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


#: ADR-046: the complete set of persistence implementation internal namespaces
#: that higher layers (components, services, workflows) must not import. The
#: public `nomarr.persistence.db` facade is intentionally NOT listed here - it
#: remains the sanctioned boundary through which higher layers reach the intent
#: facades (`db.library`, `db.app`, `db.ml`). `collections_base` and `accessors`
#: are covered by a separate dedicated scan (the collection/accessor internal
#: ban is preserved independently).
_PERSISTENCE_INTERNAL_NAMESPACES = (
    "nomarr.persistence.database",
    "nomarr.persistence.sql",
    "nomarr.persistence.mappers",
    "nomarr.persistence.models",
    "nomarr.persistence.pg_engine",
    "nomarr.persistence.api",
    "nomarr.persistence.exceptions",
)


@pytest.mark.code_smell
@pytest.mark.slow
def test_higher_layers_do_not_import_persistence_internal_namespaces():
    """Ensure higher layers cross persistence through the public `Database` facade.

    ADR-046 makes `db.library`, `db.app`, and `db.ml` the supported caller
    boundary via the public `nomarr.persistence.db` facade. Every persistence
    implementation internal namespace remains private and forbidden to
    components, services, and workflows: Tier-2 repositories
    (`nomarr.persistence.database`), Tier-1 SQL (`nomarr.persistence.sql`),
    mappers, models, pg_engine, the `nomarr.persistence.api` implementation
    modules, and persistence exceptions.

    A narrow bootstrap seam is allowlisted because schema setup intentionally
    works below the normal caller boundary.
    """
    forbidden_imports = list(_PERSISTENCE_INTERNAL_NAMESPACES)
    violations = []

    for layer_name in ("components", "services", "workflows"):
        layer_dir = NOMARR_DIR / layer_name
        for py_file in find_python_files(layer_dir, exclude_dirs={"__pycache__", ".pytest_cache"}):
            if py_file in PERSISTENCE_TIER_BOOTSTRAP_ALLOWLIST:
                continue
            file_violations = find_import_violations(py_file, forbidden_imports)
            if file_violations:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                for line_num, line in file_violations:
                    violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found higher-layer imports of persistence internal namespaces.\n"
            "Components, services, and workflows must cross the persistence boundary\n"
            "through `Database` and its Tier 3 intent facades (`db.library`, `db.app`, `db.ml`).\n"
            "Do not import " + ", ".join(_PERSISTENCE_INTERNAL_NAMESPACES) + "\n"
            "outside persistence-local code.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


@pytest.mark.code_smell
@pytest.mark.slow
def test_higher_layers_do_not_import_persistence_tier1_sql():
    """Explicit Tier-1 SQL prohibition for higher layers (ADR-046).

    Tier-1 SQL primitives (`nomarr.persistence.sql`) are implementation
    internals and remain forbidden to components, services, and workflows,
    which must use the intent facades instead. Kept as a dedicated scan so the
    Tier-1 ban stays explicit rather than only implied by the broad internal
    inventory.
    """
    forbidden_imports = [
        "nomarr.persistence.sql",
    ]
    violations = []

    for layer_name in ("components", "services", "workflows"):
        layer_dir = NOMARR_DIR / layer_name
        for py_file in find_python_files(layer_dir, exclude_dirs={"__pycache__", ".pytest_cache"}):
            if py_file in PERSISTENCE_TIER_BOOTSTRAP_ALLOWLIST:
                continue
            file_violations = find_import_violations(py_file, forbidden_imports)
            if file_violations:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                for line_num, line in file_violations:
                    violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found higher-layer imports of Tier-1 SQL primitives.\n"
            "Components, services, and workflows must cross the persistence boundary\n"
            "through `Database` and its Tier 3 intent facades (`db.library`, `db.app`, `db.ml`).\n"
            "Do not import `nomarr.persistence.sql` directly\n"
            "outside persistence-local code.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


@pytest.mark.code_smell
@pytest.mark.slow
def test_interfaces_and_helpers_do_not_import_persistence():
    """Interfaces and helpers must have NO `nomarr.persistence` imports at all.

    ADR-046 bars interfaces and helpers from persistence entirely (they are the
    only layers with a complete persistence ban): no public facade import, no
    internal import. This complements the import-linter contract and gives
    line-level failures in pytest.
    """
    forbidden_imports = [
        "nomarr.persistence",
    ]
    violations = []

    for layer_name in ("interfaces", "helpers"):
        layer_dir = NOMARR_DIR / layer_name
        if not layer_dir.exists():
            continue
        for py_file in find_python_files(layer_dir, exclude_dirs={"__pycache__", ".pytest_cache"}):
            file_violations = find_import_violations(py_file, forbidden_imports)
            if file_violations:
                rel_path = py_file.relative_to(PROJECT_ROOT)
                for line_num, line in file_violations:
                    violations.append(f"  {rel_path}:{line_num}: {line}")

    if violations:
        msg = (
            "Found interfaces/helpers importing persistence.\n"
            "Interfaces and helpers must have no nomarr.persistence imports at all\n"
            "(ADR-046); only components, services, and workflows may call the public\n"
            "Database facade.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)


@pytest.mark.code_smell
@pytest.mark.slow
def test_persistence_tier_bootstrap_allowlist_stays_empty() -> None:
    """Ensure no lower-tier bootstrap exceptions are reintroduced."""
    assert set() == PERSISTENCE_TIER_BOOTSTRAP_ALLOWLIST


@pytest.mark.code_smell
def test_no_arango_field_names_outside_persistence():
    """Ensure no ArangoDB field names (_id/_key) appear outside persistence.

    Migrated from scripts/check-arango-fields.sh + .arango-field-allowlist.yaml
    (Part E, P1-S1). Scans nomarr/**/*.py excluding nomarr/persistence/** and
    tests/** for word-boundary _id/_key references. Any reference not in the
    embedded ARANGO_FIELD_ALLOWLIST fails; any allowlist entry whose expiry has
    passed also fails (expiry semantics preserved from the original YAML).
    """
    violations = []
    pattern = re.compile(r"\b_id\b|\b_key\b")

    for py_file in find_python_files(NOMARR_DIR):
        # Skip persistence layer - ArangoDB field names are only forbidden
        # outside the persistence layer (the migration boundary).
        if "persistence" in py_file.parts:
            continue

        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        try:
            with open(py_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    if pattern.search(line) and (rel_path, line_num) not in ARANGO_FIELD_ALLOWLIST:
                        violations.append(f"  {rel_path}:{line_num}: {line.strip()}")
        except Exception as e:
            pytest.fail(f"Failed to read {py_file}: {e}")

    # Any allowlist entry past its expiry is also a failure - it must be
    # either fixed in code or the expiry must be renewed deliberately.
    today = date.today()
    expired = [
        f"  {path}:{line} (expired {expiry})"
        for (path, line), expiry in sorted(ARANGO_FIELD_ALLOWLIST.items())
        if date.fromisoformat(expiry) < today
    ]

    if violations:
        msg = (
            "Found ArangoDB field names (_id/_key) outside persistence layer.\n"
            "ArangoDB field naming is forbidden outside nomarr/persistence/ (AR-3).\n"
            "Use PostgreSQL-style field names (id, key) instead.\n\n"
            "Violations:\n" + "\n".join(violations)
        )
        pytest.fail(msg)

    if expired:
        msg = (
            "ArangoDB field-name allowlist entries have expired.\n"
            "Fix the underlying reference in code, then remove the entry from\n"
            "ARANGO_FIELD_ALLOWLIST in tests/test_architecture_qc.py.\n\n"
            "Expired entries:\n" + "\n".join(expired)
        )
        pytest.fail(msg)


# --- P6: Enforcement gates (import-linter, deptry, snapshot determinism, facade guards) ---


def _load_characterization_conftest():
    """Import tests/characterization/conftest.py by file path.

    Loading by module spec (importlib) instead of a package import works
    without a tests/__init__.py (which the repo deliberately omits) and only
    executes the conftest's module-level imports (stdlib + orjson +
    testcontainers + nomarr, all available in dev environments) - no Docker
    fixtures start.
    """
    conftest_path = Path(__file__).parent / "characterization" / "conftest.py"
    spec = importlib.util.spec_from_file_location("characterization_conftest", conftest_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not build a module spec for characterization conftest at {conftest_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError:
        pytest.skip("characterization conftest cannot be imported (nomarr or orjson unavailable)")
    return module


@pytest.mark.code_smell
def test_import_linter_contracts() -> None:
    """import-linter must report zero broken architecture contracts.

    Runs the import-linter CLI against pyproject.toml - the exact invocation
    pre-commit and CI use - and fails if any of the 10 contracts is broken.
    import-linter is a dev dependency, so CI always enforces this gate; the
    test skips locally only when the binary is missing (mirroring the
    Docker-gated suite's skip precedent), never silently passing.
    """
    # Prefer the project's .venv binary: the system python lacks `rich` and is
    # PEP-668-locked, so its `lint-imports`/`import-linter` entry points crash
    # on import. The .venv ships a working import-linter 2.13. Fall back to a
    # PATH-resolved binary for CI environments where the venv is not present.
    venv_lint = PROJECT_ROOT / ".venv" / "bin" / "lint-imports"
    binary = str(venv_lint) if venv_lint.exists() else (shutil.which("lint-imports") or shutil.which("import-linter"))
    if binary is None:
        pytest.skip("import-linter not installed")

    proc = subprocess.run(
        [binary, "--config", "pyproject.toml"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-20:])
        pytest.fail(f"import-linter reported broken contracts (exit {proc.returncode}).\n\nOutput tail:\n{tail}")


@pytest.mark.code_smell
def test_deptry_clean() -> None:
    """deptry must find no unused, missing, or obsolete dependencies.

    Runs deptry from the project root with nomarr as the first-party package,
    matching the CI invocation. The [tool.deptry] config (extend_exclude,
    per_rule_ignores) lives in pyproject.toml, so no flags beyond
    --known-first-party are needed. Skipped locally when the binary is absent;
    deptry is a dev dependency, so CI always enforces this gate.
    """
    binary = shutil.which("deptry")
    if binary is None:
        pytest.skip("deptry not installed")

    proc = subprocess.run(
        [binary, ".", "--known-first-party", "nomarr"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-20:])
        pytest.fail(f"deptry reported dependency issues (exit {proc.returncode}).\n\nOutput tail:\n{tail}")


@pytest.mark.code_smell
def test_deterministic_snapshots() -> None:
    """Characterization snapshots must be byte-deterministic re-serialization.

    The characterization suite (tests/characterization/) serializes facade
    results with serialize_facade_result() from its conftest - orjson with
    sorted keys and 2-space indent over a normalized structure - and stores
    the bytes as baseline JSON files in snapshots/. Determinism of that
    serialization is what makes stored baselines comparable across runs.

    This test loads the suite's own serializer (importlib; no fixtures run)
    and, for every committed snapshot:
      * re-serializes the stored payload twice - the two passes must be
        byte-identical (catches nondeterministic key order, float drift, or
        set/dict iteration leaking into output);
      * asserts the re-serialization equals the committed bytes - a mismatch
        means the current serializer no longer produces what the baselines
        contain (regenerate them);
      * asserts the payload is a flat JSON object - the normalized facade
        result shape.

    Snapshots are only written when Docker runs the characterization suite, so
    the file checks skip when snapshots/ is empty - but the serializer
    round-trip and shape checks run unconditionally, so the test never
    degrades to a pure skip.
    """
    conftest = _load_characterization_conftest()
    serialize = conftest.serialize_facade_result
    snapshot_dir = conftest.SNAPSHOT_DIR

    snapshots = sorted(snapshot_dir.glob("*.json"))
    for snapshot in snapshots:
        with snapshot.open("rb") as fh:
            payload = json.load(fh)
        first = serialize(payload)
        second = serialize(payload)
        assert first == second, (
            f"Snapshot {snapshot.name} re-serializes non-deterministically:\n  pass 1: {first!r}\n  pass 2: {second!r}"
        )
        committed = snapshot.read_bytes()
        assert first == committed, (
            f"Snapshot {snapshot.name} does not match the current canonical "
            f"serialization ({len(first)} bytes re-serialized vs "
            f"{len(committed)} committed). Regenerate it by running the "
            "characterization suite."
        )

    for snapshot in snapshots:
        with snapshot.open("rb") as fh:
            payload = json.load(fh)
        assert isinstance(payload, dict), (
            f"Snapshot {snapshot.name} is a {type(payload).__name__}, expected a normalized facade result object."
        )

    if not snapshots:
        pytest.skip(
            "No committed characterization snapshots in this sandbox (the "
            "Docker-gated suite writes them on first run); the pure-python "
            "serializer determinism checks above still ran."
        )


#: AR-SDR-4 transaction vocabulary that must not reappear in the facade API
#: surface. Caller-managed transactions are not a domain contract: the old
#: `_require_transaction` guard, `FacadeMisuseError`, and `transaction()` were
#: removed from every facade (LibraryDb, AppDb, MlDb and their sub-facades).
#: Repositories may still use short internal transactions (begin_nested +
#: commit); this check is scoped to the persistence API surface only.
_FACADE_TRANSACTION_PATTERNS = (
    re.compile(r"_require_transaction"),
    re.compile(r"FacadeMisuseError"),
    re.compile(r"\.transaction\("),
)


@pytest.mark.code_smell
def test_facade_transaction_contract_absent() -> None:
    """No facade exposes the AR-2 transaction guard vocabulary (AR-SDR-4).

    CONTRACTS.md AR-SDR-4 abolishes caller-managed transactions as a domain
    contract: `_require_transaction`, `FacadeMisuseError`, and `transaction()`
    were removed from every facade. This test checks that statically by
    scanning nomarr/persistence/api/*.py - no nomarr imports, so it runs even
    where the package cannot be imported. Any reappearance of the guard
    vocabulary is an AR-SDR-4 regression. Persistence repositories may keep
    short internal transactions; that is outside this facade-surface check.
    """
    facade_dir = NOMARR_DIR / "persistence" / "api"
    facade_files = sorted(facade_dir.glob("*.py"))
    assert facade_files, "No facade files found under nomarr/persistence/api/"

    violations: list[str] = []
    for path in facade_files:
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(pat.search(line) for pat in _FACADE_TRANSACTION_PATTERNS):
                violations.append(f"  {path.relative_to(PROJECT_ROOT)}:{line_num}: {line.strip()}")

    if violations:
        pytest.fail(
            "Facade exposes the removed AR-2 transaction guard vocabulary "
            "(_require_transaction / FacadeMisuseError / transaction()):\n"
            + "\n".join(violations)
            + "\n\nAR-SDR-4 removes caller-managed transactions from every facade; "
            "callers must invoke write methods directly without a transaction() "
            "context."
        )


#: AR-SDR-1 file-domain elimination surface (songs are the sole canonical entity).
#: Mirrors tests/sabotage/test_no_arango_naming.py::TestNoFileDomainNaming so the
#: pytest-level arch_qc suite enforces the same policy with faster feedback and
#: better line-level messages.
FILE_DOMAIN_SCAN_DIRS = [
    Path("nomarr/persistence"),
    *[Path(f"nomarr/{d}") for d in ("components", "services", "workflows", "interfaces", "helpers")],
]

# Eliminated entity/type/facade/transaction surface (hard-zero after Plans A-D).
_FILE_ENTITY_PATTERNS = (
    re.compile(r"\blibrary_files\b"),
    re.compile(r"\bLibraryFile\b"),
    re.compile(r"\bLibraryFilesDb\b"),
    re.compile(r"\bFileRepository\b"),
    re.compile(r"\bFileTagRepository\b"),
    re.compile(r"\bFileStateRepository\b"),
    re.compile(r"db\.library\.files"),
    re.compile(r"_require_transaction"),
    re.compile(r"FacadeMisuseError"),
    re.compile(r"\.transaction\("),
)

# Eliminated persistence table/entity names. Scanned as code tokens; prose inside
# docstrings/comments is excluded so prose like "current file_tags" does not count.
_FILE_TABLE_PATTERNS = (
    re.compile(r"\bfile_tags\b"),
    re.compile(r"\bfile_states\b"),
    re.compile(r"file_state_assignments"),
)

# EXCEPTION ALLOWLIST (AR-SDR-1/6/7): a matching line is NOT a violation.
# (a) Physical audio-file tag-IO layer. (b) AR-SDR-6 constants seed source.
# (c) Wire/API-contract `file_id` in nomarr/interfaces/ (no bare file_id pattern
#     is scanned here - it is scoped to persistence+domain API surface in P3-S3).
_FILE_ALLOWLIST = (
    re.compile(r"file_tags_io_wf"),
    re.compile(r"write_file_tags_wf"),
    re.compile(r"read_file_tags_workflow"),
    re.compile(r"remove_file_tags_workflow"),
    re.compile(r"write_file_tags_workflow"),
    re.compile(r"\bread_file_tags\b"),
    re.compile(r"\bremove_file_tags\b"),
    re.compile(r"\bwrite_file_tags\b"),
    re.compile(r"file_write_comp"),
    re.compile(r"\bTagWriter\b"),
    re.compile(r"\bsafe_write\b"),
    re.compile(r"file_states import"),
    re.compile(r"pipeline_states import"),
)


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_file_domain_naming_in_persistence_surface() -> None:
    """No file-domain persistence/domain vocabulary outside the AR-SDR-1/6/7 allowlist.

    Songs are the sole canonical library entity. The eliminated file-domain
    entity/type/facade/transaction surface and the persistence table/entity
    names (`file_tags`, `file_states`, `file_state_assignments`) must not
    reappear in `nomarr/persistence/` or the non-persistence layers, except in
    the physical audio-file tag-IO layer, the AR-SDR-6 constants seed source, and
    the wire/API-contract `file_id` in interfaces. Physical-path terms
    (`file_path`, scanner/path components, `library_folders`, scan columns,
    `songs.path`) are intentionally NOT scanned here - they are
    physical-filesystem terminology per AR-SDR-1.
    """
    violations: list[tuple[str, int, str]] = []
    project_root = PROJECT_ROOT

    def scan(pattern: re.Pattern[str], exclude_docstrings: bool = False) -> None:
        for rel_dir in FILE_DOMAIN_SCAN_DIRS:
            dir_path = project_root / rel_dir
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                doc_lines = _docstring_lines(content) if exclude_docstrings else set()
                rel_path = py_file.relative_to(project_root).as_posix()
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if line.lstrip().startswith("#"):
                        continue
                    if exclude_docstrings and line_num in doc_lines:
                        continue
                    if pattern.search(line) and not any(allow.search(line) for allow in _FILE_ALLOWLIST):
                        violations.append((rel_path, line_num, line.strip()))

    for pattern in _FILE_ENTITY_PATTERNS:
        scan(pattern)
    for pattern in _FILE_TABLE_PATTERNS:
        scan(pattern, exclude_docstrings=True)

    if violations:
        unique = sorted(set(violations))
        report = "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in unique[:20])
        if len(unique) > 20:
            report += f"\n  ... and {len(unique) - 20} more"
        pytest.fail(
            "AR-SDR-1 violation: file-domain persistence/domain vocabulary found "
            "(songs are the sole canonical entity).\n" + report
        )


# ── Worker-claims storage-mechanics ban (Phase 3) ─────────────────────────────
# The worker_claims intent facade (TASK-worker-claims-intent-facade-A-correction)
# requires that no storage mechanics cross the persistence boundary: the raw row
# TypedDict (WorkerClaimRow), dead legacy claim method names, the worker_claims
# table name, encoded claim keys, and claim JSON-payload access
# (``claim.get("file_id")``) are all persistence-internal. These patterns must not
# appear in any non-persistence nomarr/ code. ``release_claim`` / ``claim_file`` are
# intentionally excluded as bare identifiers here because they remain legitimate
# component-level thin helpers (ADR-046) that wrap the facade; they are banned only
# as attribute calls (see tests/sabotage/test_sealed_tag_facade_boundary.py).
_CLAIM_SCAN_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
    Path("nomarr/helpers"),
]

# Names with no legitimate use anywhere: dead legacy claim methods + the raw row
# type + the table name.
_CLAIM_DEAD_IDENTIFIERS = re.compile(
    r"\b(?:"
    r"insert_worker_claim|release_claim_by_song|delete_claims_for_workers"
    r"|delete_claims_for_songs|delete_claims|steal_claim|aggregate_worker_claims"
    r"|count_worker_claims|truncate_worker_claims|claim_song|try_insert_or_steal_claim"
    r"|remove_claim_by_song|WorkerClaimRow|worker_claims"
    r")\b"
)
_CLAIM_KEY_ENCODING = re.compile(r"_claim_key\s*\(|_parse_claim_key\s*\(|f[\"']claim_")
_CLAIM_PAYLOAD_ACCESS = re.compile(r"claim\.get\(|claim\[[\"']file_id[\"']\]")


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_worker_claim_storage_mechanics_outside_persistence() -> None:
    """Worker-claims storage shapes/names must not appear outside persistence.

    CONTRACTS.md forbids any non-persistence code from depending on
    WorkerClaimRow, raw claim dictionaries/payloads, encoded claim keys, the
    worker_claims table name, or a public insert/release/steal compatibility
    alias. Prose inside docstrings is excluded (it documents the boundary).
    """
    violations: list[tuple[str, int, str]] = []
    patterns = (
        ("dead-identifier", _CLAIM_DEAD_IDENTIFIERS),
        ("claim-key-encoding", _CLAIM_KEY_ENCODING),
        ("claim-payload-access", _CLAIM_PAYLOAD_ACCESS),
    )
    for rel_dir in _CLAIM_SCAN_DIRS:
        dir_path = PROJECT_ROOT / rel_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            doc_lines = _docstring_lines(content)
            rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
            for line_num, line in enumerate(content.splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                if line_num in doc_lines:
                    continue
                for _label, pattern in patterns:
                    if pattern.search(line):
                        violations.append((rel_path, line_num, line.strip()))

    if violations:
        unique = sorted(set(violations))
        report = "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in unique[:20])
        if len(unique) > 20:
            report += f"\n  ... and {len(unique) - 20} more"
        pytest.fail(
            "Worker-claims storage mechanics leaked outside persistence "
            "(WorkerClaimRow, raw claim payload access, encoded claim keys, "
            "worker_claims table name, or dead legacy claim names):\n" + report
        )


# ── Calibration intent-facade boundary (Plan E P3-S1 / P3-S2) ────────────────
# The calibration correction contracts ("final domain signatures", CONTRACTS.md)
# seal the calibration state/history surface to domain values only. The
# persistence-internal calibration modules below must not cross into caller
# code; facade results must not expose the raw JSONB state/history envelopes;
# and callers must address calibration by natural ``(model_id, head_name, label)``
# identity, never by storage PK / ``_id`` / ``_key``.

# Modules that are persistence-internal (ADR-032/040/046, ASR-0013/0014): the
# calibration repository, its mapper, and its row DTOs. The calibration
# state/history DATACLASSES (helpers/dataclasses/calibration_{state,history}_dataclass.py)
# are domain values and are deliberately NOT in this set - they are fine to
# import anywhere.
_CALIBRATION_INTERNAL_MODULES = (
    "nomarr.persistence.database.calibration_repo",
    "nomarr.persistence.mappers.calibration_mapper",
    "nomarr.helpers.dto.calibration_repo_dto",
)

# Non-persistence production layers that must reach calibration only through
# ``db.ml`` / ``db.ml.maintenance`` domain intents.
_CALIBRATION_SCAN_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
    Path("nomarr/helpers"),
]

# The code that actually owns calibration call sites today (calibration
# components, the calibration service, the pipeline service, and the calibration
# workflows). Used for the narrower storage-identity / db-internal-access and
# history-`data`-envelope scans to avoid generic false positives on unrelated
# API/wire ``data`` fields elsewhere.
_CALIBRATION_CALLER_FILES = [
    Path("nomarr/components/ml/calibration"),
    Path("nomarr/services/domain/calibration_svc.py"),
    Path("nomarr/services/infrastructure/pipeline_svc.py"),
    Path("nomarr/workflows/calibration"),
]

# DTO home files that legitimately define the raw storage shapes; excluded from
# the ``state_data`` token scan (they are the definitions, not callers).
_CALIBRATION_DTO_HOME_FILES = {
    PROJECT_ROOT / "nomarr" / "helpers" / "dto" / "calibration_repo_dto.py",
    PROJECT_ROOT / "nomarr" / "helpers" / "dto" / "repo_dto.py",
}

# Raw JSONB calibration envelope vocabulary. ``state_data`` is the
# calibration_states JSONB envelope; the history ``data`` envelope is accessed
# as a dict (``["data"]`` / ``.get("data")``). Bare ``.data`` attribute access is
# intentionally NOT scanned (generic, high false-positive rate).
_CALIBRATION_RAW_ENVELOPE_PATTERNS = (
    re.compile(r"\bstate_data\b"),
    re.compile(r"\[[\"']data[\"']\]"),
    re.compile(r"\.get\([\"']data[\"']\)"),
)

# ArangoDB storage identity tokens and direct DB-internal (Tier-1/Tier-2/
# session/connection) access that must never appear in calibration callers.
_CALIBRATION_LEGACY_ID_PATTERN = re.compile(r"\b_id\b|\b_key\b")
_CALIBRATION_DB_INTERNAL_ACCESS = re.compile(
    r"\._tier1\b|\._tier2\b|\._scoped\b|\.session\b|\.conn\b|db\.execute\b|db\.raw\b"
)

# The final production calibration facade surface (CONTRACTS.md "final domain
# signatures"): 11 routine methods on ``MlDb`` plus the 2 maintenance-only
# truncate methods on ``db.ml.maintenance``. Each caller-bearing method maps to
# the call-site pattern that proves a production caller exists.
_CALIBRATION_FACADE_METHODS_WITH_CALLERS = {
    "get_calibration_state_view": re.compile(r"get_calibration_state_view\("),
    "list_calibration_states": re.compile(r"list_calibration_states\("),
    "list_calibration_states_with_models": re.compile(r"list_calibration_states_with_models\("),
    "replace_calibration_state": re.compile(r"replace_calibration_state\("),
    "remove_calibration_state": re.compile(r"remove_calibration_state\("),
    "add_calibration_history": re.compile(r"add_calibration_history\("),
    "get_latest_calibration_history_snapshot": re.compile(r"get_latest_calibration_history_snapshot\("),
    "remove_calibration_history": re.compile(r"remove_calibration_history\("),
    # Maintenance resets are the only sanctioned truncation routing; requiring
    # the ``maintenance.`` prefix proves callers do not reach the removed
    # routine ``MlDb`` truncate shims.
    "truncate_calibration_states": re.compile(r"maintenance\.truncate_calibration_states\("),
    "truncate_calibration_history": re.compile(r"maintenance\.truncate_calibration_history\("),
}

# Retained public-surface methods with no production caller today (documented
# and allowlisted in deadcode_allowlist.py). They are part of the facade
# contract and asserted present in test_calibration_facade_surface_present, but
# are not required to have a production call site.
_CALIBRATION_RETAINED_PUBLIC_SURFACE = {
    "get_calibration_state",
    "list_calibration_history",
    "count_calibration_history",
}

_CALIBRATION_FACADE_SURFACE = set(_CALIBRATION_FACADE_METHODS_WITH_CALLERS) | _CALIBRATION_RETAINED_PUBLIC_SURFACE

# Superseded raw calibration methods/shims: removed from the facade in Plan C/D
# and must stay absent from both the surface and any production call site.
_CALIBRATION_SUPERSEDED_METHODS = (
    "remove_calibration_history_entries",
    "remove_calibration_history_for_model",
    "list_calibration_history_snapshots",
    "list_all_calibration_states_with_models",
)


def _iter_py_targets(entries: list[Path]) -> Generator[Path, None, None]:
    """Yield .py files for directory entries and single-file entries."""
    for rel in entries:
        path = PROJECT_ROOT / rel
        if path.is_file():
            if path.suffix == ".py":
                yield path
        elif path.exists():
            for py_file in path.rglob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                yield py_file


def _count_args_on_line(line: str, method: str) -> int | None:
    """Return the arg count of ``method(...)`` on one line, or None.

    Returns ``None`` when the method is absent or the call spans multiple lines
    (so no close paren is on this line). Commas at the top paren depth are
    counted as argument separators.
    """
    m = re.search(r"\b" + re.escape(method) + r"\s*\(", line)
    if m is None:
        return None
    after = line[m.end() :]
    depth = 0
    commas = 0
    for idx, ch in enumerate(after):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                body = after[:idx].strip()
                return 0 if not body else commas + 1
            depth -= 1
        elif ch == "," and depth == 0:
            commas += 1
    return None


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_calibration_persistence_internal_imports_above_persistence() -> None:
    """Calibration repo/mapper/row-DTO modules never imported outside persistence.

    ADR-032/040/046 + ASR-0013/0014 make the calibration repository
    (``nomarr.persistence.database.calibration_repo``), its mapper
    (``nomarr.persistence.mappers.calibration_mapper``), and its row DTOs
    (``nomarr.helpers.dto.calibration_repo_dto``) persistence-internal. Caller
    code above persistence must reach calibration through ``db.ml`` /
    ``db.ml.maintenance`` with domain values (``CalibrationState`` /
    ``CalibrationHistorySnapshot``), which are domain helpers and may be imported
    freely.
    """
    violations: list[tuple[str, int, str]] = []
    for py_file in _iter_py_targets(list(_CALIBRATION_SCAN_DIRS)):
        for line_num, line in find_import_violations(py_file, list(_CALIBRATION_INTERNAL_MODULES)):
            violations.append((py_file.relative_to(PROJECT_ROOT).as_posix(), line_num, line))

    if violations:
        report = "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in sorted(set(violations))[:20])
        if len(violations) > 20:
            report += f"\n  ... and {len(violations) - 20} more"
        pytest.fail(
            "Calibration persistence internals (repository, mapper, row DTOs) "
            "are ADR-032/040/046-internal and must not be imported outside "
            "nomarr/persistence/. Callers go through db.ml / db.ml.maintenance "
            "with domain values.\n" + report
        )


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_calibration_raw_envelope_outside_persistence() -> None:
    """Raw JSONB calibration envelope vocabulary never appears in caller code.

    ``state_data`` (the calibration_states JSONB envelope) is scanned across all
    non-persistence production code (docstrings/comments and the DTO home files
    are excluded). The history ``data`` dict envelope (``["data"]`` /
    ``.get("data")``) is scanned across calibration caller code. Facade results
    are domain values with named fields; caller code must never index them as
    raw storage envelopes. Plan D verified zero such usage - this codifies it.
    """
    violations: list[tuple[str, int, str]] = []

    # state_data token: full non-persistence production surface.
    for py_file in _iter_py_targets(list(_CALIBRATION_SCAN_DIRS)):
        if py_file in _CALIBRATION_DTO_HOME_FILES:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(content)
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or line_num in doc_lines:
                continue
            if _CALIBRATION_RAW_ENVELOPE_PATTERNS[0].search(line):
                violations.append((rel_path, line_num, line.strip()))

    # history `data` dict envelope: calibration caller code only.
    for py_file in _iter_py_targets(_CALIBRATION_CALLER_FILES):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(content)
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or line_num in doc_lines:
                continue
            for pat in _CALIBRATION_RAW_ENVELOPE_PATTERNS[1:]:
                if pat.search(line):
                    violations.append((rel_path, line_num, line.strip()))
                    break

    if violations:
        report = "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in sorted(set(violations))[:20])
        if len(violations) > 20:
            report += f"\n  ... and {len(violations) - 20} more"
        pytest.fail(
            "Raw calibration JSONB envelope vocabulary leaked outside "
            "persistence: `state_data` and the history `data` dict envelope are "
            "persistence-internal. Facade results are CalibrationState / "
            "CalibrationHistorySnapshot domain values with named fields; do not "
            "index them as raw storage envelopes.\n" + report
        )


@pytest.mark.code_smell
@pytest.mark.slow
def test_no_calibration_storage_identity_or_internal_db_access() -> None:
    """Calibration callers use natural identity; no storage ids or db internals.

    (a) No Arango ``_id``/``_key`` tokens in calibration caller code (storage
    identity must never leak; calibration identity is ``(model_id, head_name,
    label)`` with ``model_id`` the stable string ``RegisteredModel.id``).
    (b) No direct Tier-1/Tier-2/session/connection access into ``db`` internals
    from calibration components/services/workflows - they reach calibration only
    through ``db.ml`` / ``db.ml.maintenance`` domain intents.
    """
    violations: list[tuple[str, int, str]] = []
    for py_file in _iter_py_targets(_CALIBRATION_CALLER_FILES):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(content)
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or line_num in doc_lines:
                continue
            if _CALIBRATION_LEGACY_ID_PATTERN.search(line) or _CALIBRATION_DB_INTERNAL_ACCESS.search(line):
                violations.append((rel_path, line_num, line.strip()))

    if violations:
        report = "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in sorted(set(violations))[:20])
        if len(violations) > 20:
            report += f"\n  ... and {len(violations) - 20} more"
        pytest.fail(
            "Calibration caller code must use natural (model_id, head_name, "
            "label) identity and reach calibration only through db.ml / "
            "db.ml.maintenance. Found storage `_id`/`_key` tokens or direct "
            "Tier-1/Tier-2/session/connection access into db internals.\n" + report
        )


@pytest.mark.code_smell
def test_calibration_facade_surface_present() -> None:
    """The full production calibration facade surface is present on db.ml/maintenance.

    All 11 routine methods (on ``MlDb``) and the 2 maintenance-only truncate
    methods (on ``db.ml.maintenance``) must be defined on the final sealed
    surface in ``nomarr/persistence/api/ml.py``.
    """
    ml_file = PROJECT_ROOT / "nomarr" / "persistence" / "api" / "ml.py"
    content = ml_file.read_text(encoding="utf-8")
    missing = [
        name
        for name in sorted(_CALIBRATION_FACADE_SURFACE)
        if re.search(rf"\bdef\s+{re.escape(name)}\s*\(", content) is None
    ]
    assert not missing, "Production calibration facade methods missing from nomarr/persistence/api/ml.py: " + ", ".join(
        missing
    )


@pytest.mark.code_smell
@pytest.mark.slow
def test_calibration_facade_methods_have_production_callers() -> None:
    """Every caller-bearing calibration facade method has a production caller.

    Callers are scanned over all non-persistence production code (docstring/
    comment prose excluded), so the facade definition itself is never counted.
    The three retained public-surface methods with no caller today
    (get_calibration_state, list_calibration_history, count_calibration_history)
    are documented in _CALIBRATION_RETAINED_PUBLIC_SURFACE and asserted present
    (not required to have a call) by test_calibration_facade_surface_present.
    Additionally, every single-line ``get_calibration_state_view`` call must be
    the canonical 3-arg natural-identity form - the head/label-only 2-arg form is
    not a valid contract.
    """
    caller_hits: dict[str, list[str]] = {name: [] for name in _CALIBRATION_FACADE_METHODS_WITH_CALLERS}
    view_lines: list[tuple[str, int, str]] = []

    for py_file in _iter_py_targets(list(_CALIBRATION_SCAN_DIRS)):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(content)
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or line_num in doc_lines:
                continue
            if _CALIBRATION_FACADE_METHODS_WITH_CALLERS["get_calibration_state_view"].search(line):
                view_lines.append((rel_path, line_num, line.strip()))
            for name, pattern in _CALIBRATION_FACADE_METHODS_WITH_CALLERS.items():
                if pattern.search(line):
                    caller_hits[name].append(f"{rel_path}:{line_num}")

    missing = sorted(name for name, hits in caller_hits.items() if not hits)
    assert not missing, "Production calibration facade methods have no production caller: " + ", ".join(missing)

    # Canonical 3-arg natural-identity form for get_calibration_state_view.
    bad_view = [
        f"{p}:{ln}: {txt}"
        for p, ln, txt in view_lines
        if _count_args_on_line(txt, "get_calibration_state_view") not in (None, 3)
    ]
    assert not bad_view, (
        "get_calibration_state_view calls must use the canonical 3-arg "
        "(model_id, head_name, label) natural identity; the head/label-only "
        "2-arg form is not a valid contract.\n" + "\n".join(bad_view)
    )


@pytest.mark.code_smell
@pytest.mark.slow
def test_calibration_superseded_methods_have_no_surface_or_callers() -> None:
    """Superseded raw calibration methods/shims have no surface or callers.

    remove_calibration_history_entries, remove_calibration_history_for_model,
    list_calibration_history_snapshots, and list_all_calibration_states_with_models
    were removed in Plan C/D and must stay absent from the facade surface and from
    every production call site. Calibration table resets route exclusively through
    ``db.ml.maintenance`` (the deprecated routine ``MlDb`` truncate shims were
    removed in Phase 1), so every production truncate call must carry the
    ``maintenance.`` prefix.
    """
    ml_file = PROJECT_ROOT / "nomarr" / "persistence" / "api" / "ml.py"
    content = ml_file.read_text(encoding="utf-8")

    surface_present = [
        name for name in _CALIBRATION_SUPERSEDED_METHODS if re.search(rf"\bdef\s+{re.escape(name)}\s*\(", content)
    ]
    assert not surface_present, (
        "Superseded raw calibration methods reappeared on the facade surface "
        "in nomarr/persistence/api/ml.py: " + ", ".join(surface_present)
    )

    # The routine MlDb truncate shims are gone: truncation is maintenance-only,
    # so there is exactly one `def` for each (on MlMaintenanceDb).
    for name in ("truncate_calibration_states", "truncate_calibration_history"):
        defs = re.findall(rf"\bdef\s+{re.escape(name)}\s*\(", content)
        assert len(defs) == 1, (
            f"Expected exactly one maintenance-only `def {name}` (on "
            f"MlMaintenanceDb); found {len(defs)}. The routine MlDb truncate "
            "shim must remain removed."
        )

    superseded_hits: list[str] = []
    truncate_non_maintenance: list[str] = []
    superseded_pat = re.compile(
        r"(?:remove_calibration_history_entries|remove_calibration_history_for_model|list_calibration_history_snapshots|list_all_calibration_states_with_models)\s*\("
    )
    truncate_pat = re.compile(r"\.(truncate_calibration_states|truncate_calibration_history)\s*\(")

    for py_file in _iter_py_targets(list(_CALIBRATION_SCAN_DIRS)):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(content)
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or line_num in doc_lines:
                continue
            if superseded_pat.search(line):
                superseded_hits.append(f"{rel_path}:{line_num}: {line.strip()}")
            if truncate_pat.search(line) and "maintenance." not in line:
                truncate_non_maintenance.append(f"{rel_path}:{line_num}: {line.strip()}")

    assert not superseded_hits, (
        "Superseded raw calibration methods have production call sites. "
        "Natural-identity retention (remove_calibration_history keep_count) and "
        "the maintenance truncate pair are the sanctioned mechanisms.\n" + "\n".join(superseded_hits)
    )
    assert not truncate_non_maintenance, (
        "Calibration table truncation must route exclusively through "
        "db.ml.maintenance; the deprecated routine MlDb truncate shims are "
        "removed. Found a non-maintenance truncate call.\n" + "\n".join(truncate_non_maintenance)
    )
