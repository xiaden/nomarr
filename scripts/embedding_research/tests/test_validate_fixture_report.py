"""Schema-v2 fixture-report validator tests (research-only).

Validates the rewritten :mod:`generate_fixture_report` / :mod:`validate_fixture_report`
contract: a generated fixture ``report.json`` must expose EXACTLY the seven sections, active
catalog-only rows, separate EffNet and MusicNN backbone populations, deterministic
winner/delta/factor tables, sorted alias ids, finite values, the synthetic-fixture
warning/limitations, and zero forbidden legacy vocabulary.  These are real passing tests
over self-contained generated fixtures (never skipped); the committed/external fixture is
regenerated and validated as a coupled-verification gate rather than a unit dependency.
"""

from __future__ import annotations

import json

import pytest

from scripts.embedding_research import generate_fixture_report as gen
from scripts.embedding_research import validate_fixture_report as validator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_fixture(tmp_path) -> object:
    """Regenerate the deterministic synthetic fixture report.json into *tmp_path*."""
    return gen.main(tmp_path)  # returns the report.json path


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sections(payload) -> dict:
    return {s["id"]: s for s in payload["sections"]}


# ---------------------------------------------------------------------------
# Positive: full fixture validates (the restored active fixture test)
# ---------------------------------------------------------------------------


def test_full_fixture_validates_effnet_and_musicnn_populations(tmp_path):
    """The previously-skipped fixture test, restored as a REAL passing test.

    Validates the complete EffNet AND MusicNN fixture under the schema-v2 contract — no
    skip, no 'ctp' token in the name.  The validator must return None (no raise).
    """
    path = _generate_fixture(tmp_path)
    validator.validate_fixture_report(path)  # must not raise

    payload = _load(path)
    by_id = _sections(payload)
    assert [s["id"] for s in payload["sections"]] == list(validator.EXACT_SECTION_IDS)

    # Separate backbone populations in analysis and winners.
    assert {s["title"] for s in by_id["analysis"]["subsections"]} == {"effnet", "musicnn"}
    assert {s["title"] for s in by_id["winners"]["subsections"]} == {"effnet", "musicnn"}

    # Summary reports both backbones.
    status = next(t for t in by_id["summary"]["tables"] if t["id"] == "catalog_result_status")
    assert {r[0] for r in status["rows"]} == {"effnet", "musicnn"}

    # Canonical head provenance present for the EffNet surface.
    heads = by_id["head-analysis"]
    head_tables = {t["id"] for sub in heads.get("subsections", []) for t in sub.get("tables", [])}
    assert "head_phase_provenance_effnet" in head_tables


# ---------------------------------------------------------------------------
# Generator DB-level contract (in-memory, current schema)
# ---------------------------------------------------------------------------


def test_generator_db_contract_phase_timings_only_exact_phase_names():
    con = gen.build_fixture_con()
    try:
        rows = con.execute("SELECT DISTINCT phase FROM phase_timings").fetchall()
        phases = {r[0] for r in rows}
        assert phases <= set(gen.PHASE_NAMES), (
            f"unexpected phase names in fixture timings: {phases - set(gen.PHASE_NAMES)}"
        )
        # Both the active and the historical run_ts are present (timing-history pivot).
        run_ts = con.execute("SELECT DISTINCT run_ts FROM phase_timings").fetchall()
        assert {r[0] for r in run_ts} == {"fixture-v2-previous", "fixture-v2-run"}
    finally:
        con.close()


def test_generator_db_contract_only_retained_tables():

    con = gen.build_fixture_con()
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        expected = {
            "analyze_metrics",
            "catalog_metadata",
            "corpus_state",
            "head_phase_provenance",
            "head_stream_registry",
            "phase_timings",
            "run_provenance",
            "song_retrieval_metrics",
            "songs",
            "stream_registry",
        }
        assert tables == expected
    finally:
        con.close()


def test_generator_db_contract_head_provenance_is_canonical_catalog_scoped():
    con = gen.build_fixture_con()
    try:
        rows = con.execute(
            "SELECT backbone, boundary_source, head_pool_variant, threshold, config_id FROM head_phase_provenance"
        ).fetchall()
        assert rows, "fixture must carry canonical head provenance"
        for backbone, boundary, pool, threshold, config_id in rows:
            assert backbone == "effnet"
            assert boundary == "catalog"
            assert pool == "shared_catalog_boundary"
            assert threshold is None
            assert config_id is not None
    finally:
        con.close()


def test_generator_never_inserts_removed_tables():
    import duckdb

    # Current schema DDL creates none of the removed tables.
    con = duckdb.connect(":memory:")
    from scripts.embedding_research.db._schema import ensure_schema

    ensure_schema(con)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    removed = {
        "pooled_vecs",
        "head_results",
        "head_agreement_rows",
        "patch_features",
        "binned_pair_sims",
        "binned_classify_ctp",
        "binned_song_stats",
        "truncation_robustness_rows",
        "binned_ctp_vecs",
        "binned_ptc_ctp_metrics",
        "head_sim_corr_rows",
        "binned_calibration",
        "stratified_corpus",
    }
    assert tables.isdisjoint(removed)


# ---------------------------------------------------------------------------
# Validator failure modes
# ---------------------------------------------------------------------------


def test_validator_rejects_missing_path(tmp_path):
    with pytest.raises(ValueError):
        validator.validate_fixture_report(tmp_path / "does-not-exist.json")


def test_validator_rejects_missing_synthetic_warning(tmp_path):
    path = _generate_fixture(tmp_path)
    data = _load(path)
    data["warnings"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "synthetic-fixture" in str(exc.value)


def test_validator_rejects_wrong_section_set(tmp_path):
    path = _generate_fixture(tmp_path)
    data = _load(path)
    data["sections"] = [s for s in data["sections"] if s["id"] != "efficiency"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "section ids/order mismatch" in str(exc.value)


def test_validator_rejects_forbidden_legacy_vocabulary(tmp_path):
    path = _generate_fixture(tmp_path)
    data = _load(path)
    data["title"] = "Embedding Research Report (ptc)"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "forbidden legacy vocabulary" in str(exc.value)


def test_validator_rejects_non_finite_literal(tmp_path):
    path = _generate_fixture(tmp_path)
    _load(path)
    # Force a raw non-finite literal into the serialized payload.
    text = path.read_text(encoding="utf-8").replace('"0.8200"', '"NaN"', 1)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "non-finite" in str(exc.value)


def test_validator_rejects_non_catalog_strategy_row(tmp_path):
    path = _generate_fixture(tmp_path)
    data = _load(path)
    analysis = next(s for s in data["sections"] if s["id"] == "analysis")
    for sub in analysis["subsections"]:
        if sub["title"] == "musicnn":
            for table in sub["tables"]:
                if table["id"] == "catalog_analysis_musicnn":
                    scol = table["columns"].index("strategy_key")
                    table["rows"][0][scol] = "search:" + table["rows"][0][scol].split(":", 1)[1]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "non-catalog strategy" in str(exc.value)


def test_validator_rejects_empty_corpus(tmp_path):
    path = _generate_fixture(tmp_path)
    data = _load(path)
    corpus = next(s for s in data["sections"] if s["id"] == "corpus")
    for stat in corpus["stats"]:
        if stat["label"] == "songs":
            stat["value"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        validator.validate_fixture_report(path)
    assert "positive active song count" in str(exc.value)
