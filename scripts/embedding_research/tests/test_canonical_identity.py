"""Unit tests for canonical numeric/text identity and config hashing (Plan A P1-S2).

These pin the deterministic identity inputs later ``seg_config`` rows consume:
fixed canonical numeric formatting (same binary float -> same text; no exponent
ambiguity; non-finite rejected; ``-0.0`` normalized), canonical text identities
for bin mode / outlier window / strategy version / encoder version, and the
deterministic direct-L2 config hash over the fixed field ordering
``backbone | bin_mode | threshold | outlier_window | strategy_version |
encoder_version``.  There is no semantics/calibration/alias input and no
``std_scaled``/``canonical_semantics``/``canonical_calibration_record``/
``canonical_threshold`` surface.  The whole-module ``config_encoder_version()``
is content-addressed (SHA-256 of ``helpers/thresholds.py`` bytes).
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    ThresholdResolution,
    canonical_bin_mode,
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

# ── canonical numeric formatting ──────────────────────────────────────────────


def test_canonical_float_is_deterministic() -> None:
    """The same value encodes identically every time."""
    assert canonical_float(1.25) == canonical_float(1.25)


def test_canonical_float_equivalent_spellings_identical() -> None:
    """0.1 and 1e-1 are the same double and encode identically (no spelling drift)."""
    assert canonical_float(0.1) == canonical_float(1e-1)
    assert canonical_float(0.1) == "0.1"


def test_canonical_float_has_no_exponent_ambiguity() -> None:
    """Exponent forms are expanded to fixed-point; never scientific notation."""
    assert canonical_float(1e-06) == "0.000001"
    assert "e" not in canonical_float(1e-06)
    assert "e" not in canonical_float(1.5e-05)
    assert canonical_float(1.5e-05) == "0.000015"


def test_canonical_float_round_trips_integers() -> None:
    assert canonical_float(3.0) == "3.0"
    assert canonical_float(1.0) == "1.0"


def test_canonical_float_negative_zero_normalised() -> None:
    """-0.0 is normalised to 0.0 (mathematically equal, identical encoding)."""
    assert canonical_float(-0.0) == canonical_float(0.0) == "0.0"


def test_canonical_float_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        canonical_float(float("nan"))
    with pytest.raises(ValueError):
        canonical_float(float("inf"))


def test_canonical_float_keeps_distinct_floats_distinct() -> None:
    """Two genuinely different floats never collide (no fixed-precision rounding)."""
    assert canonical_float(0.949999) != canonical_float(0.95)


def test_canonical_int_rejects_bool_and_non_int() -> None:
    assert canonical_int(3) == "3"
    with pytest.raises(TypeError):
        canonical_int(True)
    with pytest.raises(TypeError):
        canonical_int(3.0)


# ── canonical text identities ─────────────────────────────────────────────────


def test_canonical_text_non_empty() -> None:
    assert canonical_text("effnet") == "effnet"
    assert canonical_text("direct_l2") == "direct_l2"
    with pytest.raises(ValueError):
        canonical_text("")
    with pytest.raises(ValueError):
        canonical_text("   ")


def test_canonical_scalar_text_helpers() -> None:
    assert canonical_bin_mode("temporal_global") == "temporal_global"
    assert canonical_outlier_window(3) == "3"
    assert canonical_strategy_version(1) == "1"


def test_no_scaled_or_calibration_surface() -> None:
    """The removed semantics/calibration/alias encoders no longer exist on thresholds."""
    import scripts.embedding_research.helpers.thresholds as _t

    for removed in (
        "canonical_semantics",
        "canonical_calibration_record",
        "canonical_threshold",
        "canonical_threshold_of",
        "canonical_alias",
        "STD_SCALED",
        "ThresholdSemantics",
        "validate_semantics",
    ):
        assert not hasattr(_t, removed), f"forbidden surface {removed} still present"


# ── encoder version (whole-module content hash) ───────────────────────────────


def test_encoder_version_is_64_hex() -> None:
    v = config_encoder_version()
    assert isinstance(v, str)
    assert len(v) == 64
    int(v, 16)  # must be hex


def test_module_sha256_two_source_strings_differ() -> None:
    """Two different source byte strings always hash differently (content-addressed)."""
    from scripts.embedding_research.helpers.thresholds import _module_sha256

    assert _module_sha256(b"def a():\n    return 1\n") != _module_sha256(b"def a():\n    return 2\n")


def test_encoder_version_refreshes_on_metadata_change(monkeypatch) -> None:
    """The cached version refreshes when the module file metadata (mtime/size) changes."""
    from scripts.embedding_research.helpers import thresholds as _t

    real_stat = _t._MODULE_PATH.stat()
    fresh = (_t._module_sha256(_t._MODULE_PATH.read_bytes()), real_stat.st_mtime_ns, real_stat.st_size)

    first = _t.config_encoder_version()
    # Force a cache key that differs from the real file metadata, proving the cache
    # is keyed on metadata (size, mtime_ns) — a change invalidates and re-hashes.
    monkeypatch.setattr(_t, "_encoder_version_cache", ("stale-key", 0, "stale"))
    second = _t.config_encoder_version()
    assert second == first  # re-derived from real module content, not the stale entry
    assert second == fresh[0]


# ── canonical config-hash (direct-L2 only) ────────────────────────────────────


def _hash_kwargs(**overrides):
    base = {
        "backbone": "effnet",
        "bin_mode": "temporal_global",
        "threshold": 1.25,
        "outlier_window": 3,
        "strategy_version": 1,
        "encoder_version": config_encoder_version(),
    }
    base.update(overrides)
    return base


def test_config_hash_is_deterministic() -> None:
    kwargs = _hash_kwargs()
    assert canonical_config_hash(**kwargs) == canonical_config_hash(**kwargs)


def test_config_hash_same_for_equivalent_numeric_spellings() -> None:
    """0.1 and 1e-1 are the same float, so a config using either hashes identically."""
    a = canonical_config_hash(**_hash_kwargs(threshold=0.1))
    b = canonical_config_hash(**_hash_kwargs(threshold=1e-1))
    assert a == b


def test_config_hash_sensitive_to_threshold() -> None:
    assert canonical_config_hash(**_hash_kwargs(threshold=1.25)) != canonical_config_hash(**_hash_kwargs(threshold=1.5))


def test_config_hash_sensitive_to_backbone_and_bin_mode() -> None:
    assert canonical_config_hash(**_hash_kwargs(backbone="effnet")) != canonical_config_hash(
        **_hash_kwargs(backbone="musicnn")
    )
    assert canonical_config_hash(**_hash_kwargs(bin_mode="temporal_global")) != canonical_config_hash(
        **_hash_kwargs(bin_mode="temporal_perdim")
    )


def test_config_hash_sensitive_to_encoder_version() -> None:
    assert canonical_config_hash(**_hash_kwargs(encoder_version="a" * 64)) != canonical_config_hash(
        **_hash_kwargs(encoder_version="b" * 64)
    )


def test_config_hash_rejects_non_finite_threshold() -> None:
    with pytest.raises(ValueError):
        canonical_config_hash(**_hash_kwargs(threshold=float("nan")))


def test_config_hash_requires_all_keyword_arguments() -> None:
    """Every config-hash input is a required keyword; omission raises TypeError."""
    with pytest.raises(TypeError):
        canonical_config_hash(backbone="effnet", bin_mode="temporal_global")  # type: ignore[call-arg]


def test_config_inputs_fixed_field_order() -> None:
    """The pre-hash inputs follow the documented direct-L2 seg_config field ordering."""
    encoder = config_encoder_version()
    inputs = canonical_config_inputs(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold=1.25,
        outlier_window=3,
        strategy_version=1,
        encoder_version=encoder,
    )
    ordered = [
        "backbone=effnet",
        "bin_mode=temporal_global",
        "threshold=1.25",
        "outlier_window=3",
        "strategy_version=1",
        f"encoder_version={encoder}",
    ]
    assert inputs == "|".join(ordered)


def test_config_hash_resolution_helper_shape() -> None:
    """A resolved direct-L2 ThresholdResolution carries the canonical finite fields."""
    res = resolve_threshold(1.25)
    assert isinstance(res, ThresholdResolution)
    assert res.semantics == DIRECT_L2
    assert res.effective == res.configured == 1.25
    assert res.encoder_version
    # The config hash is computed from the resolved threshold + whole-module version.
    h = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold=res.effective,
        outlier_window=3,
        strategy_version=1,
        encoder_version=res.encoder_version,
    )
    assert len(h) == 64
    int(h, 16)
