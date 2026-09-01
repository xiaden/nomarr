from __future__ import annotations

import pytest

from scripts.embedding_research.helpers import toml as research_toml
from scripts.embedding_research.pooling import load_flat_strategy_names


@pytest.fixture(autouse=True)
def clear_load_research_config_bytes_cache() -> None:
    research_toml.load_research_config_bytes.cache_clear()
    yield
    research_toml.load_research_config_bytes.cache_clear()


def test_load_research_config_bytes_returns_empty_bytes_when_file_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "missing_research_config.toml"

    monkeypatch.setattr(research_toml, "_CONFIG_PATH", missing_path)

    result = research_toml.load_research_config_bytes()

    assert result == b""


def test_load_research_config_bytes_returns_file_bytes_when_file_exists(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "research_config.toml"
    expected = b"[research]\nlimit = 42\n"
    config_path.write_bytes(expected)

    monkeypatch.setattr(research_toml, "_CONFIG_PATH", config_path)

    result = research_toml.load_research_config_bytes()

    assert result == expected


# ---------------------------------------------------------------------------
# load_flat_strategy_names (Part A live flat-strategy configuration)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_config_cache() -> None:
    research_toml.load_research_config.cache_clear()
    yield
    research_toml.load_research_config.cache_clear()


def test_shipped_config_narrows_primary_flat_strategies_to_medoid() -> None:
    """The shipped research config sets the primary flat baseline to medoid only.

    The follow-on primary experiment narrows the default to
    ``flat_strategies=["medoid"]``; the all-strategies unconfigured fallback is a
    legacy archival behaviour and is never the shipped default.
    """
    cfg = research_toml.load_research_config()
    assert load_flat_strategy_names(cfg) == ["medoid"]


def test_load_flat_strategy_names_returns_explicit_list() -> None:
    """An explicit list is returned in configuration order."""
    cfg = {"pooling": {"flat_strategies": ["mean", "max_norm", "medoid"]}}
    assert load_flat_strategy_names(cfg) == ["mean", "max_norm", "medoid"]


def test_load_flat_strategy_names_requires_medoid_for_benchmark_baseline() -> None:
    """A configured baseline without medoid is rejected."""
    cfg = {"pooling": {"flat_strategies": ["mean", "median"]}}
    with pytest.raises(ValueError, match="medoid"):
        load_flat_strategy_names(cfg)


def test_load_flat_strategy_names_rejects_unknown_strategy() -> None:
    """Unknown strategy names raise a clear ValueError."""
    cfg = {"pooling": {"flat_strategies": ["mean", "medoid", "bogus"]}}
    with pytest.raises(ValueError, match="bogus"):
        load_flat_strategy_names(cfg)


def test_load_flat_strategy_names_rejects_empty_list() -> None:
    """An explicitly empty flat_strategies list is rejected."""
    cfg = {"pooling": {"flat_strategies": []}}
    with pytest.raises(ValueError, match="empty"):
        load_flat_strategy_names(cfg)


def test_load_flat_strategy_names_preserves_order_and_dedupes() -> None:
    """Duplicates are removed while preserving first-occurrence order."""
    cfg = {"pooling": {"flat_strategies": ["medoid", "mean", "medoid"]}}
    assert load_flat_strategy_names(cfg) == ["medoid", "mean"]


def test_load_flat_strategy_names_is_backbone_independent_default() -> None:
    """The same explicit list is applied per-backbone; each identity stays scoped."""
    cfg = {"pooling": {"flat_strategies": ["mean", "medoid"]}}
    names = load_flat_strategy_names(cfg)
    effnet = [f"global_pool:effnet:{name}" for name in names]
    musicnn = [f"global_pool:musicnn:{name}" for name in names]
    assert effnet != musicnn
    assert set(effnet).isdisjoint(set(musicnn))
    assert "global_pool:effnet:medoid" in effnet
    assert "global_pool:musicnn:medoid" in musicnn


# ---------------------------------------------------------------------------
# QA R2: configuration enforces the Part B weighted reductions
# ---------------------------------------------------------------------------


def test_pooling_primary_score_variant_and_labeled_hypotheses() -> None:
    """The primary score surface is ``max_per_candidate_segment`` only.

    The three Part B weighted reductions live under a labelled
    ``[pooling.hypotheses]`` block as comparison hypotheses, not the primary
    formula declaration, and are evaluated only when explicitly added to
    ``pooling.score_variants``.
    """
    cfg = research_toml.load_research_config()
    assert cfg["pooling"]["score_variants"] == ["max_per_candidate_segment"]
    assert cfg["pooling"]["hypotheses"]["weighted_reductions"] == [
        "target_weighted",
        "bidirectional_weighted",
        "normalized_mean_pair_weighted",
    ]


def test_optimization_strategy_agg_method_is_target_weighted() -> None:
    """[optimization.strategy] agg_method is the valid weighted default."""
    cfg = research_toml.load_research_config()
    # [optimization.strategy] is a sub-table of [optimization] in the TOML.
    assert cfg["optimization"]["strategy"]["agg_method"] == "target_weighted"
