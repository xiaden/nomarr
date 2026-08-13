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
    ("nomarr/components/ml/calibration/ml_calibration_state_comp.py", 94): "2026-10-15",
    ("nomarr/components/ml/calibration/ml_calibration_state_comp.py", 96): "2026-10-15",
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


@pytest.mark.code_smell
@pytest.mark.slow
def test_higher_layers_do_not_import_persistence_tier1_or_tier2_internals():
    """Ensure higher layers cross persistence through `Database`, not lower tiers.

    ADR-031 makes `db.library`, `db.app`, and `db.ml` the supported caller
    boundary. Tier 2 (`nomarr.persistence.database`) and Tier 1
    (`nomarr.persistence.database`) remain private implementation layers.

    A narrow bootstrap seam is allowlisted because schema setup intentionally
    works below the normal caller boundary.
    """
    forbidden_imports = [
        "nomarr.persistence.database",
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
            "Found higher-layer imports of Tier 1/Tier 2 persistence internals.\n"
            "Components, services, and workflows must cross the persistence boundary\n"
            "through `Database` and its Tier 3 intent facades (`db.library`, `db.app`, `db.ml`).\n"
            "Do not import `nomarr.persistence.database` directly\n"
            "outside persistence-local code.\n\n"
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
    `navidrome_tracks.file_path`) are intentionally NOT scanned here - they are
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
