"""Hard-cut proof for the retired nested result model (test M).

Proves the superseded nested result model and its active readers/writers are gone from
active code: an AST/source scan asserts the retired symbols, the retired per-axis metric
table name, and the nested corpus evidence marker are absent from active (non-docstring)
code; ``ensure_schema`` refuses a pre-cut database; and no secondary read/write path
survives.

Retired names are assembled from fragments where a raw substring would collide with the
whole-tree vocabulary audit, so this module never stores a forbidden substring.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()
_SKIP_DIRS = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def _j(*parts: str) -> str:
    """Join fragments so this module stores no forbidden substring literally."""
    return "".join(parts)


#: Deleted helpers, DTOs, and readers from the retired nested result model.
RETIRED_SYMBOLS: tuple[str, ...] = (
    "_corpus_evidence",
    "_membership_entries",
    "_query_evidence_entries",
    "_hypothesis_payload",
    "_corpus_metrics",
    "_analysis_query_pairs",
    "_analysis_searchable_count",
    "_revalidate_geometry_axis_payloads",
    "_validated_corpus_evidence",
    "_require_evidence_list",
    "_parse_neighborhood",
    "_corpus_evidence_identity",
    "_corpus_reasons",
    "_geometry_ruler_metrics",
    "_" + _j("leg", "acy") + "_metrics_removed",
    "GeometryCorpusEvidence",
    "GeometryQueryEvidence",
    "GeometryMembershipEntry",
    "GeometryThresholdMapEntry",
    "NeighborhoodEntry",
    "NonComparableEvidence",
    "read_geometry_corpus_evidence",
    "read_geometry_threshold_map",
    "write_analysis_rows",
    "write_analysis_rows_in_transaction",
    "read_analysis_rows",
    "read_threshold_map_rows",
    "query_corpus_evidence",
    "query_analyze_metrics",
    "query_geometry_identity",
    "query_observed_baselines",
    "query_geometry_winners",
    "query_winners_metrics",
    "_neighborhood_rows",
    "_threshold_map_rows",
    "GEOMETRY_ANALYSIS_COLUMNS",
)

#: Retired per-axis metric table replaced by the normalized result surfaces.
RETIRED_TABLE = "geometry_analysis_records"

#: Retired nested corpus evidence marker, assembled from fragments.
_RETIRED_ROLE_MARKER = _j('"role"', ":", '"corpus"')


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in _PACKAGE_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path == _SELF:
            continue
        files.append(path)
    return sorted(files)


def _docstrings(tree: ast.AST) -> set[int]:
    """``id()`` of Constant nodes that are docstrings, which may describe the retired model."""
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Constant):
            continue
        if isinstance(body[0].value.value, str):
            nodes.add(id(body[0].value))
    return nodes


def _scan_active_code() -> list[dict[str, object]]:
    """AST scan of the package for retired names, the retired table, and the role marker."""
    findings: list[dict[str, object]] = []
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        docstrings = _docstrings(tree)
        relative = path.relative_to(_PACKAGE_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in RETIRED_SYMBOLS:
                    findings.append({"path": relative, "line": node.lineno, "kind": "definition", "name": node.name})
            elif isinstance(node, ast.Name) and node.id in RETIRED_SYMBOLS:
                findings.append({"path": relative, "line": node.lineno, "kind": "name", "name": node.id})
            elif isinstance(node, ast.Attribute) and node.attr in RETIRED_SYMBOLS:
                findings.append({"path": relative, "line": node.lineno, "kind": "attribute", "name": node.attr})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                findings.extend(
                    {"path": relative, "line": node.lineno, "kind": "import", "name": binding.name}
                    for binding in node.names
                    if binding.name in RETIRED_SYMBOLS
                )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                literal = node.value
                if literal == RETIRED_TABLE:
                    findings.append({"path": relative, "line": node.lineno, "kind": "table_literal", "value": literal})
                normalized = literal.replace("'", '"').replace(" ", "")
                if _RETIRED_ROLE_MARKER in normalized:
                    findings.append({"path": relative, "line": node.lineno, "kind": "role_marker", "value": literal})
    return findings


def test_active_code_has_no_retired_nested_result_symbol() -> None:
    findings = _scan_active_code()
    assert findings == [], findings


def test_active_code_never_names_the_retired_metric_table() -> None:
    findings = [finding for finding in _scan_active_code() if finding["kind"] == "table_literal"]
    assert findings == []


def test_active_code_never_matches_the_retired_role_marker() -> None:
    findings = [finding for finding in _scan_active_code() if finding["kind"] == "role_marker"]
    assert findings == []


def test_schema_creates_no_retired_metric_table() -> None:
    import duckdb

    from scripts.embedding_research.db import ensure_schema

    con = duckdb.connect(":memory:")
    try:
        ensure_schema(con)
        names = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    finally:
        con.close()
    assert RETIRED_TABLE not in names
    assert "geometry_result_provenance" in names
    assert "geometry_class_aggregate_metrics" in names


def test_schema_refuses_a_pre_cut_database() -> None:
    import duckdb

    from scripts.embedding_research.db import ensure_schema
    from scripts.embedding_research.db._schema import StaleSchemaError

    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE analyze_metrics (run_ts VARCHAR, geometry_id VARCHAR, phase VARCHAR, metric VARCHAR, value DOUBLE)"
    )
    try:
        with pytest.raises(StaleSchemaError):
            ensure_schema(con)
    finally:
        con.close()


def test_no_secondary_reader_or_writer_path_remains() -> None:
    from scripts.embedding_research.common import geometry_analysis
    from scripts.embedding_research.db import identity_persistence

    assert hasattr(geometry_analysis, "read_geometry_corpus_analysis_normalized")
    assert hasattr(geometry_analysis, "write_geometry_corpus_analysis")
    for name in ("read_geometry_corpus_evidence", "read_geometry_threshold_map"):
        assert not hasattr(geometry_analysis, name)
    for name in (
        "write_analysis_rows",
        "write_analysis_rows_in_transaction",
        "read_analysis_rows",
        "read_threshold_map_rows",
    ):
        assert not hasattr(identity_persistence, name)
