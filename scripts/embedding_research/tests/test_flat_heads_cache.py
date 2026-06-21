"""Tests for scripts.embedding_research.cache.flat_heads filesystem cache.

These tests exercise the canonical read/write contract so that bugs like
"classify writes only to the filesystem cache but analyze reads from the DB"
are caught immediately.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.cache import flat_heads

# ── helpers ───────────────────────────────────────────────────────────────────


def _save(tmp_cache, backbone, head, strategy, pathway, sid, score):
    """Save a two-element activation where act[-1] is the given score."""
    act = np.array([1.0 - score, score], dtype=np.float32)
    flat_heads.save(backbone, head, strategy, pathway, sid, act)
    return act


# ── 1. save / load roundtrip ──────────────────────────────────────────────────


def test_save_load_roundtrip(tmp_flat_head_cache):
    act = np.array([0.3, 0.7], dtype=np.float32)
    flat_heads.save("effnet", "mood_happy", "mean", "ptc", "s001", act)

    result = flat_heads.load("effnet", "mood_happy", "mean", "ptc", "s001")

    assert result is not None
    assert result.size == 2
    assert float(result[-1]) == pytest.approx(0.7, abs=1e-6)


def test_load_missing_returns_none(tmp_flat_head_cache):
    result = flat_heads.load("effnet", "mood_happy", "mean", "ptc", "nosong")
    assert result is None


def test_load_preserves_shape(tmp_flat_head_cache):
    act = np.array([0.1, 0.2, 0.3, 0.8], dtype=np.float32)
    flat_heads.save("effnet", "multi_label", "mean", "ptc", "s002", act)

    result = flat_heads.load("effnet", "multi_label", "mean", "ptc", "s002")

    assert result is not None
    assert result.shape == (4,)
    assert float(result[-1]) == pytest.approx(0.8, abs=1e-6)


# ── 2. load_bulk ──────────────────────────────────────────────────────────────


def test_load_bulk_returns_only_present(tmp_flat_head_cache):
    _save(tmp_flat_head_cache, "effnet", "mood", "mean", "ptc", "s001", 0.9)
    _save(tmp_flat_head_cache, "effnet", "mood", "mean", "ptc", "s002", 0.4)

    result = flat_heads.load_bulk("effnet", "mood", "mean", "ptc", ["s001", "s002", "s003"])

    assert set(result) == {"s001", "s002"}
    assert float(result["s001"][-1]) == pytest.approx(0.9, abs=1e-6)
    assert float(result["s002"][-1]) == pytest.approx(0.4, abs=1e-6)
    assert "s003" not in result


def test_load_bulk_empty_when_no_files(tmp_flat_head_cache):
    result = flat_heads.load_bulk("effnet", "mood", "mean", "ptc", ["s001", "s002"])
    assert result == {}


def test_load_bulk_act_last_element_is_score(tmp_flat_head_cache):
    """Regression: act[-1] must equal the saved score — the bug this pipeline had."""
    for i, sid in enumerate(["a1", "a2", "a3"]):
        _save(tmp_flat_head_cache, "effnet", "genre", "mean", "ptc", sid, i * 0.3)

    result = flat_heads.load_bulk("effnet", "genre", "mean", "ptc", ["a1", "a2", "a3"])

    assert float(result["a1"][-1]) == pytest.approx(0.0, abs=1e-6)
    assert float(result["a2"][-1]) == pytest.approx(0.3, abs=1e-6)
    assert float(result["a3"][-1]) == pytest.approx(0.6, abs=1e-6)


# ── 3. is_done ────────────────────────────────────────────────────────────────


def test_is_done_false_when_only_ptc_present(tmp_flat_head_cache):
    flat_heads.save("effnet", "mood", "mean", "ptc", "s1", np.array([0.2, 0.8]))
    assert flat_heads.is_done("effnet", "mood", "mean", "s1") is False


def test_is_done_false_when_only_ctp_present(tmp_flat_head_cache):
    flat_heads.save("effnet", "mood", "mean", "ctp", "s1", np.array([0.2, 0.8]))
    assert flat_heads.is_done("effnet", "mood", "mean", "s1") is False


def test_is_done_true_when_both_present(tmp_flat_head_cache):
    flat_heads.save("effnet", "mood", "mean", "ptc", "s1", np.array([0.2, 0.8]))
    flat_heads.save("effnet", "mood", "mean", "ctp", "s1", np.array([0.2, 0.8]))
    assert flat_heads.is_done("effnet", "mood", "mean", "s1") is True


# ── 4. missing_for_head ───────────────────────────────────────────────────────


def test_missing_for_head_identifies_partial_songs(tmp_flat_head_cache):
    """Songs with only one pathway file should be reported as missing."""
    # s1: fully done (both pathways)
    flat_heads.save("effnet", "mood", "mean", "ptc", "s1", np.array([0.1, 0.9]))
    flat_heads.save("effnet", "mood", "mean", "ctp", "s1", np.array([0.1, 0.9]))
    # s2: ptc only
    flat_heads.save("effnet", "mood", "mean", "ptc", "s2", np.array([0.4, 0.6]))
    # s3: absent entirely

    missing = flat_heads.missing_for_head(["s1", "s2", "s3"], "effnet", "mood", "mean")

    assert "s1" not in missing
    assert "s2" in missing
    assert "s3" in missing


def test_missing_for_head_empty_when_all_done(tmp_flat_head_cache):
    for sid in ["s1", "s2"]:
        flat_heads.save("effnet", "mood", "mean", "ptc", sid, np.array([0.3, 0.7]))
        flat_heads.save("effnet", "mood", "mean", "ctp", sid, np.array([0.3, 0.7]))

    missing = flat_heads.missing_for_head(["s1", "s2"], "effnet", "mood", "mean")

    assert missing == []


# ── 5. strategy / pathway independence ───────────────────────────────────────


def test_different_strategies_stored_independently(tmp_flat_head_cache):
    flat_heads.save("effnet", "mood", "mean", "ptc", "s1", np.array([0.1, 0.9]))
    flat_heads.save("effnet", "mood", "max", "ptc", "s1", np.array([0.4, 0.6]))

    mean_result = flat_heads.load("effnet", "mood", "mean", "ptc", "s1")
    max_result = flat_heads.load("effnet", "mood", "max", "ptc", "s1")

    assert mean_result is not None and float(mean_result[-1]) == pytest.approx(0.9, abs=1e-6)
    assert max_result is not None and float(max_result[-1]) == pytest.approx(0.6, abs=1e-6)
