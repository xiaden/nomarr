"""Report CLI durable-input tests through the real ``run.py::_run_report`` path.

Research-only.  Drives the actual report CLI runner (``run_mod._run_report``) against a
DuckDB database seeded with a COMPLETED run scope that carries the MANDATORY observed-medoid-
baseline semantics (unconditional — no emit key) — durable catalog identity, recomputed equivalence
classes / sorted aliases, persisted MANDATORY ``global_pool:{backbone}:medoid`` baselines +
per-class deltas, run-scoped catalog metrics, canonical head provenance/results, and
command/artifact provenance.  Asserts the emitted ``report.json`` + ``report.html`` consume
exactly that active scope and NO other (no run blending), that incomplete scopes are rejected
rather than silently blended, and that the report CLI path performs no report-time
inference/audio/model/ONNX/CUDA access (structural + behavioral guards).

The completion/scope-resolution signal lives in ``run_provenance`` (there is no status column on
``analyze_metrics``), so every run below seeds an ``analyze`` provenance row with an explicit
``finished_at`` to make resolution deterministic.
"""

from __future__ import annotations

import builtins
import json

import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db.head_phase import HeadPhaseProvenanceRow, write_head_phase_provenance
from scripts.embedding_research.db.provenance import write_run_provenance
from scripts.embedding_research.tests._report_seed import (
    EXACT_SECTION_IDS,
    assert_no_forbidden_vocabulary,
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
    seed_phase_timing,
)

# Distinct command/artifact/config provenance so a durable report provably carries them.
_CONFIG_HASH = "deadbeefcafe0001"
_COMMANDS = {
    "catalog": "python run.py catalog",
    "catalog-report": "python run.py catalog-report",
    "analyze": "python run.py analyze",
    "head-analysis": "python run.py head-analysis",
    "report": "python run.py report",
}
_BASE_MS = 1_700_000_000_000  # stable integer-ms anchor (deterministic)


def _seed_songs(con, *, n=3) -> None:
    # A single artist so disc_artist_warning emits a real warning (durable warnings section).
    con.executemany(
        "INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
        [(f"s{i}", f"/audio/s{i}.flac", "Alice", "A", f"Title {i}", "jazz") for i in range(1, n + 1)],
    )


def _seed_head_provenance(con, run_id: str) -> None:
    rows = [
        HeadPhaseProvenanceRow(
            run_id=run_id,
            config_id=1,
            backbone="effnet",
            head=head,
            bin_mode="temporal_global",
            threshold_configured=0.7,
            threshold_effective=0.7,
            semantics="direct_l2",
            status="done",
            n_songs=3,
            n_pooled=3,
            finite=True,
            reference_corpus_hash="ref-corpus-effnet",
        )
        for head in ("genre", "mood_happy")
    ]
    write_head_phase_provenance(con, rows)


def _seed_run(
    con, *, run_id: str, idx: int, classes: list[dict], medoid: dict[str, dict], seed_heads: bool = False
) -> None:
    """Seed one coherent COMPLETED run scope: catalog classes + baselines + provenance + heads.

    The ``analyze`` provenance row is pre-created (status ``complete``) with an explicit
    ``finished_at`` so the report-phase resolver deterministically orders runs by ``idx``, then
    ``write_catalog_analyze_rows`` (via ``seed_catalog``) appends its ``analyze_scope_v2`` lines
    to that single row — the exact durable identity the report provenance scope-mapping consumes.
    """
    started = _BASE_MS + idx * 10_000
    write_run_provenance(
        con,
        run_id=run_id,
        phase="analyze",
        status="complete",
        started_at=started,
        finished_at=started + 6_000,
        command_line=_COMMANDS["analyze"],
        config_hash=_CONFIG_HASH,
        song_count=3,
    )
    for cls in classes:
        for kk in cls["k_values"]:
            seed_catalog(
                con,
                run_id=run_id,
                backbone=cls["backbone"],
                strategy_key=catalog_key(cls["backbone"], cls["keyset"]),
                k=kk,
                metrics=cls["metrics"],
                config_ids=cls["config_ids"],
            )
    for backbone, med_metrics in medoid.items():
        values = {m: v for m, v in med_metrics.items() if m != "k_values"}
        for kk in med_metrics.get("k_values", (5, 10)):
            seed_medoid_baseline(con, run_id=run_id, backbone=backbone, k=kk, metrics=values)
    for phase, cmd in _COMMANDS.items():
        if phase == "analyze":
            continue  # self-recorded above by the analyze producer
        ph_started = started + 1_000
        write_run_provenance(
            con,
            run_id=run_id,
            phase=phase,
            status="completed",
            started_at=ph_started,
            finished_at=ph_started + 1_500,
            input_artifact_hashes=f"{phase}-in-{run_id}",
            output_artifact_hashes=f"{phase}-out-{run_id}",
            config_hash=_CONFIG_HASH,
            song_count=3,
            warning_count=1,
            command_line=cmd,
        )
    if seed_heads:
        _seed_head_provenance(con, run_id)
        seed_phase_timing(con, run_ts=run_id, phase="report", elapsed_s=0.2)


_ACTIVE_CLASSES = [
    # EffNet: canonical 1 with alias 5 over K in {5,10} — exercises sorted alias identity.
    {
        "backbone": "effnet",
        "keyset": "aa",
        "config_ids": (1, 5),
        "k_values": (5, 10),
        "metrics": {"map_k": 0.55, "mrr": 0.45},
    },
    {
        "backbone": "effnet",
        "keyset": "bb",
        "config_ids": (3,),
        "k_values": (5, 10),
        "metrics": {"map_k": 0.82, "mrr": 0.71},
    },
    {"backbone": "musicnn", "keyset": "mm", "config_ids": (1,), "k_values": (10,), "metrics": {"map_k": 0.6}},
]
_ACTIVE_MEDOID = {
    "effnet": {"map_k": 0.3, "mrr": 0.25, "k_values": (5, 10)},
    "musicnn": {"map_k": 0.3, "k_values": (10,)},
}
_OLD_CLASSES = [{"backbone": "effnet", "keyset": "zz", "config_ids": (9,), "k_values": (5,), "metrics": {"map_k": 0.1}}]
_OLD_MEDOID = {"effnet": {"map_k": 0.05, "k_values": (5,)}}


def _load_section(payload: dict, sid: str) -> dict:
    return next(s for s in payload["sections"] if s["id"] == sid)


def test_cli_report_resolves_active_completed_scope_and_consumes_durable_inputs(con, tmp_path):
    """No run id requested -> the active (latest) completed analyze scope is resolved + rendered.

    report.json must carry durable catalog identity, recomputed aliases, medoid baseline/deltas,
    run-scoped metrics, head provenance/results, and command/artifact hashes — and MUST NOT leak a
    different (older) run into the catalog/summary/winners/provenance sections.
    """
    _seed_songs(con)
    _seed_run(con, run_id="run-old", idx=0, classes=_OLD_CLASSES, medoid=_OLD_MEDOID)
    _seed_run(con, run_id="run-active", idx=1, classes=_ACTIVE_CLASSES, medoid=_ACTIVE_MEDOID, seed_heads=True)

    out = tmp_path / "out-active"
    cfg = {"report_dir": str(out)}
    meta = run_mod._run_report(con, cfg, "report-1")
    assert meta == {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}

    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in payload["sections"]] == list(EXACT_SECTION_IDS)
    assert payload["schema_version"] == 2
    assert_no_forbidden_vocabulary(payload)
    assert payload["warnings"], "a single-artist corpus must surface a report warning"

    text = json.dumps(payload)

    # Durable catalog identity + recomputed sorted aliases of the ACTIVE run only.
    analysis = _load_section(payload, "analysis")
    atext = json.dumps(analysis)
    assert catalog_key("effnet", "aa") in atext
    assert catalog_key("effnet", "bb") in atext
    assert catalog_key("effnet", "zz") not in atext  # older run's class never blended in
    # Equivalence-class identity: the effnet:aa class (configs 1,5) is canonical 1 with alias 5.
    effnet_table = next(t for sub in analysis["subsections"] for t in sub["tables"] if t["id"].endswith("effnet"))
    _cols = effnet_table["columns"]
    _i_sk, _i_cc, _i_al = _cols.index("strategy_key"), _cols.index("canonical_config_id"), _cols.index("alias_ids")
    aa_rows = [r for r in effnet_table["rows"] if str(r[_i_sk]).endswith(":aa")]
    assert aa_rows
    assert aa_rows[0][_i_cc] == "1"
    assert aa_rows[0][_i_al] == "5"

    # Medoid baseline + finite per-representation deltas (persisted rows, never recomputed).
    wtext = json.dumps(_load_section(payload, "winners"))
    assert '"global_pool:effnet:medoid"' in wtext

    # Run-scoped metrics + identity carried; the old run is absent from the catalog-driven
    # sections and the provenance ledger (never blended into the resolved active scope).
    for sid in ("summary", "analysis", "winners", "provenance"):
        assert "run-old" not in json.dumps(_load_section(payload, sid))
    assert "run-active" in json.dumps(_load_section(payload, "analysis"))  # run_id column carried
    assert "run-active" in json.dumps(_load_section(payload, "provenance"))  # run history ledger

    # Canonical head provenance/results present.
    htext = json.dumps(_load_section(payload, "head-analysis"))
    assert "genre" in htext and "mood_happy" in htext

    # Command/artifact hashes + run history present.
    assert _CONFIG_HASH in text
    assert "python run.py report" in text
    assert "report-out-run-active" in text

    # HTML shell is schema-v2-wired so it consumes the same durable payload at view time.
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "renderSection" in html
    assert "schema_version" in html
    assert str(payload["schema_version"]) in html  # the shell's expected version == 2


def test_cli_report_explicit_completed_scope_is_honoured_no_blend(con, tmp_path):
    """An explicitly requested completed scope (cfg['report_run_id']) is rendered verbatim.

    Requesting the OLD run renders ONLY its rows — proving explicit selection never pulls the
    active run in and never blends.
    """
    _seed_songs(con)
    _seed_run(con, run_id="run-old", idx=0, classes=_OLD_CLASSES, medoid=_OLD_MEDOID)
    _seed_run(con, run_id="run-active", idx=1, classes=_ACTIVE_CLASSES, medoid=_ACTIVE_MEDOID, seed_heads=True)

    out = tmp_path / "out-old"
    meta = run_mod._run_report(con, {"report_dir": str(out), "report_run_id": "run-old"}, "report-2")
    assert meta == {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}

    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert_no_forbidden_vocabulary(payload)
    atext = json.dumps(_load_section(payload, "analysis"))
    assert catalog_key("effnet", "zz") in atext
    assert catalog_key("effnet", "aa") not in atext
    assert "run-old" in json.dumps(_load_section(payload, "provenance"))


def test_cli_report_rejects_incomplete_scope_rather_than_blending(con, tmp_path):
    """Run-scoped analyze rows with NO completed analyze scope must be rejected, not whole-set."""
    _seed_songs(con)
    _seed_run(con, run_id="orphan", idx=0, classes=_OLD_CLASSES, medoid=_OLD_MEDOID)
    # Delete the analyze provenance row: catalog rows exist but no completed analyze scope remains.
    con.execute("DELETE FROM run_provenance WHERE run_id = 'orphan' AND phase = 'analyze'")

    out = tmp_path / "out-orphan"
    with pytest.raises(run_mod._MissingArtifactError) as exc:
        run_mod._run_report(con, {"report_dir": str(out)}, "report-3")
    assert "completed analyze scope" in str(exc.value)
    assert not (out / "report.json").exists()


def test_cli_report_rejects_explicit_requested_scope_not_completed(con, tmp_path):
    """An explicitly requested run that is not a completed analyze scope is rejected (fail closed)."""
    _seed_songs(con)
    _seed_run(con, run_id="run-active", idx=0, classes=_ACTIVE_CLASSES, medoid=_ACTIVE_MEDOID, seed_heads=True)
    out = tmp_path / "out-bogus"
    with pytest.raises(run_mod._MissingArtifactError) as exc:
        run_mod._run_report(con, {"report_dir": str(out), "report_run_id": "bogus-run"}, "report-4")
    assert "not a completed analyze scope" in str(exc.value)


def test_cli_report_empty_db_renders_empty_report(con, tmp_path):
    """No run-scoped analyze rows and no explicit scope -> empty report (matches CLI semantics)."""
    out = tmp_path / "out-empty"
    meta = run_mod._run_report(con, {"report_dir": str(out)}, "report-5")
    assert meta == {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in payload["sections"]] == list(EXACT_SECTION_IDS)
    for sid in ("summary", "analysis", "winners"):
        assert _load_section(payload, sid).get("empty_message")


def test_cli_report_never_reaches_inference_audio_model_session(con, tmp_path, monkeypatch):
    """Structural + behavioral guard: the report CLI path performs no inference/audio/ONNX/CUDA.

    Any banned-runtime import or inference/audio entry-point call during ``_run_report`` must
    raise, proving the report renders verbatim from persisted rows (never recomputes).
    """
    import scripts.embedding_research.common.embed as _embed_mod
    import scripts.embedding_research.common.infer_heads as _heads_mod
    from scripts.embedding_research import config as _config_mod

    _seed_songs(con)
    _seed_run(con, run_id="run-active", idx=0, classes=_ACTIVE_CLASSES, medoid=_ACTIVE_MEDOID, seed_heads=True)

    real_import = builtins.__import__
    banned_runtime = {"onnxruntime", "torch", "essentia", "tensorflow", "librosa"}

    def _guarded_import(name, *a, **k):
        if name.split(".")[0] in banned_runtime:
            raise AssertionError(f"report CLI reached a banned runtime import: {name}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    def _forbidden(*_a, **_k):
        raise AssertionError("report CLI must never run inference / audio / model access")

    monkeypatch.setattr(_embed_mod, "embed", _forbidden)
    monkeypatch.setattr(_heads_mod, "infer_heads", _forbidden)
    monkeypatch.setattr(_config_mod, "discover_audio", _forbidden)

    out = tmp_path / "out-cpu"
    meta = run_mod._run_report(con, {"report_dir": str(out)}, "report-6")
    assert meta["output_artifact_hashes"] == "report.json,report.html"
    assert (out / "report.json").exists()
    assert (out / "report.html").exists()
