"""Sabotage checks: meta-backed intent facade boundary (P4-S3).

Enforces the hard-cut semantic ``AppDb`` surface from
``TASK-meta-intent-facades-A-hard-cut``:

- No higher-layer code (components, services, workflows, interfaces), script,
  or non-repository test references the storage-level meta surface: ``Meta`` /
  ``MetaRow`` storage types, ``AppRepository`` raw meta primitives
  (``get_meta`` / ``upsert_meta`` / ``delete_meta`` /
   ``list_meta_keys_by_prefix``, including their private ``_`` forms), the
   deleted ``update_config_option`` legacy bridge, and the physical storage key
   encodings (``ml_model_vram:`` / ``capacity_estimate:``; ``config_`` is part of
   the pinned ``ConfigOption.key`` contract and is scanned only in production
   caller/script code, with config_svc.py's read-side strip exempted).
- Callers above persistence address the meta-backed domains through the
  semantic intents (``set_config_option(key, value)``, schema version,
  credentials, calibration bookkeeping, VRAM limits, capacity estimates, GPU
  snapshots, worker state) — never through storage types, repositories, keys,
  or payloads.
- The forbidden ``AppDb`` surface is additionally pinned at runtime by the
  surface-guard tests in ``test_meta_facade_semantics.py``; the attribute-level
  check here mirrors it.

ALLOWED (never scanned): ``nomarr/persistence/**`` (implementation owns the
storage encodings internally), the internal repository row-contract test
``test_app_repo.py``, the ``repo_dto`` TypedDict contract test
``test_repo_dto.py`` (``MetaRow`` is a persistence-internal DTO), the
surface-guard tests in ``test_meta_facade_semantics.py`` (they intentionally
name the forbidden surface to assert its absence), and this sabotage module
itself (its search patterns name the forbidden symbols). Every other
``nomarr/**``, ``scripts/**``, and ``tests/**`` file is forbidden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Directories that must go through the semantic facade (not the meta storage).
CALLER_DIRS = [
    Path("nomarr/components"),
    Path("nomarr/services"),
    Path("nomarr/workflows"),
    Path("nomarr/interfaces"),
]

# Files that legitimately reference the forbidden symbols and are exempt.
# Paths are relative to PROJECT_ROOT.
ALLOWED_REL_PATHS = {
    # Internal storage-row contract test (repository-internal names allowed).
    Path("tests/unit/persistence/database/test_app_repo.py"),
    # repo_dto TypedDict contract test — MetaRow is a persistence-internal DTO.
    Path("tests/unit/helpers/dto/test_repo_dto.py"),
    # Surface-guard absence tests — intentionally name the forbidden surface to
    # assert it does NOT exist on the facade.
    Path("tests/unit/persistence/api/test_meta_facade_semantics.py"),
}

# The raw meta primitives (public and private forms) as attribute calls.
META_PRIMITIVE_PATTERN = re.compile(r"\._?(?:get_meta|upsert_meta|delete_meta|list_meta_keys_by_prefix)\(")

# The deleted storage-payload write bridge.
LEGACY_BRIDGE_PATTERN = re.compile(r"\.update_config_option\(")

# Storage types that must never cross the persistence boundary.
STORAGE_TYPE_PATTERN = re.compile(r"\bMetaRow\b")

# Physical storage key encodings used to address the meta table, as quoted
# literals. Type annotations (`capacity_estimate: CapacityEstimate`) and domain
# attribute names are deliberately NOT matched — only quoted key prefixes leak.
STORAGE_PREFIX_PATTERN = re.compile(r"['\"](?:ml_model_vram:|capacity_estimate:)")

# Physical user-configuration storage prefix (config-key encoding). The
# ``config_`` prefix is PART of the pinned ``ConfigOption.key`` contract
# (test_meta_facade_semantics: ``option.key == "config_scan_interval"``), so it
# legitimately appears in facade-level tests and in config_svc's sanctioned
# read-side strip (see CONFIG_PREFIX_ALLOWLIST below). It is therefore scanned
# only in production caller code and scripts, and not in tests.
CONFIG_PREFIX_PATTERN = re.compile(r"['\"]config_")

# The renamed clear-result field. ``meta_keys_cleared`` was renamed to
# ``bookkeeping_values_cleared`` (Plan A, user-approved); reintroduction of the
# old storage-flavored name must be caught.
META_KEYS_CLEARED_PATTERN = re.compile(r"meta_keys_cleared")

# config_svc.py is the one sanctioned read-side exception that renames a
# returned ``ConfigOption.key`` (which carries the full storage key per the
# pinned contract) back to a bare configuration key via ``meta_key[7:]``. This
# is the documented ConfigOption.key contract, not prefix leakage.
CONFIG_PREFIX_ALLOWLIST = {Path("nomarr/services/infrastructure/config_svc.py")}

# Direct import of the storage repository layer from caller code.
STORAGE_IMPORT_PATTERN = re.compile(
    r"^\s*from\s+nomarr\.persistence\.database|^\s*import\s+nomarr\.persistence\.database"
)

# The sabotage module's own directory is exempt from the tests/ scan.
SABOTAGE_DIR = Path("tests/sabotage")


def _scan(root: Path, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Scan ``*.py`` files under *root* for *pattern* (relative to PROJECT_ROOT)."""
    dir_path = PROJECT_ROOT / root
    if not dir_path.exists():
        return []
    violations: list[tuple[str, int, str]] = []
    for py_file in dir_path.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        if rel in ALLOWED_REL_PATHS:
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                violations.append((str(rel), line_num, line.strip()))
    return violations


def _scan_tests(pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Scan tests/** (excluding this sabotage module) for *pattern*."""
    dir_path = PROJECT_ROOT / "tests"
    violations: list[tuple[str, int, str]] = []
    for py_file in dir_path.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(PROJECT_ROOT)
        if rel in ALLOWED_REL_PATHS or rel.parts[:2] == (SABOTAGE_DIR.parts[0], SABOTAGE_DIR.parts[1]):
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                violations.append((str(rel), line_num, line.strip()))
    return violations


def _format(violations: list[tuple[str, int, str]], limit: int = 20) -> str:
    if not violations:
        return "No violations found."
    lines = [f"Found {len(violations)} violation(s):"]
    for filepath, line_num, line_text in violations[:limit]:
        lines.append(f"  {filepath}:{line_num}: {line_text}")
    if len(violations) > limit:
        lines.append(f"  ... and {len(violations) - limit} more")
    return "\n".join(lines)


@pytest.mark.sabotage_check
class TestNoMetaPrimitivesOrBridge:
    """Raw meta primitives and the legacy bridge never reappear as calls."""

    def test_no_meta_primitive_or_bridge_calls_above_persistence(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, META_PRIMITIVE_PATTERN))
            violations.extend(_scan(directory, LEGACY_BRIDGE_PATTERN))
        assert len(violations) == 0, (
            "Components/services/workflows/interfaces must address the meta-backed "
            "domains through semantic intents, never by calling the raw meta "
            "primitives (get_meta/upsert_meta/delete_meta/list_meta_keys_by_prefix) "
            "or the deleted update_config_option bridge.\n"
            f"{_format(violations)}"
        )

    def test_no_meta_primitive_or_bridge_calls_in_scripts(self) -> None:
        violations = _scan(Path("scripts"), META_PRIMITIVE_PATTERN)
        violations.extend(_scan(Path("scripts"), LEGACY_BRIDGE_PATTERN))
        assert len(violations) == 0, (
            "Scripts must use the semantic AppDb surface, never the raw meta "
            "primitives or the deleted update_config_option bridge.\n"
            f"{_format(violations)}"
        )

    def test_no_meta_primitive_or_bridge_calls_in_other_tests(self) -> None:
        violations = _scan_tests(META_PRIMITIVE_PATTERN)
        violations.extend(_scan_tests(LEGACY_BRIDGE_PATTERN))
        assert len(violations) == 0, (
            "Non-repository tests must pin the semantic AppDb surface; raw meta "
            "primitives and the update_config_option bridge are repository-internal "
            "(allowed only in test_app_repo.py / the sabotage surface-guard files).\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoMetaStorageTypeLeak:
    """The MetaRow storage type never crosses the persistence boundary."""

    def test_no_metarow_in_caller_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, STORAGE_TYPE_PATTERN))
        violations.extend(_scan(Path("scripts"), STORAGE_TYPE_PATTERN))
        assert len(violations) == 0, (
            "MetaRow is a persistence-internal storage DTO; higher layers must not "
            "reference it.\n"
            f"{_format(violations)}"
        )

    def test_no_metarow_in_other_tests(self) -> None:
        violations = _scan_tests(STORAGE_TYPE_PATTERN)
        assert len(violations) == 0, (
            "MetaRow may only be referenced by repository-internal tests "
            "(test_app_repo.py, test_repo_dto.py) — not by facade-level tests.\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoStoragePrefixLeak:
    """Physical meta key prefixes never leak into higher-layer code."""

    def test_no_storage_prefixes_in_caller_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, STORAGE_PREFIX_PATTERN))
        assert len(violations) == 0, (
            "Storage key encodings (ml_model_vram:, capacity_estimate:) are "
            "persistence-owned; callers use the semantic model/capacity intents.\n"
            f"{_format(violations)}"
        )

    def test_no_config_storage_prefix_in_production_or_scripts(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, CONFIG_PREFIX_PATTERN))
        violations.extend(_scan(Path("scripts"), CONFIG_PREFIX_PATTERN))
        violations = [v for v in violations if Path(v[0]) not in CONFIG_PREFIX_ALLOWLIST]
        assert len(violations) == 0, (
            "The physical config_ storage prefix is persistence-owned; callers "
            "address user configuration by its bare configuration key. The sole "
            "exception is config_svc.py's documented read-side strip of the "
            "pinned ConfigOption.key contract."
            f"\n{_format(violations)}"
        )

    def test_no_storage_prefixes_in_other_tests(self) -> None:
        # Only the fully-internalized VRAM/capacity prefixes are scanned here.
        # The config_ prefix is part of the pinned ConfigOption.key contract and
        # legitimately appears in facade-level tests (see module docstring).
        violations = _scan_tests(STORAGE_PREFIX_PATTERN)
        assert len(violations) == 0, (
            f"Facade-level tests must not pin physical storage prefixes.\n{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoStaleClearResultField:
    """The renamed clear-result field never reappears under its old name."""

    def test_no_meta_keys_cleared_in_caller_code(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, META_KEYS_CLEARED_PATTERN))
        violations.extend(_scan(Path("scripts"), META_KEYS_CLEARED_PATTERN))
        assert len(violations) == 0, (
            "meta_keys_cleared was renamed to bookkeeping_values_cleared (Plan A); "
            "callers must use the new field name.\n"
            f"{_format(violations)}"
        )

    def test_no_meta_keys_cleared_in_other_tests(self) -> None:
        violations = _scan_tests(META_KEYS_CLEARED_PATTERN)
        assert len(violations) == 0, (
            "Facade-level tests must assert bookkeeping_values_cleared, never the old "
            f"meta_keys_cleared field name.\n{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestNoDirectStorageImports:
    """Callers above persistence never import the storage repository layer."""

    def test_components_services_workflows_interfaces_do_not_import_storage(self) -> None:
        violations: list[tuple[str, int, str]] = []
        for directory in CALLER_DIRS:
            violations.extend(_scan(directory, STORAGE_IMPORT_PATTERN))
        assert len(violations) == 0, (
            "Components/services/workflows/interfaces must address the meta-backed "
            "domains through the semantic facade, not by importing "
            "nomarr.persistence.database repos/tables directly.\n"
            f"{_format(violations)}"
        )


@pytest.mark.sabotage_check
class TestAppDbExposesNoGenericMetaSurface:
    """AppDb exposes no generic meta/primitives/prefix/payload surface."""

    def test_app_db_has_no_generic_meta_attributes(self) -> None:
        from nomarr.persistence.api.application import AppDb

        forbidden = (
            "get_meta",
            "upsert_meta",
            "delete_meta",
            "list_meta_keys_by_prefix",
            "update_config_option",
        )
        exposed = [name for name in forbidden if hasattr(AppDb, name)]
        assert not exposed, (
            "AppDb must not expose generic meta primitives or the legacy "
            f"update_config_option bridge (P4-S1/P4-S2). Exposed: {exposed}"
        )
