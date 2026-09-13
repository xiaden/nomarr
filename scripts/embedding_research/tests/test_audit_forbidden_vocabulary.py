"""Focused executable-reference deletion proof for the geometry hard cut.

This module is the machine-readable deletion boundary from Plan R. It builds the
deletion map of retired modules, symbols, tables, columns, vocabulary roots, and
filesystem artifacts, then scans the executable surfaces -- package Python,
configuration, the CLI registries, generated report/fixture output, and dynamic
``getattr`` / ``importlib`` string arguments -- and proves ZERO runtime edges
remain to the old ownership/segmentation runtime.

Retired names are assembled from fragments at runtime so this module never itself
carries a substring it forbids. Historical design/plan/log prose is traceability
only and is excluded from the executable scans.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PACKAGE_ROOT.parents[1]
_SELF = Path(__file__).resolve()

_SKIP_DIRS = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})
_SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".db",
        ".duckdb",
        ".npy",
        ".npz",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".whl",
        ".so",
        ".dylib",
        ".dll",
        ".bin",
    }
)
_DYNAMIC_NAMES = frozenset({"getattr", "import_module", "__import__", "attrgetter"})


def _j(*parts: str) -> str:
    """Join fragments so this module never stores a forbidden substring literally."""
    return "".join(parts)


_OWN = _j("cat", "alog")
_SV = _j("search", "_", "view")
_SV_COMMAND = _j("search", "-", "view")
_ALT = _j("ali", "ases")

#: The two retired CLI verbs, which must reject exactly like any unknown command.
RETIRED_COMMANDS: tuple[str, ...] = (_OWN, _OWN + "-report")

#: Retired module -> replacement module paths (relative to the package root).
RETIRED_MODULES: dict[str, tuple[str, ...]] = {
    _OWN + ".py": ("common/geometry_analysis.py", "db/geometry.py"),
    _OWN + "_storage.py": ("db/geometry.py", "streams/store.py"),
    _OWN + "_identity.py": ("db/identity_persistence.py", "db/geometry.py"),
    _OWN + "_binding.py": ("db/geometry.py",),
    _OWN + "_report.py": ("report/_retrieval.py", "report/_winners.py"),
    "common/" + _OWN + "_analysis.py": ("common/geometry_analysis.py",),
    "db/" + _OWN + "_metadata.py": ("db/analyze_scope.py", "db/provenance.py"),
    "db/segmentation.py": ("helpers/gram_segmentation.py",),
    _SV + "s.py": (),
    "helpers/segmentation.py": ("helpers/gram_segmentation.py",),
    "helpers/binning.py": ("helpers/gram_segmentation.py",),
}

#: Retired symbol -> replacement symbol (``None`` means deleted with no successor).
RETIRED_SYMBOLS: dict[str, str | None] = {
    "run_spherical_segmentation": "derive_temporal_global_from_gram",
    "global_dist": None,
    "perdim_dist": None,
    "DIST_FNS": None,
    "distance_metric_label": None,
    "temporal_segment": None,
    "temporal_segment_with_diagnostics": None,
    "observed_global_medoid_from_observation": "observed_global_medoid_from_gram",
    "observed_global_medoid_unit_vector": "observed_global_medoid_from_gram",
    "select_observed_medoid_source_index": "select_observed_medoid_from_gram",
    "observed_global_medoid": "observed_global_medoid_from_gram",
    "_to_unit_rows": None,
    "_sorted_" + _ALT: None,
    "run_shared_" + _OWN + "_head_analysis": "run_shared_geometry_head_analysis",
    "_collect_segment_membership": None,
    "_pool_segment_heads": None,
    "SearchViewRecord": None,
    "materialize_" + _SV: None,
    "record_" + _SV: None,
}

RETIRED_TABLES: tuple[str, ...] = (
    _OWN + "_metadata",
    _OWN + "_song",
    "seg_config",
    "seg_meta",
    "observation_evidence",
)

RETIRED_COLUMNS: tuple[str, ...] = (
    _OWN + "_id",
    _OWN + "_fingerprint",
    "view_refs",
)

#: Retired runtime concepts that have no single file/symbol owner.
RETIRED_CONCEPTS: tuple[dict[str, str], ...] = (
    {
        "kind": "engine",
        "identifier": "vector-centroid temporal-global segmentation runtime",
        "replacement": "helpers/gram_segmentation.py",
    },
    {
        "kind": "adapter",
        "identifier": "stream-to-unit-vector observed baseline adapter",
        "replacement": "observed_global_medoid_from_gram",
    },
    {
        "kind": "vocabulary",
        "identifier": _OWN + " identity fields",
        "replacement": (
            "observation_group_sha256/geometry_id/geometry_semantics_version/numerical_profile_digest/"
            "threshold_id/structural_identity/search_representation_id/evaluation_id/"
            "scoring_semantics_version/execution_id"
        ),
    },
    {
        "kind": "compatibility",
        "identifier": _j("ali", "as") + "/" + _j("fall", "back") + "/dual-schema",
        "replacement": "none (refused)",
    },
    {
        "kind": "filesystem_artifact",
        "identifier": "filesystem snapshot/current/view runtime",
        "replacement": "primary DuckDB song_patch_geometry",
    },
)

#: Retired symbol name -> the module that now provides the replacement.
REPLACEMENTS: dict[str, str] = {
    "derive_temporal_global_from_gram": "scripts.embedding_research.helpers.gram_segmentation",
    "derive_all_temporal_global": "scripts.embedding_research.helpers.gram_segmentation",
    "gram_from_stream": "scripts.embedding_research.helpers.gram_segmentation",
    "observed_global_medoid_from_gram": "scripts.embedding_research.helpers.gram_segmentation",
    "select_observed_medoid_from_gram": "scripts.embedding_research.helpers.gram_segmentation",
    "write_geometry": "scripts.embedding_research.db.geometry",
    "read_geometry": "scripts.embedding_research.db.geometry",
    "read_geometry_matrix": "scripts.embedding_research.db.geometry",
    "verify_geometry_binding": "scripts.embedding_research.db.geometry",
    "analyze_all_thresholds": "scripts.embedding_research.common.threshold_analysis",
    "analyze_geometry_corpus": "scripts.embedding_research.common.geometry_analysis",
    "build_geometry_corpus_request": "scripts.embedding_research.common.geometry_analysis",
    "write_geometries_for_current_songs": "scripts.embedding_research.common.geometry_analysis",
    "run_shared_geometry_head_analysis": "scripts.embedding_research.common.head_analysis",
    "medoid_strategy_key_for": "scripts.embedding_research.baseline",
}


def retired_vocabulary() -> tuple[str, ...]:
    """Retired vocabulary roots, assembled from fragments."""
    return (
        _OWN,
        _SV,
        _j("search", " view"),
        _SV_COMMAND,
        _j("current", " selector"),
        _j("current", "_selector"),
        _j("current", "-selector"),
        _j("latest", " selector"),
        _j("latest", "_selector"),
        _j("latest", "-selector"),
        _j("leg", "acy"),
        _j("ali", "as"),
        _j("fall", "back"),
    )


def retired_filesystem_artifacts() -> tuple[str, ...]:
    """Retired on-disk artifact names/paths."""
    return (
        _OWN + "s",
        "current.json",
        "views/",
        "vectors.npy",
        "keys.json",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in _PACKAGE_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _module_stem(relative: str) -> str:
    return relative[:-3].replace("/", ".")


def _retired_module_stems() -> frozenset[str]:
    return frozenset(_module_stem(relative) for relative in RETIRED_MODULES)


def _import_is_retired(module: str, stems: frozenset[str]) -> bool:
    if not module:
        return False
    normalized = module.replace("scripts.embedding_research.", "", 1).lstrip(".")
    return any(normalized == stem or normalized.endswith("." + stem) for stem in stems)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _terminal(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1] if dotted else ""


def _string_constants(tree: ast.AST) -> set[str]:
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _defined_symbol_names() -> set[str]:
    names: set[str] = set()
    for path in _iter_python_files():
        if path == _SELF:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names


def scan_executable_sources() -> dict[str, Any]:
    """AST scan of package Python for retired imports, calls, and dynamic strings."""
    stems = _retired_module_stems()
    symbols = set(RETIRED_SYMBOLS)
    commands = set(RETIRED_COMMANDS)
    scanned: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for path in _iter_python_files():
        relative = path.relative_to(_PACKAGE_ROOT).as_posix()
        if path == _SELF:
            scanned.append(
                {
                    "path": relative,
                    "sha256": _sha256_file(path),
                    "note": "scanner_self_excluded_from_literal_and_call_scan",
                }
            )
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            matches.append({"path": relative, "kind": "parse_error", "detail": str(exc)})
            continue
        scanned.append({"path": relative, "sha256": _sha256_file(path)})
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _import_is_retired(module, stems):
                    matches.append({"path": relative, "line": node.lineno, "kind": "import", "module": module})
                matches.extend(
                    {"path": relative, "line": node.lineno, "kind": "import", "symbol": binding.name}
                    for binding in node.names
                    if binding.name in symbols
                )
            elif isinstance(node, ast.Import):
                matches.extend(
                    {"path": relative, "line": node.lineno, "kind": "import", "module": binding.name}
                    for binding in node.names
                    if _import_is_retired(binding.name, stems)
                )
            elif isinstance(node, ast.Call):
                dotted = _dotted(node.func)
                terminal = _terminal(dotted)
                if terminal in symbols:
                    matches.append({"path": relative, "line": node.lineno, "kind": "call", "symbol": terminal})
                if terminal in _DYNAMIC_NAMES:
                    for argument in node.args:
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                            literal = argument.value
                            if literal in symbols or literal in commands or _import_is_retired(literal, stems):
                                matches.append(
                                    {"path": relative, "line": node.lineno, "kind": "dynamic", "literal": literal}
                                )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literal = node.value
                if literal in symbols or literal in commands or _import_is_retired(literal, stems):
                    matches.append(
                        {"path": relative, "line": node.lineno, "kind": "string_literal", "literal": literal}
                    )
    return {"files": scanned, "matches": matches, "file_count": len(scanned)}


def scan_cli_registries() -> dict[str, Any]:
    """Check every CLI phase/command registry for retired command entries."""
    from scripts.embedding_research import run as run_mod

    retired = set(RETIRED_COMMANDS)
    findings: list[dict[str, Any]] = []
    registries = {
        "CLI_PHASES": tuple(run_mod.CLI_PHASES),
        "CLI_PHASE_RUNNERS": tuple(run_mod.CLI_PHASE_RUNNERS),
        "MAINTENANCE_COMMANDS": tuple(sorted(run_mod.MAINTENANCE_COMMANDS)),
        "AUDIO_PHASES": tuple(sorted(run_mod.AUDIO_PHASES)),
        "DERIVED_PHASES": tuple(sorted(run_mod.DERIVED_PHASES)),
    }
    for name, entries in registries.items():
        findings.extend({"registry": name, "entry": entry} for entry in entries if entry in retired)
    return {"findings": findings, "registries": {name: list(entries) for name, entries in registries.items()}}


def scan_schema() -> dict[str, Any]:
    """Check the sole schema module for retired table/column names."""
    from scripts.embedding_research.db import _schema as schema_mod

    text = Path(schema_mod.__file__).read_text(encoding="utf-8")
    findings: list[dict[str, Any]] = []
    findings.extend({"kind": "table", "name": table} for table in RETIRED_TABLES if table in text)
    findings.extend({"kind": "column", "name": column} for column in RETIRED_COLUMNS if column in text)
    return {"findings": findings}


def generated_output_tokens() -> tuple[str, ...]:
    """Retired identity/file-system tokens that generated output must never emit.

    Generic English words (``leg...`` / ``ali...`` / ``fall...``) are deliberately
    excluded here: the bundled report HTML vendors third-party code that contains
    them incidentally.  Authored source is still covered by the whole-tree lexical
    audit, which forbids those tokens outright.
    """
    return (
        _OWN,
        _SV,
        _j("search", " view"),
        _SV_COMMAND,
        _j("current", " selector"),
        _j("current", "_selector"),
        _j("current", "-selector"),
        _j("latest", " selector"),
        _j("latest", "_selector"),
        _j("latest", "-selector"),
        "view_refs",
        *retired_filesystem_artifacts(),
    )


def scan_generated_text(text: str) -> list[str]:
    """Retired identity vocabulary or filesystem paths present in generated output."""
    lowered = text.lower()
    return sorted({token for token in generated_output_tokens() if token in lowered})


def scan_generated_report_artifacts() -> dict[str, Any]:
    """Scan the checked-in generated report artifacts, when present.

    The canonical evidence copies live under the workspace-relative evidence directory
    (``artifacts/evidence/.../report``); the gitignored runtime output root is only a
    secondary lookup.  Recorded paths are always workspace-relative evidence paths so the
    proof never points outside the repository.
    """
    from scripts.embedding_research.config import REPORT_DIR
    from scripts.embedding_research.tests import _gram_evidence

    evidence_report_dir = _gram_evidence.EVIDENCE_ROOT / "report"
    recorded_root = _REPO_ROOT

    def _recordable(path: Path) -> str:
        try:
            return path.resolve().relative_to(recorded_root).as_posix()
        except ValueError:
            return path.as_posix()

    artifacts: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    for name in ("report.json", "report.html"):
        evidence_path = evidence_report_dir / name
        runtime_path = Path(REPORT_DIR) / name
        path = evidence_path if evidence_path.is_file() else runtime_path
        if not path.is_file():
            continue
        recorded = _recordable(path)
        artifacts.append({"path": recorded, "sha256": _sha256_file(path)})
        hits.extend(
            {"path": recorded, "token": token}
            for token in scan_generated_text(path.read_text(encoding="utf-8", errors="replace"))
        )
    return {"artifacts": artifacts, "hits": hits}


def check_replacement_reachability() -> dict[str, dict[str, Any]]:
    """Every retired surface must have a reachable canonical replacement."""
    result: dict[str, dict[str, Any]] = {}
    for symbol, module_name in REPLACEMENTS.items():
        try:
            module = importlib.import_module(module_name)
            result[symbol] = {"module": module_name, "reachable": hasattr(module, symbol)}
        except Exception as exc:  # pragma: no cover - import failure is a proof failure
            result[symbol] = {"module": module_name, "reachable": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def _head_source_sha256(relative: str) -> str | None:
    """SHA-256 of the retired source as recorded at HEAD, when available."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "show", f"HEAD:scripts/embedding_research/{relative}"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except Exception:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def build_deletion_map(*, include_head_hashes: bool = False) -> list[dict[str, Any]]:
    """Exact machine-readable dispositions for every retired surface."""
    defined = _defined_symbol_names()
    entries: list[dict[str, Any]] = []
    for relative, replacements in RETIRED_MODULES.items():
        entries.append(
            {
                "kind": "module",
                "identifier": relative,
                "disposition": "deleted",
                "exists": (_PACKAGE_ROOT / relative).exists(),
                "replacement_paths": list(replacements),
                "replacement_sha256": {
                    replacement: (
                        _sha256_file(_PACKAGE_ROOT / replacement) if (_PACKAGE_ROOT / replacement).is_file() else None
                    )
                    for replacement in replacements
                },
                "source_sha256": _head_source_sha256(relative) if include_head_hashes else None,
            }
        )
    for symbol, replacement in RETIRED_SYMBOLS.items():
        entries.append(
            {
                "kind": "symbol",
                "identifier": symbol,
                "disposition": "deleted",
                "exists": symbol in defined,
                "replacement": replacement,
            }
        )
    entries.extend(
        {"kind": "table", "identifier": table, "disposition": "deleted", "exists": False} for table in RETIRED_TABLES
    )
    entries.extend(
        {"kind": "column", "identifier": column, "disposition": "deleted", "exists": False}
        for column in RETIRED_COLUMNS
    )
    entries.append(
        {
            "kind": "vocabulary",
            "identifier": _OWN + " identity/report vocabulary",
            "disposition": "forbidden",
            "exists": None,
            "replacement": RETIRED_CONCEPTS[2]["replacement"],
        }
    )
    entries.extend(
        {"kind": "filesystem_artifact", "identifier": artifact, "disposition": "deleted", "exists": None}
        for artifact in retired_filesystem_artifacts()
    )
    entries.extend(
        {
            "kind": concept["kind"],
            "identifier": concept["identifier"],
            "disposition": "deleted" if concept["kind"] != "vocabulary" else "forbidden",
            "exists": None,
            "replacement": concept["replacement"],
        }
        for concept in RETIRED_CONCEPTS
    )
    return entries


def build_proof(*, include_head_hashes: bool = False) -> dict[str, Any]:
    """Assemble the full machine-readable deletion proof."""
    source_scan = scan_executable_sources()
    cli = scan_cli_registries()
    schema = scan_schema()
    generated = scan_generated_report_artifacts()
    reachability = check_replacement_reachability()
    matched_locations = source_scan["matches"] + cli["findings"] + schema["findings"] + generated["hits"]
    replacement_failures = sorted(symbol for symbol, data in reachability.items() if not data["reachable"])
    zero_runtime_edges = not matched_locations and not replacement_failures
    return {
        "plan": "TASK-threshold-independent-per-song-gram-geometry-migration-R-deletion-proof",
        "package_root": _PACKAGE_ROOT.relative_to(_REPO_ROOT).as_posix(),
        "generated_at_ms": int(time.time() * 1000),
        "deletion_map": build_deletion_map(include_head_hashes=include_head_hashes),
        "scans": {
            "executable_python": source_scan,
            "dynamic_dispatch": {"matches": [m for m in source_scan["matches"] if m["kind"] == "dynamic"]},
            "cli_registries": cli,
            "schema": schema,
            "generated_artifacts": generated,
        },
        "replacement_reachability": reachability,
        "matched_locations": matched_locations,
        "replacement_failures": replacement_failures,
        "zero_runtime_edges": zero_runtime_edges,
        "exit_status": 0 if zero_runtime_edges else 1,
        "summary": {
            "retired_surfaces": len(build_deletion_map()),
            "matched_locations": len(matched_locations),
            "scanned_python_files": source_scan["file_count"],
            "replacement_symbols": len(reachability),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_deletion_map_covers_every_retired_surface() -> None:
    entries = build_deletion_map()
    kinds = {entry["kind"] for entry in entries}
    assert {"module", "symbol", "table", "column", "vocabulary", "filesystem_artifact", "engine"} <= kinds
    assert all(entry["disposition"] in {"deleted", "forbidden"} for entry in entries)
    assert all(entry["exists"] is not True for entry in entries)


def test_retired_modules_are_absent_from_disk_and_unimportable() -> None:
    for relative in RETIRED_MODULES:
        assert not (_PACKAGE_ROOT / relative).exists(), relative
        dotted = "scripts.embedding_research." + _module_stem(relative)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(dotted)


def test_executable_scan_has_zero_retired_edges() -> None:
    result = scan_executable_sources()
    assert result["file_count"] >= 10
    assert result["matches"] == [], result["matches"]


def test_dynamic_dispatch_has_no_retired_literals() -> None:
    result = scan_executable_sources()
    assert [match for match in result["matches"] if match["kind"] == "dynamic"] == []


def test_cli_registries_exclude_retired_commands() -> None:
    assert scan_cli_registries()["findings"] == []


def test_schema_excludes_retired_tables_and_columns() -> None:
    assert scan_schema()["findings"] == []


def test_replacement_symbols_are_reachable() -> None:
    reachability = check_replacement_reachability()
    failures = {symbol: data for symbol, data in reachability.items() if not data["reachable"]}
    assert not failures, failures


def test_generated_report_artifacts_are_clean() -> None:
    from scripts.embedding_research.config import REPORT_DIR

    if not (Path(REPORT_DIR) / "report.json").is_file():
        pytest.skip("no generated report artifact present in this checkout")
    assert scan_generated_report_artifacts()["hits"] == []


def test_fixture_generated_output_is_clean(tmp_path) -> None:
    from scripts.embedding_research.generate_fixture_report import main as generate

    html = tmp_path.parent / "docs" / "embedding-research-report.html"
    generate(tmp_path, html_out_path=html)
    text = (tmp_path / "report.json").read_text(encoding="utf-8", errors="replace")
    assert scan_generated_text(text) == [], "report.json"
    html = tmp_path.parent / "docs" / "embedding-research-report.html"
    assert html.is_file() and html.stat().st_size > 0
    assert not list(tmp_path.rglob("*.html"))
    assert all(path.suffix == ".json" for path in tmp_path.rglob("*") if path.is_file())


def test_historical_prose_is_not_scanned_as_executable() -> None:
    files = {str(path) for path in _iter_python_files()}
    assert files
    # The historical ``artifacts/`` tree must never be scanned; a tool module whose
    # *filename* contains the word is not a historical prose path.
    assert not any("artifacts" in Path(path).parts for path in files)


def test_proof_is_machine_readable_and_zero_edges() -> None:
    proof = build_proof()
    round_tripped = json.loads(json.dumps(proof))
    assert round_tripped["zero_runtime_edges"] is True, round_tripped["matched_locations"]
    assert round_tripped["exit_status"] == 0
    assert round_tripped["summary"]["matched_locations"] == 0
    assert round_tripped["replacement_failures"] == []


def _write_proof(destination: Path) -> int:
    proof = build_proof(include_head_hashes=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    return int(proof["exit_status"])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Emit the geometry hard-cut deletion proof as JSON.")
    parser.add_argument("--write", required=True, help="destination JSON path")
    arguments = parser.parse_args(argv)
    return _write_proof(Path(arguments.write))


if __name__ == "__main__":
    raise SystemExit(main())
