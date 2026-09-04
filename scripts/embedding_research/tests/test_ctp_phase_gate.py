"""Phase-level CTP archival gate tests (Plan E, P2-S1 / DD line 233, U6).

The default run has ``[archival_ctp] enabled=false``.  These tests drive the
``run.py`` / ``classify.py`` orchestration surfaces and assert that a disabled
default performs ZERO CTP work and creates ZERO CTP artifacts:

* ``run._segment_phase`` never builds CTP segment infra and never invokes the
  CTP segmenter when disabled (it does when explicitly enabled);
* ``classify._classify_song_missing`` / ``_classify_song`` never run the CTP
  patch-level head pass and never write the flat ``"ctp"``-pathway cache when
  disabled;
* ``classify._process_song_head_missing`` writes no ``binned_ctp_heads`` cache
  rows when disabled.

Empty CTP tables/caches are the EXPECTED CORRECT state (the phase-level zero-row
gate accepts empty CTP tables as correct, not corruption) — so these assertions
check that the disabled path produces exactly zero CTP rows rather than raising.
"""

from __future__ import annotations

import numpy as np

import scripts.embedding_research.common.segment as _segment_mod
from scripts.embedding_research import classify as classify_mod
from scripts.embedding_research import run as run_mod

# ---------------------------------------------------------------------------
# run._segment_phase — CTP segmentation is phase-gated
# ---------------------------------------------------------------------------


def _segment_cfg(**overrides) -> dict:
    cfg = {
        "flat_strategies": ["medoid"],
        "song_ids": {"s1"},
        "force": False,
        "backbones": ["effnet"],
        "cache": None,
        "heads": None,
        "device": "cpu",
    }
    cfg.update(overrides)
    return cfg


def _segment_call_recorder(monkeypatch, runs) -> None:
    def _spy(con, segment_fn, *args, **kwargs):  # noqa: ARG001
        runs.append(segment_fn)

    monkeypatch.setattr(_segment_mod, "segment", _spy)


def _noop_batches(*_args, **_kwargs) -> None:
    return None


def _fake_ctp_infra(_backbone, *, heads=None, device="cpu"):  # noqa: ARG001
    """Return a non-empty fake CTP head-session map + no-op batch runner."""
    return ({"mood": object()}, _noop_batches)


def test_segment_phase_disabled_does_no_ctp_segmentation(monkeypatch) -> None:
    """A disabled default runs global_pool + PTC segmentation but NO CTP pass."""
    calls: list = []
    _segment_call_recorder(monkeypatch, calls)
    built: list = []

    def _record(_backbone, *, heads=None, device="cpu"):
        built.append(True)
        return _fake_ctp_infra(_backbone, heads=heads, device=device)

    monkeypatch.setattr(run_mod, "_build_ctp_segment_infra", _record)
    monkeypatch.setattr(run_mod, "_ctp_enabled", lambda: False)

    run_mod._segment_phase(con=None, cfg=_segment_cfg())

    # Only the two primary passes (global_pool + PTC) run; no CTP segmenter.
    assert len(calls) == 2
    assert not built, "CTP segment infra must not be built when archival_ctp is disabled"


def test_segment_phase_enabled_runs_ctp_segmentation(monkeypatch) -> None:
    """Explicit opt-in re-enables the CTP segment pass."""
    calls: list = []
    _segment_call_recorder(monkeypatch, calls)
    monkeypatch.setattr(run_mod, "_build_ctp_segment_infra", _fake_ctp_infra)
    monkeypatch.setattr(run_mod, "_ctp_enabled", lambda: True)

    run_mod._segment_phase(con=None, cfg=_segment_cfg())

    # global_pool + PTC + CTP = three segment passes.
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# classify.py — CTP head inference + cache writes are phase-gated
# ---------------------------------------------------------------------------


def _fake_song(tmp_path, monkeypatch):
    """Return (path, save_calls, run_batches_calls)."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sidecar = tmp_path / "sidecar.npy"
    np.save(sidecar, np.ones((2, 3), dtype=np.float32))
    monkeypatch.setattr(classify_mod, "song_id", lambda _p: "s1")
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)

    save_calls: list = []
    batch_calls: list = []
    monkeypatch.setattr(classify_mod._flat_heads_cache, "save", lambda *a: save_calls.append(a))
    monkeypatch.setattr(
        classify_mod,
        "_run_head_session",
        lambda _session, vec: np.asarray(
            [0.1, 0.9] if vec.ndim == 1 else np.ones((len(vec), 2)) * 0.5, dtype=np.float32
        ),
    )

    def _run_batches(*_a, **_k):
        batch_calls.append(True)
        return np.ones((2, 3), dtype=np.float32)

    return song_path, save_calls, batch_calls, _run_batches


def test_classify_song_missing_disabled_skips_ctp_inference_and_write(monkeypatch, tmp_path) -> None:
    """Disabled: no patch-level head inference and no flat ``"ctp"``-pathway cache row."""
    song_path, save_calls, batch_calls, run_batches = _fake_song(tmp_path, monkeypatch)
    monkeypatch.setattr(classify_mod, "_ctp_enabled", lambda: False)

    worked = classify_mod._classify_song_missing(
        path=song_path,
        backbone_name="effnet",
        head_name="mood",
        head_session=object(),
        run_in_batches_fn=run_batches,
        batch_size=8,
        pooled_map={"mean": np.ones((1, 3), dtype=np.float32)},
        missing_strats=frozenset({"mean"}),
    )

    assert worked is True
    assert not batch_calls, "disabled default must not run the CTP patch-level head pass"
    # Exactly one PTC-pathway write, never a CTP-pathway write.
    assert len(save_calls) == 1
    pathway = save_calls[0][3]
    assert pathway == "ptc"


def test_classify_song_missing_enabled_writes_ctp_pathway(monkeypatch, tmp_path) -> None:
    """Explicit opt-in runs the patch pass and writes the flat ``"ctp"`` pathway."""
    song_path, save_calls, batch_calls, run_batches = _fake_song(tmp_path, monkeypatch)
    monkeypatch.setattr(classify_mod, "_ctp_enabled", lambda: True)

    worked = classify_mod._classify_song_missing(
        path=song_path,
        backbone_name="effnet",
        head_name="mood",
        head_session=object(),
        run_in_batches_fn=run_batches,
        batch_size=8,
        pooled_map={"mean": np.ones((1, 3), dtype=np.float32)},
        missing_strats=frozenset({"mean"}),
    )

    assert worked is True
    assert batch_calls, "enabled CTP must run the patch-level head pass"
    pathways = {call[3] for call in save_calls}
    assert pathways == {"ptc", "ctp"}


def test_classify_binned_ctp_heads_gated_when_disabled(monkeypatch) -> None:
    """Disabled: _process_song_head_missing writes no binned_ctp_heads cache rows."""
    save_calls: list = []
    monkeypatch.setattr(classify_mod._binned_ctp_heads_cache, "save", lambda *a: save_calls.append(a))
    monkeypatch.setattr(classify_mod, "_ctp_enabled", lambda: False)

    def _run_batches(*_a, **_k):  # should never be reached when disabled
        raise AssertionError("CTP head inference must not run when archival_ctp is disabled")

    saved = classify_mod._process_song_head_missing(
        sid="s1",
        backbone="effnet",
        head_name="mood",
        head_session=object(),
        run_in_batches_fn=_run_batches,
        batch_size=8,
        patches=np.ones((3, 3), dtype=np.float32),
        missing_thresholds=frozenset({0.5}),
    )

    assert saved == 0
    assert not save_calls, "disabled default must write zero binned_ctp_heads cache rows"


def test_empty_ctp_tables_are_expected_correct_state() -> None:
    """The default-config gate yields zero CTP rows — an accepted correct state.

    Ground: DD line 233 — 'the phase-level zero-row gate explicitly accepts empty
    CTP tables as correct, not corruption.'  A disabled default run produces no
    CTP analyze rows; asserting this == 0 (not raising) is the expected outcome.
    """
    from scripts.embedding_research.helpers import toml as toml_mod

    cfg = toml_mod.load_research_config()
    assert cfg["archival_ctp"]["enabled"] is False
    # The phase-level gate reads the same flag everywhere it matters.
    assert run_mod._ctp_enabled() is False
    assert classify_mod._ctp_enabled() is False
