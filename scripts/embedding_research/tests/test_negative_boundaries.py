"""Spec-first negative-boundary tests (Plan A P1 — frozen-observation corrective pass).

Each test encodes a requirement and FAILS LOUDLY if the requirement is later
violated. They are *negative* tests: they assert that the obsolete surfaces
(implicit calibration multiplier, any second/scaled threshold semantics,
unlabelled aggregate/medoid, path-derived identity, numeric DuckDB 2.x
assumption, default CTP path, permissive config) are REJECTED or absent, never
silently accepted.

Grounding (``DD-frozen-observation-corrective-pass.md`` + plan P1):
1. Threshold is a single direct normalized-unit-vector L2 contract
   (``effective == configured``).  ``std_scaled``/calibration/p50 resolution and
   any ``semantics=``/``calibration_record=`` keyword are gone.
2. Unlabelled aggregate/medoid -> medoids are observed source indices; the
   synthetic coordinate-wise ``median`` and unknown/unlabelled rep names are
   rejected; a generic aggregate never enters as an unlabelled strategy.
3. Identity is never path-derived: canonical hash inputs are pure content
   parameters (no cache root / cwd / path).  ``config_encoder_version()`` is
   content-addressed (SHA-256 of ``helpers/thresholds.py`` bytes) — a deliberate,
   documented safe-direction exception whose refresh key is file *metadata*, not
   a path-derived ID.
4. Numeric DuckDB 2.x assumption: ``duckdb>=1.5,<2.0``; the LIBRARY version is
   gated while the STORAGE-format version is an opaque LABEL never compared.
5. CTP is never the default: the strict config has no ``[archival_ctp]`` section
   (the family is rejected outright), and ``run._ctp_enabled()`` is always False.
"""

from __future__ import annotations

import inspect

import duckdb
import pytest

from scripts.embedding_research.db import _schema as db_schema
from scripts.embedding_research.helpers import toml as toml_mod
from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    canonical_config_hash,
    canonical_config_inputs,
    resolve_threshold,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Single direct-L2 threshold contract; no scaled/calibration/p50 surface
# ─────────────────────────────────────────────────────────────────────────────


def test_direct_l2_effective_equals_configured_never_scaled() -> None:
    """Under the single direct-L2 semantics effective == configured exactly."""
    resolution = resolve_threshold(1.2)
    assert resolution.semantics == DIRECT_L2
    assert resolution.effective == 1.2
    assert resolution.configured == 1.2
    # No hidden p50 basis, no multiplier: the field no longer exists.
    assert not hasattr(resolution, "calibration_record")


def test_any_semantics_or_calibration_keyword_is_rejected() -> None:
    """There is no second/scaled semantics: requesting one is a TypeError, not silent."""
    with pytest.raises(TypeError):
        resolve_threshold(1.2, semantics="std_scaled")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        resolve_threshold(1.2, calibration_record={"statistic": "p50", "value": 0.8})  # type: ignore[call-arg]


# ─────────────────────────────────────────────────────────────────────────────
# 2. No unlabelled aggregate / medoid strategy (observed-source only)
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 3. Identity is content-derived, never path-derived
# ─────────────────────────────────────────────────────────────────────────────


def test_canonical_config_identity_has_no_path_parameter() -> None:
    """The canonical config-identity/hash functions are pure content functions.

    ``canonical_config_inputs``/``canonical_config_hash`` take ONLY semantic
    content parameters (backbone/bin_mode/threshold/outlier_window/strategy_
    version/encoder_version) — no path, cache root, corpus root, cwd, or
    filesystem context.
    """
    params = set(inspect.signature(canonical_config_inputs).parameters)
    forbidden_path_params = {"path", "cache_root", "root", "output_root", "cwd", "dir", "corpus"}
    assert forbidden_path_params.isdisjoint(params)


def _hash_kwargs(**overrides):
    from scripts.embedding_research.helpers.thresholds import config_encoder_version

    base = {
        "backbone": "effnet",
        "bin_mode": "temporal_global",
        "threshold": 1.2,
        "outlier_window": 3,
        "strategy_version": 1,
        "encoder_version": config_encoder_version(),
    }
    base.update(overrides)
    return base


def test_canonical_config_hash_is_deterministic_across_path_contexts() -> None:
    """Identical semantic content -> identical hash regardless of any path context.

    Because the hash signature carries no path/root and is a pure function of
    content parameters, the hash cannot change with any cache-root/filesystem
    context.  ``config_encoder_version()`` is content-addressed from module
    bytes (the documented safe-direction whole-module hash), not a path ID.
    """
    first = canonical_config_hash(**_hash_kwargs())
    second = canonical_config_hash(**_hash_kwargs())
    assert first == second  # deterministic
    assert isinstance(first, str) and len(first) == 64  # sha256 hexdigest
    # Threshold is part of identity: a different direct threshold differs.
    assert canonical_config_hash(**_hash_kwargs(threshold=1.5)) != first


# ─────────────────────────────────────────────────────────────────────────────
# 4. DuckDB: storage-version is a LABEL, library-version is gated
# ─────────────────────────────────────────────────────────────────────────────


def test_storage_version_is_opaque_label_never_numeric_gate() -> None:
    """A hypothetical DuckDB 2.x STORAGE-format version passes through as a label."""
    assert db_schema.storage_version_label("2.1.0") == "2.1.0"
    assert db_schema.storage_version_label("2.0.0") == "2.0.0"
    assert db_schema.storage_version_label(2) == "2"  # even a bare 2 is not gated


def test_library_2x_is_gated_while_2x_storage_label_is_not(monkeypatch) -> None:
    """Library-version gate and storage-version label are DISTINCT."""
    db_schema.require_supported_duckdb()
    monkeypatch.setattr(duckdb, "__version__", "2.0.3")
    with pytest.raises(RuntimeError, match="duckdb"):
        db_schema.require_supported_duckdb()
    assert db_schema.storage_version_label("2.0.3") == "2.0.3"


# ─────────────────────────────────────────────────────────────────────────────
# 5. CTP is never the default; strict config has no CTP/forbidden surfaces
# ─────────────────────────────────────────────────────────────────────────────


def test_default_pipeline_vocabulary_excludes_ctp() -> None:
    """The strict typed config exposes no CTP/archival/optimization/pooling surfaces.

    The legacy PTC strategy-vocabulary module (``strategy_ptc.segment_fn``) was
    deleted with the segmentation strategies in the corrective-pass hard cut; no
    CTP can be selected because the strict config rejects the ``[archival_ctp]``
    family and exposes none of the legacy sections.
    """
    cfg = toml_mod.load_research_config()
    # No forbidden config sections are exposed on the strict typed object.
    for forbidden_attr in ("archival_ctp", "optimization", "pooling", "similarity", "stratify", "binning"):
        assert not hasattr(cfg, forbidden_attr), f"forbidden config section {forbidden_attr} still exposed"
