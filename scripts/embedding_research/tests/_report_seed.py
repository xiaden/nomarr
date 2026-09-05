"""Shared seeding helpers for the catalog-only report tests (research-only).

Builds active catalog ``analyze_metrics`` rows through the real analyze-scope catalog writer
(``db.analyze_scope.write_catalog_analyze_rows``) so the report tests exercise the true
persistence + provenance-scope path.
"""

from __future__ import annotations

from scripts.embedding_research.common.catalog_analysis import CatalogAnalysisResult
from scripts.embedding_research.db.analyze_scope import write_catalog_analyze_rows


def make_catalog_result(
    *,
    run_id: str,
    backbone: str,
    strategy_key: str,
    k: int,
    metrics: dict[str, float],
    view_content_hash: str = "viewhash0",
    config_ids: tuple[int, ...] = (1,),
    score_variant: str = "max_per_candidate_segment",
    version: int = 1,
) -> CatalogAnalysisResult:
    """A minimal finite CatalogAnalysisResult with empty per-song / per-query lenses."""
    return CatalogAnalysisResult(
        run_id=run_id,
        backbone=backbone,
        config_ids=config_ids,
        representation_classes=(),
        k=k,
        view_content_hash=view_content_hash,
        score_variant=score_variant,
        scoring_semantics_version=version,
        strategy_key=strategy_key,
        finite=True,
        metrics=metrics,
        per_song={},
        per_query=(),
        n_queries=0,
        n_candidate_rows=0,
    )


def seed_catalog(
    con,
    *,
    run_id: str,
    backbone: str,
    strategy_key: str,
    k: int,
    metrics: dict[str, float],
    view_content_hash: str = "viewhash0",
    config_ids: tuple[int, ...] = (1,),
    score_variant: str = "max_per_candidate_segment",
    version: int = 1,
) -> str:
    """Persist one active catalog class through the real analyze-scope catalog writer."""
    result = make_catalog_result(
        run_id=run_id,
        backbone=backbone,
        strategy_key=strategy_key,
        k=k,
        metrics=metrics,
        view_content_hash=view_content_hash,
        config_ids=config_ids,
        score_variant=score_variant,
        version=version,
    )
    return write_catalog_analyze_rows(con, run_id=run_id, result=result)


def seed_phase_timing(con, *, run_ts: str = "run-1", phase: str = "analyze", elapsed_s: float = 1.5) -> None:
    from scripts.embedding_research.db._schema import upsert_phase_timing

    upsert_phase_timing(con, run_ts, phase, elapsed_s)


def catalog_key(backbone: str, keyset: str = "abc") -> str:
    """Build a well-formed active catalog strategy key for *backbone*."""
    return f"catalog:{backbone}:max_per_candidate_segment:v1:{keyset}"


#: Forbidden legacy vocabulary that must NEVER appear in an emitted report section/table id,
#: key, title, description, warning, or value (the hard-cut report contract).
FORBIDDEN_REPORT_VOCABULARY: tuple[str, ...] = (
    "global_pool",
    "ptc",
    "ctp",
    "binned",
    "truncation",
    "optimizer",
    "weighted",
    "rep_a",
    "rep_b",
    "calibration",
)


EXACT_SECTION_IDS: tuple[str, ...] = (
    "summary",
    "corpus",
    "analysis",
    "winners",
    "head-analysis",
    "provenance",
    "efficiency",
)


def assert_no_forbidden_vocabulary(payload: dict) -> None:
    """Assert no forbidden legacy token appears in any emitted text/key of the payload."""
    import json as _json

    text = _json.dumps(payload, default=str).lower()
    hits = [tok for tok in FORBIDDEN_REPORT_VOCABULARY if tok.lower() in text]
    assert not hits, f"forbidden report vocabulary emitted: {hits}"
