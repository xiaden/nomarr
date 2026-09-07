"""Active catalog-only analysis loader and analysis section builder.

Research-only.  This module owns the single active reader over ``analyze_metrics``:

* :func:`query_analyze_metrics` returns the run-scoped (or whole active-table) catalog
  analysis rows as a decoded long-form frame.  Only ``strategy_type == "catalog"`` rows are
  ever read — there is no legacy strategy allowlist.  Each row is one literal
  ``(strategy_key, sim_metric, k, metric, value)`` cell of an active catalog class,
  enriched with the decoded identity and the provenance-scope fields
  (``canonical_config_id`` / ``alias_ids`` / the DURABLE SEMANTIC ``representation_hash`` /
  catalog anchor / per-member evidence / ``view_keyset_hash`` / ``view_content_hash``) read
  from the analyze run scope recorded in ``run_provenance``.  A disposable keyset is never
  promoted into the semantic ``representation_hash`` column.
* :func:`query_medoid_baselines` returns the observed ``global_pool:{backbone}:medoid``
  baseline ``analyze_metrics`` rows (``strategy_type == "global_pool"``) as a decoded frame.
* :func:`query_winners_metrics` concatenates the catalog classes with those medoid baseline
  rows into the winners/summary frame (catalog classes plus per-backbone baselines).
* :func:`section_analysis` renders those rows into the ``analysis`` schema-v2 section, one
  per-backbone subsection.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE
from scripts.embedding_research.db.analyze_scope import parse_analyze_scope
from scripts.embedding_research.db.incomplete_diagnostics import read_incomplete_analyze_diagnostics

from ._base import (
    CATALOG_ANALYSIS_COLUMNS,
    CATALOG_STRATEGY_TYPE,
    decode_catalog_strategy_key,
    empty_df,
    fmt,
    make_section,
    make_table,
    table_exists,
)


def _scope_map(con, *, run_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Map catalog strategy_key -> analyze run-scope dict from ``run_provenance``.

    Reads ``phase='analyze'`` provenance rows' ``output_artifact_hashes`` and parses each
    canonical ``analyze_scope_v2`` line (there is a SINGLE analyze-scope schema in the runtime;
    ``parse_analyze_scope`` returns ``None`` for any non-``analyze_scope_v2|`` line, so a
    historical v1 line is simply ignored — never a fallback/current path).  When *run_id* is given
    only that run's provenance rows are scanned, else every analyze provenance row is scanned
    (the whole active completed scope).  Returns ``{strategy_key: scope}``.
    """
    out: dict[str, dict[str, Any]] = {}
    if not table_exists(con, "run_provenance"):
        return out
    params: tuple[str, ...] = ()
    where = ""
    if run_id is not None:
        where = " WHERE run_id = ? AND phase = ?"
        params = (run_id, "analyze")
    else:
        where = " WHERE phase = ?"
        params = ("analyze",)
    try:
        rows = con.execute(
            "SELECT output_artifact_hashes FROM run_provenance" + where,
            list(params),
        ).fetchall()
    except Exception:
        return out
    for (blob,) in rows:
        if not blob:
            continue
        for line in blob.splitlines():
            scope = parse_analyze_scope(line.strip())
            if scope is None:
                continue
            out.setdefault(scope["strategy_key"], scope)
    return out


def _scope_corpus(cfg: dict[str, Any] | None) -> tuple[Any, ...]:
    """A row's persisted evaluation-corpus columns from its analyze scope dict.

    Mirrors the ``evaluation_corpus_*`` keys written onto the single ``analyze_scope_v2``
    provenance line (the five legacy keys plus the Plan C Phase 1 complete identity/evidence
    extensions); ``(None,)*13`` when the scope carries no corpus identity (absent/empty scope).
    """
    if not cfg:
        return (None,) * 13
    h = cfg.get("evaluation_corpus_hash")
    if not h:
        return (None,) * 13
    return (
        h,
        cfg.get("evaluation_corpus_count"),
        cfg.get("evaluation_corpus_comparable"),
        cfg.get("evaluation_corpus_missing_count"),
        cfg.get("evaluation_corpus_missing_digest") or None,
        cfg.get("evaluation_corpus_semantics_version"),
        cfg.get("evaluation_corpus_eligible"),
        cfg.get("evaluation_corpus_eligible_digest") or None,
        cfg.get("evaluation_corpus_requested_count"),
        cfg.get("evaluation_corpus_requested_digest") or None,
        cfg.get("evaluation_corpus_observation_digest") or None,
        cfg.get("evaluation_corpus_complete"),
        cfg.get("evaluation_corpus_integrity") or None,
    )


def _alias_and_canonical(config_ids: Any) -> tuple[Any, list[Any]]:
    """Split a sorted class member list into (canonical_config_id, sorted alias_ids).

    ``config_ids`` is the ascending class member list with the canonical (lowest) member
    first.  Empty / absent membership yields ``(None, [])``.
    """
    if not config_ids:
        return None, []
    ids = [int(c) for c in config_ids]
    return ids[0], sorted(ids[1:])


def query_analyze_metrics(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Load the active catalog-only ``analyze_metrics`` rows as a decoded long frame.

    Reads every ``analyze_metrics`` row with ``strategy_type == 'catalog'`` (optionally
    restricted to the physical ``run_id`` column equalling *run_id*), decodes each active
    ``catalog:{backbone}:{score_variant}:v{version}:{keyset}`` strategy key, and enriches the
    row with the provenance-scope config identity (``canonical_config_id``, sorted
    ``alias_ids``), the DURABLE SEMANTIC ``representation_hash``, catalog anchor, per-member
    evidence and ``view_content_hash`` where the analyze run scope is recorded.  A row whose
    durable scope carries no semantic hash is rendered visibly incomplete (``representation_hash``
    None) — the disposable strategy-key keyset is surfaced separately as ``view_keyset_hash`` and
    is never promoted into the semantic column.

    Returns an empty frame with :data:`CATALOG_ANALYSIS_COLUMNS` when the table is absent,
    has no catalog rows, or a query fails (so callers render empty sections rather than crash).
    """
    columns = list(CATALOG_ANALYSIS_COLUMNS)
    if not table_exists(con, "analyze_metrics"):
        return empty_df(columns)

    params: list[object] = [CATALOG_STRATEGY_TYPE]
    where_run = ""
    if run_id is not None:
        where_run = " AND run_id = ?"
        params.append(run_id)
    try:
        df = con.execute(
            "SELECT run_id, strategy_key, strategy_type, sim_metric, k, metric, value "
            "FROM analyze_metrics WHERE strategy_type = ?" + where_run,
            params,
        ).df()
    except Exception:
        return empty_df(columns)

    if df.empty:
        return empty_df(columns)

    # Per-ruler ``n_queries_*`` cells are ruler-evaluable-query COUNTS, not scored retrieval
    # cells: they never enter the analysis / winners / summary / winner-delta surfaces, so they
    # are excluded from the catalog-only decoded frame here (each class's n_queries_* EAV rows
    # still exist under its strategy key; they are simply not scored cells to render/benchmark).
    df = df[~df["metric"].str.startswith("n_queries_")].reset_index(drop=True)
    if df.empty:
        return empty_df(columns)

    # Decode the active catalog identity; rows whose key is not a well-formed catalog key are
    # dropped (a data-integrity anomaly, never a strategy-filter).
    decoded = df["strategy_key"].map(decode_catalog_strategy_key)
    valid = decoded.notna()
    if not valid.all():
        df = df.loc[valid]
    if df.empty:
        return empty_df(columns)

    identity = pd.DataFrame(
        list(decoded.loc[valid]),
        index=df.index,
    )

    scope = _scope_map(con, run_id=run_id)
    decoded_list = list(decoded.loc[valid])
    canonical: list[Any] = []
    alias_ids: list[Any] = []
    config_ids: list[Any] = []
    members: list[Any] = []
    semantic_hashes: list[Any] = []
    cat_ids: list[Any] = []
    cat_fprints: list[Any] = []
    view_hashes: list[Any] = []
    view_keysets: list[Any] = []
    # Parallel per-row corpus-identity column lists (the 13 ``evaluation_corpus_*`` persisted
    # keys decoded from each scope line by ``_scope_corpus``).
    corpus_cols: dict[str, list[Any]] = {
        "corpus_hash": [],
        "corpus_count": [],
        "corpus_comparable": [],
        "corpus_missing_count": [],
        "corpus_missing_digest": [],
        "corpus_semantics_version": [],
        "corpus_eligible": [],
        "corpus_eligible_digest": [],
        "corpus_requested_count": [],
        "corpus_requested_digest": [],
        "corpus_observation_digest": [],
        "corpus_complete": [],
        "corpus_integrity": [],
    }
    for i, key in enumerate(df["strategy_key"]):
        cfg = scope.get(key)
        # The disposable per-run view keyset rides in the strategy-key trailing segment; the
        # durable semantic representation hash (when recorded) is preferred over it so the
        # report never renders a disposable view/keyset hash as semantic identity.
        view_keyset = str(decoded_list[i]["keyset_hash"])
        view_keysets.append(view_keyset)
        corpus_parts = _scope_corpus(cfg)
        if cfg:
            ccid, aliases = _alias_and_canonical(cfg.get("config_ids"))
            canonical.append(ccid)
            alias_ids.append(aliases)
            config_ids.append(list(cfg.get("config_ids") or []))
            members.append(list(cfg.get("members") or []))
            semantic = cfg.get("search_representation_hash")
            # The semantic representation hash is the DURABLE catalog value; a genuinely
            # identity-less structural scope (no durable semantic recorded) stays VISIBLY
            # incomplete (None) rather than promoting the disposable keyset into the semantic
            # column (Plan B P3 removed the transitional keyset fallback).
            semantic_hashes.append(semantic or None)
            cat_ids.append(cfg.get("catalog_id") or None)
            cat_fprints.append(cfg.get("catalog_fingerprint") or None)
            view_hashes.append(cfg.get("view_content_hash") or None)
        else:
            # No provenance scope recorded: no durable semantic identity exists for the row, so
            # identity fields stay empty and it is rendered visibly incomplete — the disposable
            # keyset (carried separately in view_keyset_hash) is NEVER promoted to semantic.
            canonical.append(None)
            alias_ids.append([])
            config_ids.append([])
            members.append([])
            semantic_hashes.append(None)
            cat_ids.append(None)
            cat_fprints.append(None)
            view_hashes.append(None)
        for _name, _value in zip(corpus_cols, corpus_parts, strict=False):
            corpus_cols[_name].append(_value)

    enriched = pd.DataFrame(
        {
            "run_id": df["run_id"],
            "backbone": identity["backbone"],
            "strategy_key": df["strategy_key"],
            "strategy_type": CATALOG_STRATEGY_TYPE,
            "sim_metric": df["sim_metric"],
            "k": df["k"],
            "score_variant": identity["score_variant"],
            "scoring_semantics_version": identity["scoring_semantics_version"],
            "representation_hash": semantic_hashes,
            "catalog_id": cat_ids,
            "catalog_fingerprint": cat_fprints,
            "canonical_config_id": canonical,
            "alias_ids": alias_ids,
            "config_ids": config_ids,
            "view_keyset_hash": view_keysets,
            "view_content_hash": view_hashes,
            "class_members": members,
            "evaluation_corpus_hash": corpus_cols["corpus_hash"],
            "evaluation_corpus_count": corpus_cols["corpus_count"],
            "evaluation_corpus_comparable": corpus_cols["corpus_comparable"],
            "evaluation_corpus_missing_count": corpus_cols["corpus_missing_count"],
            "evaluation_corpus_missing_digest": corpus_cols["corpus_missing_digest"],
            "evaluation_corpus_semantics_version": corpus_cols["corpus_semantics_version"],
            "evaluation_corpus_eligible": corpus_cols["corpus_eligible"],
            "evaluation_corpus_eligible_digest": corpus_cols["corpus_eligible_digest"],
            "evaluation_corpus_requested_count": corpus_cols["corpus_requested_count"],
            "evaluation_corpus_requested_digest": corpus_cols["corpus_requested_digest"],
            "evaluation_corpus_observation_digest": corpus_cols["corpus_observation_digest"],
            "evaluation_corpus_complete": corpus_cols["corpus_complete"],
            "evaluation_corpus_integrity": corpus_cols["corpus_integrity"],
            "metric": df["metric"],
            "value": df["value"],
        }
    )
    enriched["k"] = enriched["k"].astype(int)
    order = ["backbone", "k", "strategy_key", "metric"]
    return enriched.sort_values(order, kind="mergesort").reset_index(drop=True)


def query_medoid_baselines(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Load the observed global-medoid baseline ``analyze_metrics`` rows as a decoded frame.

    Distinct from :func:`query_analyze_metrics` (catalog-only, pinned forever): reads every
    ``analyze_metrics`` row with ``strategy_type == MEDOID_STRATEGY_TYPE`` (``"global_pool"``,
    the observed ``global_pool:{backbone}:medoid`` baseline persisted by the analyze phase),
    optionally restricted to *run_id*.  Each row is one literal
    ``(strategy_key, sim_metric, k, metric, value)`` cell of that baseline identity; backbone is
    parsed from the strategy key.  A medoid baseline is NOT a catalog class, so it carries no
    class representation of its own (``representation_hash`` / ``canonical_config_id`` /
    ``alias_ids`` / ``config_ids`` / ``class_members`` / ``view_*`` are empty) — but its persisted
    ``analyze_scope_v2`` provenance line is surfaced, so ``score_variant`` /
    ``scoring_semantics_version`` / ``catalog_id`` / ``catalog_fingerprint`` / the
    evaluation-corpus identity (``evaluation_corpus_*``) are NOT left blank (a baseline scope
    anchors to the same compact catalog + corpus as the classes it benchmarks against).  Rows
    whose key is not a well-formed ``global_pool:{bb}:medoid`` key are
    dropped (a data-integrity anomaly, never a strategy-filter).  Returns an empty
    :data:`CATALOG_ANALYSIS_COLUMNS` frame when the table is absent or has no medoid rows.
    """
    columns = list(CATALOG_ANALYSIS_COLUMNS)
    if not table_exists(con, "analyze_metrics"):
        return empty_df(columns)

    params: list[object] = [MEDOID_STRATEGY_TYPE]
    where_run = ""
    if run_id is not None:
        where_run = " AND run_id = ?"
        params.append(run_id)
    try:
        df = con.execute(
            "SELECT run_id, strategy_key, sim_metric, k, metric, value "
            "FROM analyze_metrics WHERE strategy_type = ?" + where_run,
            params,
        ).df()
    except Exception:
        return empty_df(columns)

    if df.empty:
        return empty_df(columns)

    # ``n_queries_*`` counts on the medoid baseline never enter the winners/summary benchmark
    # surfaces (they are counts, not scored cells) — mirror the catalog loader filter.
    df = df[~df["metric"].str.startswith("n_queries_")].reset_index(drop=True)
    if df.empty:
        return empty_df(columns)

    backbones: list[Any] = []
    valid = []
    for sk in df["strategy_key"]:
        parts = str(sk).split(":")
        if len(parts) == 3 and parts[0] == "global_pool" and bool(parts[1]) and parts[2] == "medoid":
            backbones.append(parts[1])
            valid.append(True)
        else:
            backbones.append(None)
            valid.append(False)
    keep = [i for i, ok in enumerate(valid) if ok]
    if not keep:
        return empty_df(columns)
    df = df.iloc[keep].reset_index(drop=True)
    backbone_col = [backbones[i] for i in keep]

    scope = _scope_map(con, run_id=run_id)
    corpus: list[tuple[Any, ...]] = [_scope_corpus(scope.get(str(sk))) for sk in df["strategy_key"]]
    # A medoid baseline is not a config class, but its persisted scope carries the compact
    # catalog anchor + score/scoring-semantics provenance of the analyze run; surface those
    # rather than leaving the baseline's identity columns blank.  config / member / semantic /
    # disposable-view identity stays empty (a baseline has no class representation of its own).
    score_variants: list[Any] = []
    semantics_versions: list[Any] = []
    cat_ids: list[Any] = []
    cat_fprints: list[Any] = []
    for sk in df["strategy_key"]:
        cfg = scope.get(str(sk))
        score_variants.append(cfg.get("score_variant") if cfg else None)
        semantics_versions.append(cfg.get("scoring_semantics_version") if cfg else None)
        cat_ids.append(cfg.get("catalog_id") or None if cfg else None)
        cat_fprints.append(cfg.get("catalog_fingerprint") or None if cfg else None)

    enriched = pd.DataFrame(
        {
            "run_id": df["run_id"],
            "backbone": backbone_col,
            "strategy_key": df["strategy_key"],
            "strategy_type": MEDOID_STRATEGY_TYPE,
            "sim_metric": df["sim_metric"],
            "k": df["k"].astype(int),
            "score_variant": score_variants,
            "scoring_semantics_version": semantics_versions,
            "representation_hash": [None] * len(df),
            "catalog_id": cat_ids,
            "catalog_fingerprint": cat_fprints,
            "canonical_config_id": [None] * len(df),
            "alias_ids": [[] for _ in range(len(df))],
            "config_ids": [[] for _ in range(len(df))],
            "view_keyset_hash": [""] * len(df),
            "view_content_hash": [None] * len(df),
            "class_members": [[] for _ in range(len(df))],
            "evaluation_corpus_hash": [c[0] for c in corpus],
            "evaluation_corpus_count": [c[1] for c in corpus],
            "evaluation_corpus_comparable": [c[2] for c in corpus],
            "evaluation_corpus_missing_count": [c[3] for c in corpus],
            "evaluation_corpus_missing_digest": [c[4] for c in corpus],
            "evaluation_corpus_semantics_version": [c[5] for c in corpus],
            "evaluation_corpus_eligible": [c[6] for c in corpus],
            "evaluation_corpus_eligible_digest": [c[7] for c in corpus],
            "evaluation_corpus_requested_count": [c[8] for c in corpus],
            "evaluation_corpus_requested_digest": [c[9] for c in corpus],
            "evaluation_corpus_observation_digest": [c[10] for c in corpus],
            "evaluation_corpus_complete": [c[11] for c in corpus],
            "evaluation_corpus_integrity": [c[12] for c in corpus],
            "metric": df["metric"],
            "value": df["value"],
        }
    )
    order = ["backbone", "k", "strategy_key", "metric"]
    return enriched.sort_values(order, kind="mergesort").reset_index(drop=True)


def query_winners_metrics(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """The decoded winners/summary frame: catalog classes PLUS observed medoid baselines.

    Concatenation of :func:`query_analyze_metrics` (catalog classes) and
    :func:`query_medoid_baselines` (per-backbone observed ``global_pool:{backbone}:medoid``
    baselines), both run-scoped identically.  This enriched frame carries each cell's medoid
    baseline row so :func:`build_winner_delta_rows` (and the summary / winners sections) can
    delegate baseline/winner/delta selection to the observed medoid.  ``section_analysis`` must
    keep using the catalog-only :func:`query_analyze_metrics` frame (never this one), so the
    catalog-only pin in ``tests/test_report.py`` stays valid.
    """
    catalog = query_analyze_metrics(con, run_id=run_id)
    medoid = query_medoid_baselines(con, run_id=run_id)
    if medoid.empty:
        frame = catalog
    elif catalog.empty:
        frame = medoid
    else:
        frame = pd.concat([catalog, medoid], ignore_index=True)
    # Plan B P2: persist the run-scoped non-comparable representation diagnostics on the winners
    # frame so ``build_winner_delta_rows`` can merge them into ``attrs["baseline_incomplete"]``.
    # A run whose invocation later failed is never resolved as a clean completed run_id here, so
    # its diagnostics are excluded from clean completed-report selection by construction.
    frame.attrs["persisted_incomplete_diagnostics"] = query_incomplete_analyze_diagnostics(con, run_id=run_id)
    return frame


def query_incomplete_analyze_diagnostics(
    con,
    *,
    run_id: str | None = None,
) -> tuple[dict, ...]:
    """Return persisted non-comparable diagnostics normalized to the report incomplete shape.

    Reads the ``analyze_incomplete_diagnostics`` table (optionally restricted to *run_id*) and
    normalizes each versioned diagnostic into the EXACT report incomplete-representation mapping
    shape emitted by ``baseline._incomplete_entry``.  Each normalized entry carries the 14 derive
    keys ``report._winners_report`` renders under :data:`_INCOMPLETE_COLUMNS` (strategy/config
    identity, sim metric/K, reason, the baseline (mandatory observed medoid) vs representation
    evaluation-corpus hash/count/comparability, and the representation's missing count/digest),
    PLUS ``backbone`` and the 4 durable class-identity enrichment keys that ``_INCOMPLETE_COLUMNS``
    now also renders (``search_representation_hash`` / ``canonical_config_id`` / ``config_ids`` /
    ``missing_song_ids``).  Class identity is never the disposable view/keyset hash; ``metric``
    stays ``""`` because a non-comparable representation was never scored per-metric (it is
    representation-incomplete, not a partial metric cell).
    A non-comparable representation NEVER becomes an ``analyze_metrics`` row or complete scope, so
    it is only ever surfaced here as visibly incomplete, with no winner/delta.  Returns ``()`` when
    the table is absent or no rows match (no diagnostics == zero change to any clean report).
    """
    entries: list[dict] = []
    for row in read_incomplete_analyze_diagnostics(con, run_id=run_id):
        missing_song_ids: list[str] = []
        if row.get("missing_song_ids_json"):
            try:
                missing_song_ids = json.loads(row["missing_song_ids_json"])
            except json.JSONDecodeError:
                missing_song_ids = []
        config_ids: list[int] = []
        if row.get("config_ids_json"):
            try:
                config_ids = json.loads(row["config_ids_json"])
            except json.JSONDecodeError:
                config_ids = []
        entries.append(
            {
                "backbone": row.get("backbone") or "",
                "sim_metric": row.get("sim_metric") or "",
                "k": row.get("k") or 0,
                "metric": row.get("metric") or "",
                "strategy_key": row.get("strategy_key") or "",
                "baseline_strategy_key": row.get("baseline_strategy_key") or "",
                "reason": row.get("reason") or "",
                "baseline_evaluation_corpus_hash": row.get("baseline_evaluation_corpus_hash"),
                "baseline_evaluation_corpus_count": row.get("baseline_evaluation_corpus_count"),
                "baseline_evaluation_corpus_comparable": row.get("baseline_evaluation_corpus_comparable"),
                "representation_evaluation_corpus_hash": row.get("evaluation_corpus_hash"),
                "representation_evaluation_corpus_count": row.get("evaluation_corpus_count"),
                "representation_evaluation_corpus_comparable": row.get("evaluation_corpus_comparable"),
                "representation_missing_count": row.get("missing_count"),
                "representation_missing_digest": row.get("missing_digest"),
                # Durable class/threshold identity + tested-threshold membership (never omitted;
                # surfaced so a reader can see WHICH tested class lost songs), plus the actual lost
                # song membership.  These ride on the entry and are rendered via the incomplete
                # table's shared column set when the representation row is present.
                "search_representation_hash": row.get("search_representation_hash"),
                "canonical_config_id": row.get("canonical_config_id"),
                "config_ids": tuple(int(c) for c in config_ids) if config_ids else (),
                "missing_song_ids": tuple(str(s) for s in missing_song_ids) if missing_song_ids else (),
            }
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Analysis section renderer
# ---------------------------------------------------------------------------


def _class_table_rows(bb_df: pd.DataFrame) -> list[dict]:
    """One analysis row per (strategy_key, k, metric) cell for a backbone, alias-joined.

    Renders the full durable v2 identity surface distinctly: the SEMANTIC
    ``representation_hash`` (never a keyset), the DISPOSABLE ``view_keyset_hash`` (kept in a
    separate column so the two never look identical), the compact-catalog anchor
    (``catalog_id``/``catalog_fingerprint``), the ordered membership (``canonical_config_id`` /
    ``alias_ids`` / ``config_ids``), score/scoring-semantics versions, and the persisted
    evaluation-corpus identity + missing evidence.  All fields come directly from the durable
    scope line — nothing is inferred from a later catalog.
    """
    rows: list[dict] = []
    for _, r in bb_df.iterrows():
        corpus_hash = r.get("evaluation_corpus_hash")
        rows.append(
            {
                "run_id": fmt(r.get("run_id")) if pd.notna(r.get("run_id")) else "—",
                "strategy_key": r["strategy_key"],
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "metric": r["metric"],
                "value": float(r["value"]),
                "score_variant": r["score_variant"],
                "scoring_semantics_version": int(r["scoring_semantics_version"]),
                "canonical_config_id": fmt(r.get("canonical_config_id")),
                "alias_ids": _alias_text(r.get("alias_ids")),
                "config_ids": _alias_text(r.get("config_ids")),
                "catalog_id": fmt(r.get("catalog_id")),
                "catalog_fingerprint": fmt(r.get("catalog_fingerprint")),
                "representation_hash": fmt(r.get("representation_hash")),
                "view_keyset_hash": fmt(r.get("view_keyset_hash")),
                "view_content_hash": fmt(r.get("view_content_hash")),
                "evaluation_corpus_hash": fmt(corpus_hash) if corpus_hash is not None else "—",
                "evaluation_corpus_count": fmt(r.get("evaluation_corpus_count")),
                "evaluation_corpus_comparable": fmt(r.get("evaluation_corpus_comparable")),
                "evaluation_corpus_missing_count": fmt(r.get("evaluation_corpus_missing_count")),
                "evaluation_corpus_missing_digest": fmt(r.get("evaluation_corpus_missing_digest")),
            }
        )
    return rows


def _member_rows(bb_df: pd.DataFrame) -> list[dict]:
    """One row per (class, member) surfacing per-member configured/effective threshold, bin mode
    and exact segmentation hash directly from the durable v2 member records.

    ``bb_df`` is the enriched per-backbone frame; the enriched ``class_members`` list repeats on
    every metric row of a class, so membership is deduped per strategy_key.  Rows do NOT carry the
    strategy-key literal (kept on the main catalog table) — the semantic hash ties each member row
    back to its class.  Identity-less structural rows (no member records) yield no rows.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for _, r in bb_df.iterrows():
        sk = str(r["strategy_key"])
        if sk in seen:
            continue
        seen.add(sk)
        rows.extend(
            {
                "representation_hash": fmt(r.get("representation_hash")),
                "config_id": fmt(m.get("config_id")),
                "threshold_configured": fmt(m.get("threshold_configured")),
                "threshold_effective": fmt(m.get("threshold_effective")),
                "bin_mode": fmt(m.get("bin_mode")),
                "exact_segmentation_hash": fmt(m.get("exact_segmentation_hash")),
            }
            for m in (r.get("class_members") or [])
        )
    return rows


def _alias_text(alias_ids) -> str:
    if not alias_ids:
        return "—"
    return ",".join(str(a) for a in alias_ids)


def section_analysis(df: pd.DataFrame) -> dict:
    """Render the active catalog ``analyze_metrics`` rows into the ``analysis`` section.

    One per-backbone subsection with a table of decoded catalog rows (one per metric cell)
    carrying the full separated identity surface, plus a collapsible per-class/member table
    surfacing the per-member threshold/bin/exact-segmentation evidence.  Equal search
    representations were collapsed to one class by the analyze pipeline, so each
    ``strategy_key`` appears once per (sim_metric, k, metric) cell with its sorted alias list
    carried alongside — aliases never create duplicate metric/score rows.
    """
    if df is None or df.empty or "backbone" not in df.columns:
        return make_section(
            "analysis",
            "Catalog Analysis",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    subsections: list[dict] = []
    for backbone in sorted({str(b) for b in df["backbone"].dropna().tolist()}):
        bb_df = df[df["backbone"] == backbone]
        table_rows = _class_table_rows(bb_df)
        if not table_rows:
            continue
        tables: list[dict] = [
            make_table(
                table_rows,
                id=f"catalog_analysis_{backbone}",
                title=f"Active catalog analysis rows ({backbone})",
                collapsible=True,
                summary_text=f"{len(table_rows)} active catalog row(s)",
            )
        ]
        member_rows = _member_rows(bb_df)
        if member_rows:
            tables.append(
                make_table(
                    member_rows,
                    id=f"catalog_members_{backbone}",
                    title=f"Search-representation member evidence ({backbone})",
                    collapsible=True,
                    summary_text=f"{len(member_rows)} member row(s) (thresholds / bin / exact hash)",
                )
            )
        subsections.append(
            {
                "id": f"analysis-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [],
                "tables": tables,
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    if not subsections:
        return make_section(
            "analysis",
            "Catalog Analysis",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    return make_section(
        "analysis",
        "Catalog Analysis",
        description=(
            "Active catalog-only analyze_metrics rows: one row per (strategy_key, sim_metric, "
            "k, metric).  Each strategy_key is a collapsed search-representation class (equal "
            "representations scored once); every row renders the DURABLE SEMANTIC "
            "representation_hash distinctly from the DISPOSABLE per-run view_keyset_hash, plus "
            "the compact-catalog anchor, canonical/member/alias config ids, score/scoring "
            "versions and the persisted evaluation-corpus identity/missing evidence — all read "
            "directly from the analyze-scope v2 line, never inferred from a later catalog.  The "
            "per-class member table surfaces each member's configured/effective threshold, bin "
            "mode and exact segmentation hash.  EffNet and MusicNN are independent per-backbone "
            "populations and are never cross-averaged."
        ),
        subsections=subsections,
    )
