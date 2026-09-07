"""Plan B Corrective Phase 2 spec-first report tests (research-only).

Pins the downstream-only read contract on top of the already-complete v2 data produced and
persisted by the corrective phases:

* **report meaning is independent of the current catalog pointer** — every reader derives
  catalog/corpus/semantic identity SOLELY from the persisted ``analyze_scope_v2`` provenance
  recorded on the research DB; nothing in the report/read path consults ``catalogs/current.json``
  or opens a current catalog snapshot.  Rendering is unchanged no matter where the pointer points.
* **all readers require v2** — a catalog/baseline row whose durable scope is missing, non-decodable
  or historical-v1 is surfaced as an INCOMPLETE input (semantic/identity/corpus empty, keyset never
  promoted), never silently rendered as a complete anchored metric and never a matched delta.
* **complete provenance is retained** — baseline and segmented rows carry their full v2 identity
  (semantic search_representation_hash distinct from the disposable view identity, catalog anchor,
  evaluation-corpus identity, per-member threshold/bin/exact evidence, score semantics) from the
  loader seams through to the rendered payload.
* **no identity-less structural path reaches ACTIVE reporting as complete** — the loader decision
  (pinned here): a ``structural_fixture`` / identity-less catalog row IS readable at the loader seam
  but is surfaced visibly incomplete (``representation_hash`` ``None``, no catalog anchor, no
  corpus) so it can never render as a complete catalog metric and never forms a matched delta.
* **matched deltas stay matching-only** — only an equal, comparable, finite corpus identity can win
  a cell; an unequal population is never partially matched (no silent intersection).

Research-only.  Mirrors the seeded v2 paths of ``_report_seed`` (the real analyze-scope catalog
writer) so the tests exercise the true persistence + provenance-scope read path.
"""

from __future__ import annotations

import json

from scripts.embedding_research.baseline import build_baseline_delta_rows
from scripts.embedding_research.db.analyze_scope import encode_analyze_scope_v2
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.report._retrieval import (
    query_analyze_metrics,
    query_medoid_baselines,
    query_winners_metrics,
)
from scripts.embedding_research.tests._report_seed import (
    _FIXTURE_CATALOG_FINGERPRINT,
    _FIXTURE_CATALOG_ID,
    EXACT_SECTION_IDS,
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
)

_SEMANTIC = "d" * 64


# --------------------------------------------------------------------------- #
# helpers                                                                       #
# --------------------------------------------------------------------------- #
def _section(payload, sid: str) -> dict:
    return next(s for s in payload["sections"] if s["id"] == sid)


def _all_tables(section: dict) -> list[dict]:
    tabs = list(section.get("tables") or [])
    for sub in section.get("subsections") or []:
        tabs.extend(sub.get("tables") or [])
    return tabs


def _table(section: dict, tid: str) -> dict:
    return next(t for t in _all_tables(section) if t["id"] == tid)


def _row_map(table: dict, idx: int = 0) -> dict:
    return dict(zip(table["columns"], table["rows"][idx], strict=False))


def _scope_lines(con, run_id: str) -> str:
    (blob,) = con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase='analyze'",
        (run_id,),
    ).fetchone()
    return blob or ""


def _seed_one_effnet(con, run_id: str, *, key_suffix: str, value: float = 0.8) -> None:
    seed_catalog(
        con,
        run_id=run_id,
        backbone="effnet",
        strategy_key=catalog_key("effnet", key_suffix),
        k=5,
        metrics={"map_k": value},
        config_ids=(1, 5),
        search_representation_hash=_SEMANTIC,
    )
    seed_medoid_baseline(con, run_id=run_id, backbone="effnet", k=5, metrics={"map_k": 0.5})


# --------------------------------------------------------------------------- #
# P6-S3(1): report meaning is independent of the current catalog pointer        #
# --------------------------------------------------------------------------- #
def test_report_meaning_stable_when_current_catalog_pointer_changes(con, tmp_path):
    """Rendered catalog identity is scope-derived and immune to catalogs/current.json.

    The research DB has NO catalog tables and report_run is handed only a research connection, yet
    a seeded full-v2 scope referencing ``_FIXTURE_CATALOG_ID`` renders that catalog anchor +
    semantic hash with no catalog snapshot present anywhere.  Pointing a filesystem
    ``catalogs/current.json`` at a DIFFERENT catalog (different id + fingerprint) must not alter the
    report: the readers never consult the pointer.
    """
    _seed_one_effnet(con, run_id="run-p", key_suffix="p")

    # Render with NO catalog filesystem present at all.
    a = report_run(con, tmp_path / "r1")

    # Now plant a "current catalog" on disk selecting a wholly different catalog; even if a future
    # reader tried to consult the pointer it would resolve catalog-other (different fingerprint).
    catroot = tmp_path / "catroot"
    (catroot / "catalogs" / "catalog-other-zz").mkdir(parents=True)
    (catroot / "catalogs" / "current.json").write_text(
        json.dumps({"catalog_id": "catalog-other-zz", "catalog_fingerprint": "beef" * 4})
    )

    # Render the SAME seeded scope again with the pointer present and pointing elsewhere.
    b = report_run(con, tmp_path / "r2")

    # The rendered analysis identity is the persisted scope's, never the filesystem pointer's.
    a_analysis = _table(_section(a, "analysis"), "catalog_analysis_effnet")
    row = _row_map(a_analysis)
    assert row["catalog_id"] == _FIXTURE_CATALOG_ID
    assert row["catalog_fingerprint"] == _FIXTURE_CATALOG_FINGERPRINT
    assert row["representation_hash"] == _SEMANTIC

    # Report meaning (section structure + every rendered row) is byte-identical with vs without the
    # pointer, and regardless of where the pointer points.  run_ts is the only varying top-level key.
    assert [s["id"] for s in a["sections"]] == list(EXACT_SECTION_IDS)
    assert a["sections"] == b["sections"]


# --------------------------------------------------------------------------- #
# P6-S3(2): all readers require v2 — missing / non-decodable scope is surfaced  #
# --------------------------------------------------------------------------- #
def test_missing_v2_scope_surfaced_incomplete_never_complete(con, tmp_path):
    """A catalog analyze row with NO recorded v2 scope is incomplete, never a semantic class."""
    # Write a bare catalog analyze_metrics row with a well-formed catalog key but NO scope line.
    from scripts.embedding_research import db

    run_id = "run-noscope"
    db.write_analyze_metrics(
        con,
        catalog_key("effnet", "noscope"),
        "catalog",
        "cosine",
        5,
        {"map_k": 0.9},
        run_id=run_id,
    )
    # A medoid baseline WITH corpus so the matching gate has a corpus side to compare against.
    seed_medoid_baseline(con, run_id=run_id, backbone="effnet", k=5, metrics={"map_k": 0.5})

    frame = query_analyze_metrics(con, run_id=run_id)
    assert len(frame) == 1
    row = frame.iloc[0]
    # No durable semantic / catalog identity, and the disposable keyset is NOT promoted to semantic.
    assert row["representation_hash"] is None
    assert row["catalog_id"] is None
    assert row["catalog_fingerprint"] is None
    assert row["view_keyset_hash"] == "noscope"  # disposable key rides ONLY in view_keyset_hash
    assert row["evaluation_corpus_hash"] is None

    # Through the winners path the identity-less class can never match: it is surfaced incomplete.
    wdf = query_winners_metrics(con, run_id=run_id)
    base = build_baseline_delta_rows(wdf)
    assert base.rows == ()
    assert len(base.incomplete) == 1
    assert base.incomplete[0]["strategy_key"] == catalog_key("effnet", "noscope")

    # Rendered: no matched winner delta references it; it is surfaced in the incomplete table.
    payload = report_run(con, tmp_path)
    winners = _section(payload, "winners")
    assert not any(t["id"].startswith("winner_delta_effnet") for t in _all_tables(winners))
    incomplete = _table(winners, "incomplete_representations_effnet")
    keys = [dict(zip(incomplete["columns"], r, strict=False))["strategy_key"] for r in incomplete["rows"]]
    assert catalog_key("effnet", "noscope") in keys


def test_non_decodable_historical_scope_surfaced_incomplete(con):
    """A catalog row whose scope line is not a decodable analyze_scope_v2 is incomplete.

    Simulates a historical-v1 / corrupted provenance line sitting on the run: ``parse_analyze_scope``
    returns ``None`` for it, the reader never reinterprets it as current identity, and the row is
    surfaced visibly incomplete (never a promoted semantic, never a matched delta).
    """
    _seed_one_effnet(con, run_id="run-legacy", key_suffix="legacy")
    # Corrupt the single recorded v2 scope line into a non-decodable (legacy-flavored) blob.
    blob = _scope_lines(con, "run-legacy")
    assert blob.startswith("analyze_scope_v2|")
    con.execute(
        "UPDATE run_provenance SET output_artifact_hashes=? WHERE run_id=? AND phase='analyze'",
        ("analyze_scope_v1|legacy|identity|line", "run-legacy"),
    )

    frame = query_analyze_metrics(con, run_id="run-legacy")
    assert len(frame) == 1
    row = frame.iloc[0]
    # The non-decodable line yields NO semantic identity; the disposable keyset is not promoted.
    assert row["representation_hash"] is None
    assert row["catalog_id"] is None
    assert row["config_ids"] == []
    assert row["view_keyset_hash"] == "legacy"

    # It can never be a matched delta against the (corpus-bearing) baseline.
    result = build_baseline_delta_rows(query_winners_metrics(con, run_id="run-legacy"))
    assert result.rows == ()
    assert any(catalog_key("effnet", "legacy") == e["strategy_key"] for e in result.incomplete)


# --------------------------------------------------------------------------- #
# P6-S3(3): baseline + segmented rows retain complete provenance to the payload #
# --------------------------------------------------------------------------- #
def test_segmented_and_baseline_retain_full_provenance_through_loaders(con, tmp_path):
    """Both the segmented class and the observed-medoid baseline reach the rendered payload with
    their full v2 identity: semantic hash distinct from disposable view identity, catalog anchor,
    evaluation-corpus identity, and score semantics."""
    _seed_one_effnet(con, run_id="run-full", key_suffix="f")

    # Loader seam: the segmented class carries the full durable semantic identity...
    seg = query_analyze_metrics(con, run_id="run-full").iloc[0]
    assert seg["representation_hash"] == _SEMANTIC
    assert seg["representation_hash"] != seg["view_keyset_hash"]
    assert seg["catalog_id"] == _FIXTURE_CATALOG_ID
    assert seg["config_ids"] == [1, 5]
    assert seg["evaluation_corpus_hash"]
    # ...and the medoid baseline carries ITS catalog anchor + corpus + score semantics (no class id).
    med = query_medoid_baselines(con, run_id="run-full").iloc[0]
    assert med["catalog_id"] == _FIXTURE_CATALOG_ID
    assert med["catalog_fingerprint"] == _FIXTURE_CATALOG_FINGERPRINT
    assert med["evaluation_corpus_hash"] == seg["evaluation_corpus_hash"]
    assert med["score_variant"] == "max_per_candidate_segment"
    assert med["representation_hash"] is None
    assert med["config_ids"] == []

    # Rendered payload: the analysis table carries the class's semantic distinct from view keyset.
    payload = report_run(con, tmp_path)
    main = _table(_section(payload, "analysis"), "catalog_analysis_effnet")
    arow = _row_map(main)
    assert arow["representation_hash"] == _SEMANTIC
    assert arow["view_keyset_hash"] == "f"
    assert arow["representation_hash"] != arow["view_keyset_hash"]
    assert arow["catalog_id"] == _FIXTURE_CATALOG_ID
    # The equal-corpus class + baseline form a matched delta whose baseline identity is carried.
    winners = _section(payload, "winners")
    delta = _table(winners, "winner_delta_effnet")
    drow = _row_map(delta)
    assert drow["winner_strategy_key"] == catalog_key("effnet", "f")
    assert drow["baseline_strategy_key"].endswith(":medoid")


# --------------------------------------------------------------------------- #
# P6-S3(4): no identity-less structural path reaches ACTIVE reporting as complete
# --------------------------------------------------------------------------- #
def test_structural_fixture_loader_decision_readable_but_never_complete(con, tmp_path):
    """DECIDED loader treatment (pinned): a structural_fixture / identity-less catalog row IS
    readable by the loader seam but is surfaced VISIBLY INCOMPLETE — representation_hash None, no
    catalog anchor, no corpus — so it can never render as a complete catalog metric and never forms
    a matched delta.  The disposable keyset is never promoted to semantic.
    """
    run_id = "run-struct"
    structural_key = catalog_key("effnet", "struct")
    seed_catalog(
        con,
        run_id=run_id,
        backbone="effnet",
        strategy_key=structural_key,
        k=5,
        metrics={"map_k": 0.95},  # highest value on the backbone — must still never "win"
        catalog_id="",  # genuinely identity-less structural fixture (no semantic/members/anchor)
    )
    seed_medoid_baseline(con, run_id=run_id, backbone="effnet", k=5, metrics={"map_k": 0.5})

    # Loader seam: readable, but visibly incomplete.
    frame = query_analyze_metrics(con, run_id=run_id)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["strategy_key"] == structural_key
    assert row["representation_hash"] is None  # never a semantic; keyset NOT promoted
    assert row["catalog_id"] is None
    assert row["catalog_fingerprint"] is None
    # A structural fixture carries its config membership but no catalog anchor, no per-member
    # threshold/bin/exact evidence and no semantic hash (represented BY THE structural_fixture tag).
    assert row["config_ids"] == [1]
    assert row["class_members"] == []
    assert row["view_keyset_hash"] == "struct"  # disposable key rides only in view_keyset_hash
    assert row["evaluation_corpus_hash"] is None

    # It carries no corpus => against the corpus-bearing baseline it is a one-sided comparison that
    # can never match (matching-only gate).  The highest-value structural class wins NO cell.
    result = build_baseline_delta_rows(query_winners_metrics(con, run_id=run_id))
    assert result.rows == ()
    inc = next(e for e in result.incomplete if e["strategy_key"] == structural_key)
    assert "only one side" in inc["reason"]

    # Rendered ACTIVE report: no matched winner delta cites the structural class; it is surfaced in
    # the incomplete table; the factor roster keeps its keyset only in view_keyset_hash (never
    # semantic).
    payload = report_run(con, tmp_path)
    winners = _section(payload, "winners")
    assert not any(t["id"].startswith("winner_delta_effnet") for t in _all_tables(winners))
    incomplete = _table(winners, "incomplete_representations_effnet")
    inc_keys = [dict(zip(incomplete["columns"], r, strict=False))["strategy_key"] for r in incomplete["rows"]]
    assert structural_key in inc_keys

    factor = _table(winners, "factor_classes_effnet")
    frow = _row_map(factor)
    assert frow["strategy_key"] == structural_key
    # In the RENDERED payload an empty value is formatted as the visible '—' incomplete marker.
    assert frow["representation_hash"] == "—"
    assert frow["view_keyset_hash"] == "struct"
    assert frow["catalog_id"] == "—"


# --------------------------------------------------------------------------- #
# P6-S3(5): matched deltas stay matching-only under corpus identity rules        #
# --------------------------------------------------------------------------- #
def test_matched_deltas_remain_matching_only_reader_end_to_end(con, tmp_path):
    """End-to-end through the readers: only an equal, comparable corpus identity produces a matched
    delta; an unequal population is never partially matched (no silent intersection)."""
    # Two runs on the same backbone: run-eq has an equal-population class + baseline (matches);
    # run-ne has an unequal-population class whose corpus shares 3/4 songs with its baseline and
    # must NEVER partially match.
    from scripts.embedding_research.catalog_identity import (
        EVALUATION_CORPUS_SEMANTICS_VERSION,
        EvaluationCorpusIdentity,
    )

    def _corp(songs, ch, missing=(), comparable=True):
        return EvaluationCorpusIdentity(
            backbone="effnet",
            song_ids=tuple(sorted(songs)),
            corpus_hash=ch,
            count=len(songs),
            eligible=True,
            comparable=comparable,
            missing_song_ids=tuple(sorted(missing)),
            missing_count=len(missing),
            missing_digest="x" * 8 if missing else None,
            semantics_version=EVALUATION_CORPUS_SEMANTICS_VERSION,
        )

    # run-eq: class {a,b,c,d} == baseline {a,b,c,d} -> match.
    eq = _corp(["a", "b", "c", "d"], "same-corp")
    seed_catalog(
        con,
        run_id="run-eq",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "eq"),
        k=5,
        metrics={"map_k": 0.8},
        evaluation_corpus=eq,
    )
    seed_medoid_baseline(con, run_id="run-eq", backbone="effnet", k=5, metrics={"map_k": 0.5}, evaluation_corpus=eq)
    payload = report_run(con, tmp_path / "eq")
    delta = _row_map(_table(_section(payload, "winners"), "winner_delta_effnet"))
    assert delta["winner_strategy_key"] == catalog_key("effnet", "eq")

    # run-ne (isolated on backbone 'mobilenet' so its cell does not collide with run-eq's effnet cell
    # in the whole-table read): class {a,b,c,d} (0.9) vs baseline {a,b,c,d,z} (0.5).  The shared
    # subset {a,b,c,d} must not silently intersect => no matched delta, surfaced incomplete.
    seg4 = _corp(["a", "b", "c", "d"], "seg-4")
    base5 = _corp(["a", "b", "c", "d", "z"], "base-5")
    seed_catalog(
        con,
        run_id="run-ne",
        backbone="mobilenet",
        strategy_key=catalog_key("mobilenet", "ne"),
        k=5,
        metrics={"map_k": 0.9},
        evaluation_corpus=seg4,
    )
    seed_medoid_baseline(
        con, run_id="run-ne", backbone="mobilenet", k=5, metrics={"map_k": 0.5}, evaluation_corpus=base5
    )
    payload = report_run(con, tmp_path / "ne")
    winners = _section(payload, "winners")
    assert not any(t["id"].startswith("winner_delta_mobilenet") for t in _all_tables(winners))
    incomplete = _table(winners, "incomplete_representations_mobilenet")
    inc = next(
        dict(zip(incomplete["columns"], r, strict=False))
        for r in incomplete["rows"]
        if dict(zip(incomplete["columns"], r, strict=False))["strategy_key"] == catalog_key("mobilenet", "ne")
    )
    assert "differs" in inc["reason"]
    assert inc["representation_evaluation_corpus_hash"] == "seg-4"
    assert inc["baseline_evaluation_corpus_hash"] == "base-5"


# --------------------------------------------------------------------------- #
# P6-S3(2b): the whole-reader require-v2 gate also applies at the run_id=None seam
# --------------------------------------------------------------------------- #
def test_v2_scope_roundtrip_is_single_schema_on_read_rows(con):
    """Sanity: every seeded scope line is a decodable analyze_scope_v2 record (encode round-trips);
    the reader seam only ever hands the loaders v2 provenance."""
    run_id = "run-roundtrip"
    _seed_one_effnet(con, run_id=run_id, key_suffix="rt")
    from scripts.embedding_research.db.analyze_scope import decode_analyze_scope_v2

    for line in _scope_lines(con, run_id).splitlines():
        assert line.startswith("analyze_scope_v2|")
        decoded = decode_analyze_scope_v2(line.strip())
        assert decoded is not None
        assert encode_analyze_scope_v2(decoded) == line.strip()
