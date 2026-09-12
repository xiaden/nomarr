"""Unit tests for canonical numeric/text identity and config hashing (Plan A P1-S2)."""

from __future__ import annotations

import pytest

from scripts.embedding_research.helpers.thresholds import (
    DIRECT_DISTANCE,
    ThresholdResolution,
    canonical_config_hash,
    canonical_config_inputs,
    canonical_float,
    canonical_int,
    canonical_outlier_window,
    canonical_strategy_version,
    canonical_text,
    config_encoder_version,
    resolve_threshold,
)


def test_canonical_float_is_deterministic() -> None:
    assert canonical_float(1.25) == canonical_float(1.25)


def test_canonical_float_equivalent_spellings_identical() -> None:
    assert canonical_float(0.1) == canonical_float(1e-1) == "0.1"


def test_canonical_float_has_no_exponent_ambiguity() -> None:
    assert canonical_float(1e-06) == "0.000001"
    assert "e" not in canonical_float(1e-06)
    assert canonical_float(1.5e-05) == "0.000015"


def test_canonical_float_round_trips_integers() -> None:
    assert canonical_float(3.0) == "3.0"
    assert canonical_float(1.0) == "1.0"


def test_canonical_float_negative_zero_normalised() -> None:
    assert canonical_float(-0.0) == canonical_float(0.0) == "0.0"


def test_canonical_float_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        canonical_float(float("nan"))
    with pytest.raises(ValueError):
        canonical_float(float("inf"))


def test_canonical_float_keeps_distinct_floats_distinct() -> None:
    assert canonical_float(0.949999) != canonical_float(0.95)


def test_canonical_int_rejects_bool_and_non_int() -> None:
    assert canonical_int(3) == "3"
    with pytest.raises(TypeError):
        canonical_int(True)
    with pytest.raises(TypeError):
        canonical_int(3.0)


def test_canonical_text_non_empty() -> None:
    assert canonical_text("effnet") == "effnet"
    assert canonical_text("direct_distance") == "direct_distance"
    with pytest.raises(ValueError):
        canonical_text("")
    with pytest.raises(ValueError):
        canonical_text("   ")


def test_canonical_scalar_text_helpers() -> None:
    assert canonical_text("temporal_global") == "temporal_global"
    assert canonical_outlier_window(3) == "3"
    assert canonical_strategy_version(1) == "1"


def test_no_scaled_or_calibration_surface() -> None:
    import scripts.embedding_research.helpers.thresholds as module

    for removed in (
        "canonical_semantics",
        "canonical_calibration_record",
        "canonical_threshold",
        "canonical_threshold_of",
        "STD_SCALED",
        "ThresholdSemantics",
        "validate_semantics",
    ):
        assert not hasattr(module, removed)


def test_encoder_version_is_64_hex() -> None:
    version = config_encoder_version()
    assert isinstance(version, str) and len(version) == 64
    int(version, 16)


def test_encoder_version_is_deterministic_across_calls() -> None:
    assert config_encoder_version() == config_encoder_version()


def test_module_sha256_two_source_strings_differ() -> None:
    from scripts.embedding_research.helpers.thresholds import _module_sha256

    assert _module_sha256(b"def a():\n    return 1\n") != _module_sha256(b"def a():\n    return 2\n")


def test_encoder_version_refreshes_on_metadata_change(monkeypatch) -> None:
    from scripts.embedding_research.helpers import thresholds as module

    stat = module._MODULE_PATH.stat()
    expected = module._module_sha256(module._MODULE_PATH.read_bytes())
    first = module.config_encoder_version()
    monkeypatch.setattr(module, "_encoder_version_cache", ("stale-key", 0, "stale"))
    assert module.config_encoder_version() == first == expected
    assert stat.st_size > 0


def _hash_kwargs(**overrides):
    values = {
        "backbone": "effnet",
        "experiment": "temporal_global",
        "threshold": 1.25,
        "outlier_window": 3,
        "strategy_version": 1,
        "encoder_version": config_encoder_version(),
    }
    values.update(overrides)
    return values


def test_config_hash_is_deterministic() -> None:
    assert canonical_config_hash(**_hash_kwargs()) == canonical_config_hash(**_hash_kwargs())


def test_config_hash_same_for_equivalent_numeric_spellings() -> None:
    assert canonical_config_hash(**_hash_kwargs(threshold=0.1)) == canonical_config_hash(**_hash_kwargs(threshold=1e-1))


def test_config_hash_sensitive_to_threshold() -> None:
    assert canonical_config_hash(**_hash_kwargs(threshold=1.25)) != canonical_config_hash(**_hash_kwargs(threshold=1.5))


def test_config_hash_sensitive_to_backbone_and_experiment() -> None:
    assert canonical_config_hash(**_hash_kwargs(backbone="effnet")) != canonical_config_hash(
        **_hash_kwargs(backbone="musicnn")
    )
    assert canonical_config_hash(**_hash_kwargs(experiment="temporal_global")) != canonical_config_hash(
        **_hash_kwargs(experiment="temporal_perdim_chebyshev_secondary")
    )


def test_config_hash_sensitive_to_encoder_version() -> None:
    assert canonical_config_hash(**_hash_kwargs(encoder_version="a" * 64)) != canonical_config_hash(
        **_hash_kwargs(encoder_version="b" * 64)
    )


def test_config_hash_rejects_non_finite_threshold() -> None:
    with pytest.raises(ValueError):
        canonical_config_hash(**_hash_kwargs(threshold=float("nan")))


def test_config_hash_requires_all_keyword_arguments() -> None:
    with pytest.raises(TypeError):
        canonical_config_hash(backbone="effnet", experiment="temporal_global")  # type: ignore[call-arg]


def test_config_inputs_fixed_field_order() -> None:
    encoder = config_encoder_version()
    inputs = canonical_config_inputs(
        backbone="effnet",
        experiment="temporal_global",
        threshold=1.25,
        outlier_window=3,
        strategy_version=1,
        encoder_version=encoder,
    )
    assert inputs == "|".join(
        [
            "backbone=effnet",
            "experiment=temporal_global",
            "threshold=1.25",
            "outlier_window=3",
            "strategy_version=1",
            f"encoder_version={encoder}",
        ]
    )


def test_config_hash_resolution_helper_shape() -> None:
    resolution = resolve_threshold(1.25)
    assert isinstance(resolution, ThresholdResolution)
    assert resolution.semantics == DIRECT_DISTANCE
    assert resolution.effective == resolution.configured == 1.25
    digest = canonical_config_hash(
        backbone="effnet",
        experiment="temporal_global",
        threshold=resolution.effective,
        outlier_window=3,
        strategy_version=1,
        encoder_version=resolution.encoder_version,
    )
    assert len(digest) == 64
    int(digest, 16)
