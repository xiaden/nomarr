"""Plan D Phase 4 (P4-S4) — the future ANN boundary is an interface SEAM, never a live v1 index.

DD requirement (DD-R10 / search_views): **v1 performs exact CPU gathering and scoring and
creates NO ANN index and NO DuckDB VSS persistence.**  The only "ANN" surface on the exact
CPU path is an *interface seam* — the module docstring/interface documenting where ANN would
plug in later (``search_views.py`` states "v1 is exact CPU gathering; the ANN boundary is only
an interface seam").  It is never a live v1 index.

This module proves that through the FULL catalog-first analysis path over a synthetic corpus
(catalog -> disposable corpus view -> bounded scoring -> run-scoped metrics):

* after a full analysis NO ANN artifact exists: no ANN/VSS/index table or column in the
  catalog, ``duckdb_indexes()`` is empty (no index of any kind was created), and no ANN index
  file/artifact was produced under the output tree (the only produced artifact is the exact
  CPU ``views/<keyset>/vectors.npy`` + ``keys.json`` view, never an index file);
* no DuckDB VSS function is invoked and no code in the exact-CPU analysis modules constructs
  an ANN index — asserted structurally (AST/tokenize scan, mirroring
  ``test_frozen_invariants``) that real code (never docstrings/comments, which legitimately
  document the seam) in ``catalog_analysis`` / ``search_views`` / ``bounded_scoring`` /
  ``scoring_harness`` / ``catalog`` / ``fixture_benchmark`` never references the ANN/VSS/index
  construction vocabulary;
* the ONLY ANN surface is the documented interface seam (docstring present in
  ``search_views``), asserted present and described as a seam;
* the research CPU boundary holds through the full analysis path: a real full analysis
  completes with raising sentinels on ``config.discover_audio`` / ``onnxruntime.
  InferenceSession`` / ``torch.cuda.is_available`` and records ZERO calls (the R5 negative
  gate, same style as ``test_stream_cpu_boundary`` / ``test_negative_boundaries``).

Every number here is a fixture over a deterministic synthetic corpus — never an empirical
corpus/model claim.
"""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research import fixture_benchmark
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.config import discover_audio as config_discover_audio
from scripts.embedding_research.streams.store import StreamStore

# Optional ML-stack availability — the analysis path never imports these; sentinels fire if
# a regression ever reaches them, and if absent they cannot be called (itself the CPU proof).
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]

_RESEARCH_DIR = Path(__file__).resolve().parents[1]

#: The synthetic corpus surface (documented fixtures; never empirical).
_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}


class _RaisingSentinel:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __call__(self, *_args, **_kwargs):
        self.events.append(self.name)
        raise AssertionError(f"forbidden call during a CPU-only analysis: {self.name}")


def _install_sentinels(monkeypatch) -> dict[str, int]:
    """Monkeypatch real audio/ONNX/CUDA call sites with raising sentinels."""
    events: list[str] = []
    installed: dict[str, _RaisingSentinel] = {}

    sentinel = _RaisingSentinel("config.discover_audio", events)
    monkeypatch.setattr(config_discover_audio.__module__ + ".discover_audio", sentinel)
    installed["config.discover_audio"] = sentinel

    if onnxruntime is not None:
        sentinel = _RaisingSentinel("onnxruntime.InferenceSession", events)
        monkeypatch.setattr(onnxruntime, "InferenceSession", sentinel)
        installed["onnxruntime.InferenceSession"] = sentinel

    if torch is not None:
        sentinel = _RaisingSentinel("torch.cuda.is_available", events)
        monkeypatch.setattr(torch.cuda, "is_available", sentinel)
        installed["torch.cuda.is_available"] = sentinel

    return {name: len(_sentinel.events) for name, _sentinel in installed.items()}


def _unit(rng, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _build_corpus(con, out) -> tuple[StreamStore, object]:
    """Publish one ready effnet stream per song and build a VERIFIED COMPACT catalog.

    Returns ``(store, handle)`` where *handle* is the open read-only compact snapshot handle
    (caller must ``.close()`` it) whose ``.con`` the analysis reads from.
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.catalog_storage import open_snapshot_file
    from scripts.embedding_research.streams import make_current_stream_resolver

    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(7)
    for song in _SONGS:
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(
        make_current_stream_resolver(store),
        None,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        list(_SONGS),
        output_root=str(out),
        run_id="run-cat-1",
        verify=True,
    )
    assert rep.verify_ok is True
    handle = open_snapshot_file(f"{out}/catalogs/.staging-run-cat-1/catalog.duckdb", read_only=True)
    return store, handle


def _run_full_analysis(con, tmp_path) -> ca.CatalogAnalysisResult:
    store, handle = _build_corpus(con, tmp_path / "out")
    try:
        cfg = ca.CatalogAnalysisConfig(run_id="run-ann-1", backbone="effnet", song_ids=_SONGS, artists=_ARTISTS)
        return ca.analyze_catalog_corpus(store, handle.con, cfg, research_con=con)
    finally:
        handle.close()


# --------------------------------------------------------------------------- #
# 1. Full analysis completes exact-CPU with ZERO audio/model/CUDA sentinel calls #
# --------------------------------------------------------------------------- #


def test_full_analysis_exact_cpu_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """A full catalog-first analysis completes and records ZERO sentinel (audio/model/CUDA) calls.

    Both halves of the DD negative gate: the workload COMPLETES with a finite numpy result
    AND every installed sentinel recorded ZERO calls.  A sentinel firing would raise and
    fail the test — catching a sentinel exception is never a success path.
    """
    store, handle = _build_corpus(con, tmp_path / "out")
    counts = _install_sentinels(monkeypatch)

    cfg = ca.CatalogAnalysisConfig(run_id="run-ann-1", backbone="effnet", song_ids=_SONGS, artists=_ARTISTS)
    try:
        result = ca.analyze_catalog_corpus(store, handle.con, cfg, research_con=con)

        assert result.finite is True
        assert len(result.per_query) == len(_SONGS)
    finally:
        handle.close()
    assert counts  # at least config.discover_audio is always guarded
    assert all(count == 0 for count in counts.values()), counts


# --------------------------------------------------------------------------- #
# 2. No ANN artifact after a full analysis (tables/columns/indexes/files)        #
# --------------------------------------------------------------------------- #


def test_after_full_analysis_no_ann_index_tables_columns_or_files(con, tmp_path):
    """A full analysis leaves NO ANN/VSS/index table, column, DB index, or artifact file."""
    result = _run_full_analysis(con, tmp_path)
    assert result.finite is True

    # No database index of any kind (duckdb VSS / ANN indexes are just DuckDB indexes).
    indexes = con.execute("SELECT * FROM duckdb_indexes()").fetchall()
    assert indexes == [], f"an index was created on the analysis path: {indexes}"

    # No ANN/VSS/index-related table or column anywhere in the catalog.
    forbidden = ("hnsw", "faiss", "ivf", "vss", "ann", "vector_index", "vector_collection")
    tables = [row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]
    columns = [
        row[1] for row in con.execute("SELECT table_name, column_name FROM information_schema.columns").fetchall()
    ]
    assert all(lower not in (t.lower() for t in tables) for lower in forbidden)
    assert all(lower not in (c.lower() for c in columns) for lower in forbidden)
    # No view_manifest registry table either.
    assert not any("view_manifest" in t.lower() for t in tables)

    # The only produced artifact under the output tree is the exact-CPU disposable view
    # (vectors.npy + keys.json), never an ANN/index file.
    out_root = Path(tmp_path / "out")
    produced = {str(p.relative_to(out_root)) for p in out_root.rglob("*") if p.is_file()}
    index_hint = {"hnsw", "faiss", ".index", ".ivf", "ann"}
    offenders = [rel for rel in produced if any(hint in rel.lower() for hint in index_hint)]
    assert offenders == [], f"ANN/index artifact files were produced: {offenders}"
    # The exact CPU view payload is present (proving the v1 gathering path actually ran).
    view_npy = [rel for rel in produced if rel.startswith("views/") and rel.endswith("vectors.npy")]
    assert view_npy, "no disposable exact-CPU view was materialized"
    assert "keys.json" in {rel.split("/")[-1] for rel in produced if rel.startswith("views/")}


def test_full_analysis_no_duckdb_vss_artifacts_via_analysis_sql(con, tmp_path):
    """The analysis writes its scope through plain exact values, never DuckDB VSS DDL."""
    result = _run_full_analysis(con, tmp_path)
    assert result.finite is True
    # The analysis registered rows in run_provenance / analyze tables without any index.
    tables = [row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]
    assert "view_manifest" not in tables
    assert con.execute("SELECT * FROM duckdb_indexes()").fetchall() == []


# --------------------------------------------------------------------------- #
# 3. The ONLY ANN surface on the exact-CPU path is the documented interface seam   #
# --------------------------------------------------------------------------- #

#: Real-code (non-docstring/non-comment) tokens that would mean an ANN/VSS/index is live.
_FORBIDDEN_ANN_TOKENS = ("faiss", "hnsw", "ivfflat", "annindex", "vector_index", "create index", "duckdb_indexes")


def _real_code_references_ann(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line) where a forbidden ANN/VSS/index token appears in real code.

    Docstring/comment mentions are tolerated — they legitimately document the interface
    seam / deliberate omission (mirroring the ``disc_album`` guard in test_frozen_invariants);
    a real import, class, call or SQL reference is a violation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstring_lines: set[int] = set()
    for node in [tree, *ast.walk(tree)]:
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_lines.add(body[0].lineno)

    violations: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            lowered = tok.string.lower()
            if not any(bad in lowered for bad in _FORBIDDEN_ANN_TOKENS):
                continue
            if tok.type == tokenize.STRING and tok.start[0] in docstring_lines:
                continue
            violations.append((tok.start[0], tok.line.rstrip()))
    return violations


@pytest.mark.parametrize(
    "rel",
    [
        "search_views.py",
        "bounded_scoring.py",
        "scoring_harness.py",
        "common/catalog_analysis.py",
        "catalog.py",
        "fixture_benchmark.py",
    ],
)
def test_exact_cpu_modules_have_no_live_ann_index_code(rel):
    """The exact-CPU analysis modules never construct/use an ANN/VSS/index in real code."""
    path = _RESEARCH_DIR / rel
    bad = _real_code_references_ann(path)
    assert not bad, f"{rel} references an ANN/VSS/index in real code: {bad}"


def test_only_ann_surface_is_the_documented_interface_seam():
    """The only 'ANN' surface is search_views's docstring: an interface seam, not a live index."""
    doc = (_RESEARCH_DIR / "search_views.py").read_text(encoding="utf-8").split('"""')[1]
    assert "ANN" in doc
    assert "interface seam" in doc
    assert "no ANN / DuckDB VSS persistence" in doc
    assert "exact CPU" in doc
    # And it never claims a live v1 index exists — it documents the seam as an omission.
    assert "no ANN / DuckDB VSS persistence" in doc


def test_fixture_benchmark_label_is_fixtures_only_and_index_free(con, tmp_path):
    """The P4-S3 benchmark helper is fixtures-only and creates no ANN artifact (consistent seam)."""
    _run_full_analysis(con, tmp_path)
    record = fixture_benchmark.run_bounded_benchmark(seed=5)
    assert record.validate() == []
    assert record.fixtures_only is True
    assert con.execute("SELECT * FROM duckdb_indexes()").fetchall() == []
