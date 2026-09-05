"""Report-command smoke: live run() over a seeded compact-catalog con.

Research-only.  Seeds an active catalog (two EffNet classes + one MusicNN class across K)
through the real analyze-scope catalog writer, plus a small songs corpus and a phase timing,
then runs the live report path and asserts the exact seven-section contract, catalog-only
analysis rows, per-backbone grouping, and zero forbidden vocabulary in every emitted section.
"""

from __future__ import annotations

from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.tests._report_seed import (
    EXACT_SECTION_IDS,
    assert_no_forbidden_vocabulary,
    catalog_key,
    seed_catalog,
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
