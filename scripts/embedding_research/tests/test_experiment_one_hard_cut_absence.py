"""Absence proof for the retired nested result model and every dual-surface shim.

This module complements ``test_experiment_one_hard_cut.py``.  That module scans the whole
package for retired symbol *bindings*, the retired table, and the nested role marker, then
exercises the schema refusal and the secondary reader/writer attributes.  This module scans
only the ACTIVE (non-test) modules with a wider node set -- string constants, subscript keys,
and evidence-rooted attribute access -- so a dynamic reference, a re-exported name, or a nested
evidence read cannot hide.  It additionally proves the analysis-reset topology, the declared
surface set, and the report read path all resolve to the single normalized result layer, and
re-asserts the immutable-geometry/refusal guarantees from an independent file.

Retired names and nested keys are assembled from fragments where a raw form would collide with
the whole-tree vocabulary audit, so this module never stores a forbidden substring.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

import duckdb
import pytest

from scripts.embedding_research.db._schema import StaleSchemaError, ensure_schema

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()
_SKIP_DIRS = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def _j(*parts: str) -> str:
    """Join fragments so this module stores no forbidden substring literally."""
    return "".join(parts)


#: Deleted helpers, DTOs, and readers from the retired nested result model.
_RETIRED_SYMBOLS: tuple[str, ...] = (
    "GeometryCorpusEvidence",
    "GeometryQueryEvidence",
    "GeometryMembershipEntry",
    "GeometryThresholdMapEntry",
    "read_geometry_corpus_evidence",
    "read_geometry_threshold_map",
    "read_threshold_map_rows",
    "write_analysis_rows",
    "write_analysis_rows_in_transaction",
    "read_analysis_rows",
    "_corpus_evidence",
    "_analysis_query_pairs",
)

#: Retired per-axis metric table, assembled so the literal never appears as one AST constant.
_RETIRED_TABLE = "geometry_" + "analysis_records"

#: Nested evidence keys of the retired giant JSON blob.
_RETIRED_NESTED_KEYS = ("threshold_map", "queries", "hypotheses", "neighborhood")

#: Bases whose attribute access denotes the retired nested evidence shape.
_RETIRED_EVIDENCE_ROOTS = frozenset({"_corpus_evidence", "corpus_evidence", "evidence", "evidence_json", "corpus"})

#: Retired nested corpus evidence marker, assembled from fragments.
_RETIRED_ROLE_MARKER = _j('"role"', ":", '"corpus"')

#: Normalized result surfaces A-G: ``(table, reader_module, reader, report_wrapper_or_None)``.
#: The reader is the ONE canonical read path; the wrapper (when present) is the ONE report read
#: path and must delegate to that reader.
_SURFACES: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "geometry_threshold_class_map",
        "scripts.embedding_research.db.identity_persistence",
        "read_threshold_class_map",
        "query_threshold_class_map",
    ),
    (
        "geometry_class_aggregate_metrics",
        "scripts.embedding_research.db.result_surfaces",
        "read_class_aggregate_metrics",
        "query_class_aggregate_metrics",
    ),
    (
        "geometry_class_query_metrics",
        "scripts.embedding_research.db.result_surfaces",
        "read_class_query_metrics",
        "query_class_query_metrics",
    ),
    (
        "geometry_class_neighborhoods",
        "scripts.embedding_research.db.result_surfaces",
        "read_class_neighborhoods",
        "query_class_neighborhoods",
    ),
    (
        "geometry_baseline_aggregate_metrics",
        "scripts.embedding_research.db.result_surfaces",
        "read_baseline_aggregate_metrics",
        "query_baseline_aggregate_metrics",
    ),
    (
        "geometry_baseline_query_metrics",
        "scripts.embedding_research.db.result_surfaces",
        "read_baseline_query_metrics",
        "query_baseline_query_metrics",
    ),
    (
        "geometry_baseline_neighborhoods",
        "scripts.embedding_research.db.result_surfaces",
        "read_baseline_neighborhoods",
        "query_baseline_neighborhoods",
    ),
    (
        "geometry_evaluation_corpus",
        "scripts.embedding_research.db.identity_persistence",
        "read_evaluation_corpus",
        "query_evaluation_corpus",
    ),
    (
        "geometry_threshold_structural",
        "scripts.embedding_research.db.identity_persistence",
        "read_threshold_structural",
        None,
    ),
    (
        "geometry_head_label_provenance",
        "scripts.embedding_research.db.identity_persistence",
        "read_head_label_provenance",
        None,
    ),
    (
        "geometry_result_provenance",
        "scripts.embedding_research.db.result_surfaces",
        "read_result_provenance",
        "query_result_provenance",
    ),
)

#: Upstream authoritative tables the analysis reset must never delete from.
_AUTHORITATIVE_TABLES = (
    "song_patch_geometry",
    "stream_registry",
    "head_stream_registry",
    "songs",
    "corpus_state",
)


def _iter_active_python_files() -> list[Path]:
    """Every authored non-test module under the research package."""
    files: list[Path] = []
    for path in _PACKAGE_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if "tests" in path.relative_to(_PACKAGE_ROOT).parts:
            continue
        if path == _SELF:
            continue
        files.append(path)
    return sorted(files)


def _relative(path: Path) -> str:
    return path.relative_to(_PACKAGE_ROOT).as_posix()


def _module_relative(module_name: str) -> str:
    return module_name.removeprefix("scripts.embedding_research.").replace(".", "/") + ".py"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _scan_active_code() -> list[dict[str, Any]]:
    """AST scan of ACTIVE modules for retired names, table, role marker, and nested access."""
    findings: list[dict[str, Any]] = []
    for path in _iter_active_python_files():
        tree = _parse(path)
        if tree is None:
            continue
        relative = _relative(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name in _RETIRED_SYMBOLS
            ):
                findings.append({"path": relative, "line": node.lineno, "kind": "definition", "name": node.name})
            if isinstance(node, ast.Name) and node.id in _RETIRED_SYMBOLS:
                findings.append({"path": relative, "line": node.lineno, "kind": "name", "name": node.id})
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                findings.extend(
                    {"path": relative, "line": node.lineno, "kind": "import", "name": binding.name}
                    for binding in node.names
                    if binding.name in _RETIRED_SYMBOLS
                )
            if isinstance(node, ast.Attribute):
                if node.attr in _RETIRED_SYMBOLS:
                    findings.append({"path": relative, "line": node.lineno, "kind": "attribute", "name": node.attr})
                terminal_base = _dotted(node.value).rsplit(".", 1)[-1]
                if node.attr == "threshold_map" or (
                    node.attr in _RETIRED_NESTED_KEYS and terminal_base in _RETIRED_EVIDENCE_ROOTS
                ):
                    findings.append(
                        {"path": relative, "line": node.lineno, "kind": "nested_attribute", "name": node.attr}
                    )
            if isinstance(node, ast.Subscript):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _RETIRED_NESTED_KEYS:
                    findings.append(
                        {"path": relative, "line": node.lineno, "kind": "nested_subscript", "name": key.value}
                    )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literal = node.value
                if literal in _RETIRED_SYMBOLS or literal == _RETIRED_TABLE:
                    findings.append({"path": relative, "line": node.lineno, "kind": "string_literal", "value": literal})
                normalized = literal.replace("'", '"').replace(" ", "")
                if _RETIRED_ROLE_MARKER in normalized:
                    findings.append({"path": relative, "line": node.lineno, "kind": "role_marker", "value": literal})
    return findings


def _defined_names_by_module() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for path in _iter_active_python_files():
        tree = _parse(path)
        if tree is None:
            continue
        names[_relative(path)] = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
    return names


# ── S1: the retired nested result model is absent from active code ───────────


def test_active_modules_have_no_retired_nested_result_symbol() -> None:
    findings = [
        finding
        for finding in _scan_active_code()
        if finding["kind"] in {"definition", "name", "import", "attribute", "string_literal"}
    ]
    assert findings == []


def test_active_modules_never_name_the_retired_metric_table_or_role_marker() -> None:
    findings = [finding for finding in _scan_active_code() if finding["kind"] in {"string_literal", "role_marker"}]
    assert findings == []


def test_active_modules_never_index_the_retired_nested_evidence_shape() -> None:
    findings = [
        finding for finding in _scan_active_code() if finding["kind"] in {"nested_attribute", "nested_subscript"}
    ]
    assert findings == []


# ── S2: schema refusal, reset topology, immutable geometry, refusal code ─────


def test_ensure_schema_refuses_a_pre_cut_database() -> None:
    pre_cut_analyze = duckdb.connect(":memory:")
    pre_cut_analyze.execute("CREATE TABLE analyze_metrics (strategy_key TEXT)")
    try:
        with pytest.raises(StaleSchemaError):
            ensure_schema(pre_cut_analyze)
    finally:
        pre_cut_analyze.close()

    pre_cut_geometry = duckdb.connect(":memory:")
    pre_cut_geometry.execute("CREATE TABLE song_patch_geometry (geometry_id TEXT)")
    try:
        with pytest.raises(StaleSchemaError):
            ensure_schema(pre_cut_geometry)
    finally:
        pre_cut_geometry.close()


def test_analysis_reset_topology_covers_the_normalized_surface_set() -> None:
    from scripts.embedding_research.cleanup import _DISPOSABLE_ANALYSIS_TABLES

    con = duckdb.connect(":memory:")
    try:
        ensure_schema(con)
        schema_tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    finally:
        con.close()

    disposable = set(_DISPOSABLE_ANALYSIS_TABLES)
    # No duplicate entries in the declared reset topology.
    assert len(disposable) == len(_DISPOSABLE_ANALYSIS_TABLES)
    # Every normalized result surface is disposable.
    assert {entry[0] for entry in _SURFACES} <= disposable
    # No phantom table names: the reset topology names only tables the schema creates.
    assert disposable <= schema_tables
    # Upstream authoritative evidence is never disposable.
    assert disposable.isdisjoint(_AUTHORITATIVE_TABLES)


def _geometry_row() -> dict[str, object]:
    blob = b"immutable-geometry\x00\xff"
    return {
        "geometry_id": "g1",
        "song_id": "s1",
        "backbone": "effnet",
        "observation_group_sha256": "commit",
        "stream_ref": "streams/s1.effnet.stream.npy",
        "stream_fingerprint_sha256": "stream",
        "stream_payload_sha256": "stream-payload",
        "mask_ref": "audio_masks/s1.effnet.mask.npy",
        "mask_payload_sha256": "mask-payload",
        "patch_count": 2,
        "embedding_dim": 3,
        "stream_dtype": "float32",
        "stream_format_version": "1",
        "embed_semantics_version": 1,
        "preprocess_fn": "identity",
        "preprocess_version": "1",
        "backbone_model_hash": "model",
        "audio_params": "{}",
        "provenance_source": "synthetic",
        "provenance_assumption": "synthetic",
        "alignment_token": "align",
        "audio_content_sha256": "audio",
        "mask_semantics_version": "1",
        "group_format_version": "1",
        "provenance_identity": "identity",
        "geometry_semantics_version": "1",
        "numerical_profile_digest": "profile",
        "geometry_blob_byte_length": len(blob),
        "geometry_blob_sha256": hashlib.sha256(blob).hexdigest(),
        "gram_blob": blob,
        "status": "committed",
        "writer_run_id": "run-1",
        "created_at_ms": 1,
        "updated_at_ms": 1,
    }


def test_analysis_reset_preserves_geometry_bytes_byte_for_byte(tmp_path) -> None:
    from scripts.embedding_research.cleanup import reset_analysis

    db_path = tmp_path / "db.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    row = _geometry_row()
    columns = tuple(row)
    con.execute(
        f"INSERT INTO song_patch_geometry ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(row.values()),
    )
    con.execute(
        "INSERT INTO geometry_threshold_class_map (run_id,execution_id,evaluation_id,experiment,threshold_index,"
        "threshold_value,threshold_id,corpus_search_class_id,comparable,reasons_json,created_at_ms) "
        "VALUES ('run-1','execution:run-1:effnet','eval-1','exp',0,0.5,'t-0','class-0',true,'[]',1)"
    )
    con.execute(
        "INSERT INTO geometry_threshold_structural (run_id,evaluation_id,song_id,backbone,threshold_index,"
        "threshold_id,structural_identity,search_representation_id,searchable_count,medoid_defined,alignment_ok,"
        "comparable,reasons_json,created_at_ms) "
        "VALUES ('run-1','eval-1','s1','effnet',0,'t-0','si','sr',1,true,true,true,'[]',1)"
    )
    con.close()
    digest_before = hashlib.sha256(row["gram_blob"]).hexdigest()

    reset_analysis(tmp_path, db_path)

    check = duckdb.connect(str(db_path), read_only=True)
    preserved = check.execute("SELECT gram_blob FROM song_patch_geometry").fetchone()[0]
    assert preserved == row["gram_blob"]
    assert hashlib.sha256(preserved).hexdigest() == digest_before
    assert check.execute("SELECT COUNT(*) FROM geometry_threshold_class_map").fetchone()[0] == 0
    assert check.execute("SELECT COUNT(*) FROM geometry_threshold_structural").fetchone()[0] == 0
    check.close()


def test_reset_geometry_scope_is_refused_with_the_typed_code() -> None:
    from types import SimpleNamespace

    from scripts.embedding_research import run as run_mod
    from scripts.embedding_research.cleanup import GeometryResetUnavailableError, reset_geometry

    with pytest.raises(SystemExit) as raised:
        run_mod._cmd_reset(SimpleNamespace(scope="geometry", dry_run=True))
    assert "GEOMETRY_RESET_UNAVAILABLE" in str(raised.value)

    with pytest.raises(GeometryResetUnavailableError) as typed:
        reset_geometry()
    assert typed.value.code == "GEOMETRY_RESET_UNAVAILABLE"


# ── S3: no shim, no second surface, exactly one read path per surface ────────


def _compat_markers() -> tuple[str, ...]:
    """Compatibility markers assembled from fragments."""
    return (_j("com", "pat"), _j("sh", "im"))


def test_active_modules_have_no_compatibility_shim() -> None:
    findings: list[dict[str, Any]] = []
    for path in _iter_active_python_files():
        tree = _parse(path)
        if tree is None:
            continue
        relative = _relative(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {"__getattr__", "__getattribute__"}:
                findings.append({"path": relative, "line": node.lineno, "kind": "dunder_hook", "name": node.name})
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and any(
                marker in node.name.lower() for marker in _compat_markers()
            ):
                findings.append({"path": relative, "line": node.lineno, "kind": "name", "name": node.name})
            if isinstance(node, ast.Assign):
                findings.extend(
                    {"path": relative, "line": node.lineno, "kind": "assign", "name": target.id}
                    for target in node.targets
                    if isinstance(target, ast.Name) and any(marker in target.id.lower() for marker in _compat_markers())
                )
            if isinstance(node, ast.Call):
                terminal = _dotted(node.func).rsplit(".", 1)[-1]
                if terminal in {"import_module", "__import__", "getattr"}:
                    findings.extend(
                        {"path": relative, "line": node.lineno, "kind": "dynamic", "value": argument.value}
                        for argument in node.args
                        if isinstance(argument, ast.Constant) and argument.value in (*_RETIRED_SYMBOLS, _RETIRED_TABLE)
                    )
    assert findings == []


def test_declared_surface_names_match_the_created_schema() -> None:
    from scripts.embedding_research.tools import _evidence

    declared = tuple(_evidence._RESULT_SURFACE_NAMES)
    assert len(declared) == len(set(declared))
    assert set(declared) == {entry[0] for entry in _SURFACES}

    con = duckdb.connect(":memory:")
    try:
        ensure_schema(con)
        created = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    finally:
        con.close()
    assert set(declared) <= created

    # No dual schema: each normalized surface is defined exactly once in the schema module.
    schema_source = (_PACKAGE_ROOT / "db" / "_schema.py").read_text(encoding="utf-8")
    for table in declared:
        assert schema_source.count(f"CREATE TABLE IF NOT EXISTS {table}") == 1, table


def test_report_has_exactly_one_read_path_per_surface() -> None:
    by_module = _defined_names_by_module()

    reader_locations: dict[str, list[str]] = {}
    for relative, names in by_module.items():
        for entry in _SURFACES:
            if entry[2] in names:
                reader_locations.setdefault(entry[2], []).append(relative)

    for table, reader_module, reader, _wrapper in _SURFACES:
        assert reader_locations.get(reader) == [_module_relative(reader_module)], (table, reader)

    retrieval = _module_relative("scripts.embedding_research.report._retrieval")
    wrappers = {name for name in by_module[retrieval] if name.startswith("query_")}
    expected = {entry[3] for entry in _SURFACES if entry[3] is not None}
    expected.add("query_incomplete_analyze_diagnostics")
    assert wrappers == expected

    tree = _parse(_PACKAGE_ROOT / retrieval)
    assert tree is not None
    for table, _reader_module, reader, wrapper in _SURFACES:
        if wrapper is None:
            continue
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == wrapper)
        assert reader in ast.unparse(node), (table, wrapper, reader)
