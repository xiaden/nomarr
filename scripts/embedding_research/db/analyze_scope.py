"""Run-scoped analyze write + scope bookkeeping contract (Plan E P3-S3, post-run_id-migration).

``analyze_metrics`` now carries a physical ``run_id`` column (added by the backup-first
``db._schema.migrate_analyze_metrics_provenance`` migration, which copies legacy rows as
``run_id='legacy'`` and drops the old PRIMARY KEY).  This module is the scope bookkeeping + writer
surface layered on that column:

  * the encode/parse/record scope contracts below are preserved — a run's output-row scope is still
    recorded in ``run_provenance.output_artifact_hashes`` as a canonical parseable ``analyze_scope_v1``
    record (the atomicity/audit layer, Phase C/D) — while run-scoped WRITES additionally stamp the
    physical ``run_id`` on every aggregate row they own.
  * an analysis run only ever touches rows it owns.  The aggregate writer
    ``db.write_analyze_metrics`` (called from :func:`write_catalog_analyze_rows`) deletes/replaces ONLY
    its own ``(run_id, strategy_key, sim_metric, k)`` scope — never another run's rows and never
    Tier 1/2 baseline/corpus results (``run_id='legacy'``) or retained runs.  No code path here or in
    the analysis callers performs a global ``DELETE FROM analyze_metrics``.
  * the run-scoped reader contracts that gained a ``run_id`` filter (``load_analyze_metrics`` in
    db/flat.py, ``query_analysis_done`` in db/queries.py) restrict to rows whose physical ``run_id``
    column equals that run.  ``query_analyze_metrics`` (report/_retrieval.py) gained the same optional
    ``run_id`` filter.  Default ``run_id=None`` keeps the whole-table read (unchanged on a single
    generation DB).
  * :func:`run_row_scopes` remains the provenance/atomicity bookkeeping query (a scope may be recorded
    before any row is physically written, and recorded scopes are retained as the run's audit record);
    the physical column is the row-level realization used by reader filters and run-scoped reset.

Finite-only guarantee is enforced by the analysis layer (common.catalog_analysis raises
``NonFiniteResultError`` before a non-finite value can reach a writer).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_ANALYZE_PHASE = "analyze"
_SCOPE_PREFIX = "analyze_scope_v1"


def encode_analyze_scope(scope: Mapping[str, Any]) -> str:
    """Canonical single-line scope record for *scope* (parsable with :func:`parse_analyze_scope`)."""
    payload = {
        "strategy_key": scope["strategy_key"],
        "sim_metric": scope["sim_metric"],
        "k": scope["k"],
        "backbone": scope["backbone"],
        "config_ids": sorted(scope.get("config_ids", ())),
        "search_view_hash": scope.get("search_view_hash", ""),
        "score_variant": scope.get("score_variant", ""),
        "scoring_semantics_version": scope.get("scoring_semantics_version", 0),
    }
    return f"{_SCOPE_PREFIX}|{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"


def parse_analyze_scope(text: str) -> dict[str, Any] | None:
    """Parse a scope line written by :func:`encode_analyze_scope`; None if not one."""
    if not text.startswith(_SCOPE_PREFIX + "|"):
        return None
    return json.loads(text.split("|", 1)[1])


def _scope_row_scope(text: str) -> tuple[str, str, int] | None:
    scope = parse_analyze_scope(text)
    if scope is None:
        return None
    return (scope["strategy_key"], scope["sim_metric"], int(scope["k"]))


def run_row_scopes(con, *, run_id: str) -> frozenset[tuple[str, str, int]]:
    """The set of ``(strategy_key, sim_metric, k)`` output-row scopes recorded for *run_id*.

    Read from the run's ``phase='analyze'`` ``run_provenance`` rows' ``output_artifact_hashes``
    (each may carry many scope lines).  Empty when the run has no recorded analyze scope.
    """
    scopes: set[tuple[str, str, int]] = set()
    rows = con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    for (blob,) in rows:
        if not blob:
            continue
        for line in blob.splitlines():
            parsed = _scope_row_scope(line.strip())
            if parsed is not None:
                scopes.add(parsed)
    return frozenset(scopes)


def record_analyze_run_scope(
    con,
    *,
    run_id: str,
    strategy_key: str,
    sim_metric: str,
    k: int,
    backbone: str,
    config_ids: tuple[int, ...],
    search_view_hash: str,
    score_variant: str,
    scoring_semantics_version: int,
) -> None:
    """Record *run_id*'s output-row scope in ``run_provenance.output_artifact_hashes``.

    Merge semantics: appends this strategy scope to every ``phase='analyze'`` provenance row of the
    run, deduped by ``(strategy_key, sim_metric, k)``.  If the run has no ``phase='analyze'`` row yet
    (no view was materialized for it), one is created (status ``complete``) so the scope anchor always
    exists.  Other runs' rows — including ``retained`` rows — are never modified.
    """
    line = encode_analyze_scope(
        {
            "strategy_key": strategy_key,
            "sim_metric": sim_metric,
            "k": k,
            "backbone": backbone,
            "config_ids": config_ids,
            "search_view_hash": search_view_hash,
            "score_variant": score_variant,
            "scoring_semantics_version": scoring_semantics_version,
        }
    )
    existing = con.execute(
        "SELECT rowid FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    if not existing:
        from scripts.embedding_research.db.provenance import write_run_provenance

        write_run_provenance(
            con,
            run_id=run_id,
            phase=_ANALYZE_PHASE,
            status="complete",
            started_at=_now_ms(),
            finished_at=_now_ms(),
            output_artifact_hashes=line,
        )
        return
    # Merge into each existing phase='analyze' row.
    for (rowid,) in existing:
        (blob,) = con.execute("SELECT output_artifact_hashes FROM run_provenance WHERE rowid=?", (rowid,)).fetchone()
        lines = [ln for ln in (blob or "").splitlines() if ln.strip()] if blob else []
        if line not in lines:
            lines.append(line)
        con.execute(
            "UPDATE run_provenance SET output_artifact_hashes=? WHERE rowid=?",
            ("\n".join(lines), rowid),
        )


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def write_catalog_analyze_rows(
    con,
    *,
    run_id: str,
    result,
) -> str:
    """Run-scoped writer for a :class:`CatalogAnalysisResult` (finite, identity-carrying).

    Writes the aggregate ``analyze_metrics`` rows and per-song ``song_retrieval_metrics`` rows under
    ``result.strategy_key`` (which embeds backbone/score-variant/keyset) and records the run's output
    scope in provenance.  Returns ``result.strategy_key``.

    Finite-only: this function asserts ``result.finite`` and refuses to write otherwise (the analysis
    layer raises ``NonFiniteResultError`` before ever building a non-finite result, so this is a
    defensive final gate at the trust boundary).  No global delete occurs anywhere in this path.
    """
    if not result.finite:
        raise ValueError(f"refusing to write non-finite catalog analysis result for run {run_id!r}")
    from scripts.embedding_research import db

    strategy_key = result.strategy_key
    sim_metric = "cosine"  # primary sim-metric dimension (mirrors similarity.METRICS == {cosine})
    # Aggregate rows: stamped with this run's physical run_id; write_analyze_metrics replaces
    # only this run's own (run_id, strategy scope) rows, never another run's or legacy baseline.
    db.write_analyze_metrics(con, strategy_key, "catalog", sim_metric, result.k, dict(result.metrics), run_id=run_id)
    # Per-song rows: clear only this strategy scope, then write using the legacy song_retrieval_metrics
    # writer contract (parallel lists keyed by song_ids).
    db.clear_song_retrieval_metrics(con, strategy_key, sim_metric, result.k)
    song_ids = sorted(result.per_song)
    per_song = {
        "song_ids": song_ids,
        "ap_k": [float(result.per_song[s]["map_k"]) for s in song_ids],
        "mrr": [float(result.per_song[s]["mrr"]) for s in song_ids],
        "recall_k": [float(result.per_song[s]["recall_k"]) for s in song_ids],
        "disc_artist_contrib": [float(result.per_song[s]["within"] - result.per_song[s]["cross"]) for s in song_ids],
        "disc_genre_contrib": [],
        "disc_head_contrib": [],
    }
    db.write_song_retrieval_metrics(con, strategy_key, sim_metric, result.k, per_song)
    record_analyze_run_scope(
        con,
        run_id=run_id,
        strategy_key=strategy_key,
        sim_metric=sim_metric,
        k=result.k,
        backbone=result.backbone,
        config_ids=result.config_ids,
        search_view_hash=result.search_view_hash,
        score_variant=result.score_variant,
        scoring_semantics_version=result.scoring_semantics_version,
    )
    return strategy_key
