"""Report-command smoke: live run() over a seeded compact-catalog con.

Research-only.  Seeds an active catalog (two EffNet classes + one MusicNN class across K)
through the real analyze-scope catalog writer, plus a small songs corpus and a phase timing,
then runs the live report path and asserts the exact seven-section contract, catalog-only
analysis rows, per-backbone grouping, and zero forbidden vocabulary in every emitted section.
"""

from __future__ import annotations

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.tests._report_seed import (
    EXACT_SECTION_IDS,
    assert_no_forbidden_vocabulary,
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
    seed_phase_timing,
)


def _seed_songs(con) -> None:
    con.executemany(
        "INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("s1", "/a/x.flac", "Alice", "A", "One", "jazz"),
            ("s2", "/a/y.flac", "Alice", "A", "Two", "jazz"),
            ("s3", "/b/z.flac", "Bob", "B", "Three", "rock"),
        ],
    )


def test_report_command_smoke_seven_sections_catalog_only(con, tmp_path):
    _seed_songs(con)
    # EffNet: two classes (canonical 1 with alias 5 / canonical 3) over K in {5, 10}.
    for kk in (5, 10):
        seed_catalog(
            con,
            run_id="run-smoke",
            backbone="effnet",
            strategy_key=catalog_key("effnet", "aa"),
            k=kk,
            metrics={"map_k": 0.5, "mrr": 0.4},
            config_ids=(1, 5),
        )
        seed_catalog(
            con,
            run_id="run-smoke",
            backbone="effnet",
            strategy_key=catalog_key("effnet", "bb"),
            k=kk,
            metrics={"map_k": 0.8, "mrr": 0.7},
            config_ids=(3,),
        )
    # MusicNN: independent population.
    seed_catalog(
        con,
        run_id="run-smoke",
        backbone="musicnn",
        strategy_key=catalog_key("musicnn", "mm"),
        k=10,
        metrics={"map_k": 0.6},
    )
    # Observed medoid baselines so every segmented cell renders a winner/delta row.
    for kk in (5, 10):
        seed_medoid_baseline(con, run_id="run-smoke", backbone="effnet", k=kk, metrics={"map_k": 0.3, "mrr": 0.2})
    seed_medoid_baseline(con, run_id="run-smoke", backbone="musicnn", k=10, metrics={"map_k": 0.3})
    seed_phase_timing(con, run_ts="run-smoke", phase="report", elapsed_s=0.2)

    payload = report_run(con, tmp_path)

    # Exact seven-section set + order.
    assert [s["id"] for s in payload["sections"]] == list(EXACT_SECTION_IDS)

    # Zero forbidden vocabulary anywhere in the emitted text/keys.
    assert_no_forbidden_vocabulary(payload)

    by_id = {s["id"]: s for s in payload["sections"]}

    # Corpus populated.
    corpus = by_id["corpus"]
    assert any(int(d["value"]) == 3 for d in corpus["stats"] if d["label"] == "songs")

    # Analysis: catalog-only, per-backbone grouped, aliases not duplicated.
    analysis = by_id["analysis"]
    sub_titles = {sub["title"] for sub in analysis["subsections"]}
    assert sub_titles == {"effnet", "musicnn"}
    all_rows = []
    for sub in analysis["subsections"]:
        for tbl in sub["tables"]:
            all_rows.extend(tbl["rows"])
    text = str(all_rows)
    assert text.count(catalog_key("effnet", "aa")) == 4  # 2 K x 2 metrics, not alias-multiplied
    assert text.count("5") >= 1  # alias config 5 carried, not duplicated
    assert "catalog:effnet" in text

    # Winners: per-backbone winner/delta + factor tables.
    winners = by_id["winners"]
    winner_backbones = {sub["title"] for sub in winners["subsections"]}
    assert winner_backbones == {"effnet", "musicnn"}
    effnet_table_ids = {
        tbl["id"] for sub in winners["subsections"] if sub["title"] == "effnet" for tbl in sub["tables"]
    }
    assert {"winner_delta_effnet", "factor_classes_effnet"} <= effnet_table_ids

    # Head-analysis + provenance + efficiency sections present (may be empty-data but id correct).
    assert by_id["head-analysis"]["id"] == "head-analysis"
    assert by_id["provenance"]["id"] == "provenance"
    assert by_id["efficiency"]["id"] == "efficiency"

    # Outputs written.
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.html").exists()


def test_cli_report_smoke_resolves_completed_scope_and_writes_outputs(con, tmp_path):
    """Real run.py report CLI runner over a completed seed scope (the durable-input smoke).

    Drives ``run_mod._run_report`` — the CLI report-phase runner — with the ``report`` command's
    own freshly-generated run id.  The seeded scope ``run-smoke`` is the completed analyze run, so
    the runner must resolve and render exactly it: durable catalog identity (canonical 1 / alias
    5), the persisted ``global_pool:effnet:medoid`` baseline, run-scoped provenance, and both
    machine JSON + human HTML outputs.
    """
    _seed_songs(con)
    seed_catalog(
        con,
        run_id="run-smoke",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "aa"),
        k=5,
        metrics={"map_k": 0.55, "mrr": 0.45},
        config_ids=(1, 5),
    )
    seed_medoid_baseline(con, run_id="run-smoke", backbone="effnet", k=5, metrics={"map_k": 0.3, "mrr": 0.2})
    seed_phase_timing(con, run_ts="run-smoke", phase="report", elapsed_s=0.1)

    out = tmp_path / "cli-out"
    meta = run_mod._run_report(con, {"report_dir": str(out)}, "report-cli")
    assert meta == {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}

    import json

    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in payload["sections"]] == list(EXACT_SECTION_IDS)
    assert payload["schema_version"] == 2
    assert_no_forbidden_vocabulary(payload)

    # The resolved scope is exactly run-smoke (its analysis + provenance ledger carry it).
    text = json.dumps(payload)
    assert "run-smoke" in text
    provenance = next(s for s in payload["sections"] if s["id"] == "provenance")
    history = next(t for t in provenance["tables"] if t["id"] == "run_history")
    assert {row[0] for row in history["rows"]} == {"run-smoke"}

    # Durable identity + persisted medoid baseline consumed.
    assert '"global_pool:effnet:medoid"' in json.dumps(next(s for s in payload["sections"] if s["id"] == "winners"))
    analysis = next(s for s in payload["sections"] if s["id"] == "analysis")
    effnet_table = next(t for sub in analysis["subsections"] for t in sub["tables"])
    cols = effnet_table["columns"]
    aa_rows = [r for r in effnet_table["rows"] if r[cols.index("strategy_key")].endswith(":aa")]
    assert aa_rows
    assert aa_rows[0][cols.index("canonical_config_id")] == "1"
    assert aa_rows[0][cols.index("alias_ids")] == "5"

    assert (out / "report.json").exists()
    assert (out / "report.html").exists()
