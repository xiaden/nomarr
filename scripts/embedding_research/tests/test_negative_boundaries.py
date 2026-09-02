"""Spec-first negative-boundary tests (Plan A, Phase 3 — P3-S2).

Each test encodes a DD requirement and FAILS LOUDLY if the requirement is later
violated. They are *negative* tests: they assert that the obsolete semantics
(implicit calibration multiplier, unlabelled aggregate/medoid, path-derived
identity, numeric DuckDB 2.x assumption, default CTP path) are REJECTED or
absent, never silently accepted.

DD grounding (``DD-frozen-observation-stream-segmentation-catalog.md``):
1. Implicit calibration multiplier  -> R2 (resolve configured-vs-effective;
   ``direct_l2`` default ``effective==configured``; legacy ``std_scaled`` only
   explicit with a recorded basis, never recomputed implicitly).
2. Unlabelled aggregate/medoid      -> R7/R13 (+ P1-S3 validator): medoids are
   observed source-patch indices; the synthetic coordinate-wise ``median`` and
   unknown/unlabelled names are rejected; a generic aggregate never enters as an
   unlabelled strategy.
3. Path-derived identity           -> R3 ("no path-derived IDs downstream")/R9:
   canonical identity/hash functions are pure content functions with no path
   parameter; identical semantic content -> identical hash regardless of any
   cache root / path context.
4. Numeric DuckDB 2.x assumption   -> DD dependency paragraph (post-L289):
   ``duckdb>=1.5,<2.0``; the LIBRARY version is gated while the STORAGE-format
   version is an opaque LABEL never numerically compared; 2.x = separately
   approved follow-up.
5. Default CTP path                -> R13 (CTP archival and truly disabled
   default) + DD CPU/inference-boundaries decision: ``[archival_ctp]
   enabled=false``; the default pipeline vocabulary excludes CTP; any CTP
   invocation requires an explicit archival opt-in.
"""

from __future__ import annotations

import inspect
import pathlib

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db import _schema as db_schema
from scripts.embedding_research.helpers import toml as toml_mod
from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    STD_SCALED,
    canonical_config_hash,
    canonical_config_inputs,
    resolve_threshold,
)
from scripts.embedding_research.strategy_binned._constants import (
    validate_optimizer_representation,
    validate_score_variant,
)
from scripts.embedding_research.strategy_ptc.segment_fn import STRATEGY_NAMES as PTC_STRATEGY_NAMES
from scripts.embedding_research.strategy_ptc.segment_fn import make_segment_fn

# ─────────────────────────────────────────────────────────────────────────────
# 1. No implicit calibration multiplier (R2)
# ─────────────────────────────────────────────────────────────────────────────


def test_direct_l2_default_effective_equals_configured_never_scaled() -> None:
    """Under the default ``direct_l2`` semantics the effective threshold == configured.

    Ground: R2. No multiplier and no ``0.1`` fallback: requesting PTC
    segmentation with no explicit basis must produce ``effective == configured``
    exactly, never ``configured x 0.1`` (the legacy silent default when no
    calibration row existed).
    """
    resolution = resolve_threshold(1.2)
    assert resolution.semantics == DIRECT_L2
    assert resolution.effective == 1.2
    assert resolution.configured == 1.2
    assert resolution.calibration_record is None  # no hidden p50 basis attached


def test_std_scaled_without_explicit_basis_raises_resolve_threshold() -> None:
    """``std_scaled`` with no calibration basis is rejected, never silently 0.1.

    Ground: R2. Legacy compatibility is explicit opt-in ONLY and requires a
    recorded basis; there is no implicit p50/0.1 fallback in the pure API.
    """
    with pytest.raises(ValueError, match="calibration"):
        resolve_threshold(1.2, semantics=STD_SCALED)
    with pytest.raises(ValueError, match="calibration"):
        resolve_threshold(1.2, semantics=STD_SCALED, calibration_record=None)
    # A non-finite/zero/negative basis is also rejected, not silently scaled.
    for bad_basis in ({"statistic": "p50", "value": 0.0}, {"statistic": "p50", "value": -1.0}):
        with pytest.raises(ValueError):
            resolve_threshold(1.2, semantics=STD_SCALED, calibration_record=bad_basis)


def test_ptc_std_scaled_without_basis_raises_end_to_end() -> None:
    """An end-to-end PTC ``std_scaled`` request with no explicit basis raises.

    Ground: R2. ``make_segment_fn(semantics=std_scaled, calibration_records={})``
    must raise on invocation rather than fall back to a silent ``0.1`` default.
    """
    fn = make_segment_fn(None, semantics=STD_SCALED, calibration_records={})
    patches = np.ones((4, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="explicit calibration basis"):
        fn(patches, "bb", PTC_STRATEGY_NAMES[0])


def test_ptc_default_direct_l2_hands_configured_threshold_to_segmenter(monkeypatch) -> None:
    """Spy/equivalence: the default PTC path never scales — effective == configured.

    Ground: R2. Under the default ``direct_l2`` adapter the threshold handed to
    ``temporal_segment`` equals the configured value decoded from the strategy
    name; there is no p50/0.1 multiplier anywhere on the default path.
    """
    captured: dict[str, object] = {}

    def _spy(*args, **_kwargs):
        captured["threshold"] = args[1]
        return []

    monkeypatch.setattr("scripts.embedding_research.strategy_ptc.segment_fn.temporal_segment", _spy)
    fn = make_segment_fn(None)  # default semantics=direct_l2
    name = PTC_STRATEGY_NAMES[0]
    _bin_mode, configured = _decode_ptc(name)
    fn(np.ones((4, 8), dtype=np.float32), "bb", name)
    assert captured["threshold"] == configured


def _decode_ptc(strategy_name: str) -> tuple[str, float]:
    """Decode a ``ptc_{bin_mode}_{std_thresh:.2f}`` name (kept local, no behavior change)."""
    # Mirrors strategy_ptc.segment_fn._decode_strategy_name for the spy assertions.
    body = strategy_name[len("ptc_") :]
    bin_mode, thresh = body.rsplit("_", 1)
    return bin_mode, float(thresh)


# ─────────────────────────────────────────────────────────────────────────────
# 2. No unlabelled aggregate / medoid strategy (R7/R13 + P1-S3 validator)
# ─────────────────────────────────────────────────────────────────────────────


def test_optimizer_rejects_synthetic_median_and_unknown_unlabelled_reps() -> None:
    """An aggregate/medoid rep without an explicit observed-source label is rejected.

    Ground: R7. The stale coordinate-wise synthetic ``median`` (a never-observed
    bin vector) and any unknown/unlabelled rep name are rejected loudly by
    ``validate_optimizer_representation``; the only medoid accepted is the
    observed-source ``"medoid"``.
    """
    with pytest.raises(ValueError, match="medoid"):
        validate_optimizer_representation("median")
    for unlabelled in ("bogus", "centroid", "mode", ""):
        with pytest.raises(ValueError):
            validate_optimizer_representation(unlabelled)
    # The observed-source medoid is the accepted labelled form.
    assert validate_optimizer_representation("medoid") == "medoid"


def test_no_unlabelled_generic_aggregate_as_a_scoring_strategy() -> None:
    """No generic aggregate may be selected as an unlabelled scoring strategy.

    Ground: R7/R13. mean/median/max/min/medoid are generic aggregate names and
    are rejected by ``validate_score_variant`` — the only accepted scoring
    strategies are the labelled primary ``max_per_candidate_segment`` and the
    three explicitly named weighted hypotheses.
    """
    for generic in ("mean", "median", "max", "min", "medoid"):
        with pytest.raises(ValueError):
            validate_score_variant(generic)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Identity is never path-derived (R3/R9)
# ─────────────────────────────────────────────────────────────────────────────


def test_canonical_config_identity_has_no_path_parameter() -> None:
    """The canonical config-identity/hash functions are pure content functions.

    Ground: R3/R9. ``canonical_config_inputs``/``canonical_config_hash`` take
    ONLY semantic content parameters (backbone/bin_mode/thresholds/semantics/
    calibration/outlier/version/alias) — no path, cache root, corpus root, cwd,
    or filesystem context. Identity is content-derived, never path-derived.
    """
    params = set(inspect.signature(canonical_config_inputs).parameters)
    forbidden_path_params = {"path", "cache_root", "root", "output_root", "cwd", "dir", "corpus"}
    assert forbidden_path_params.isdisjoint(params)


def test_canonical_module_source_never_keys_identity_off_a_path() -> None:
    """The canonical-identity module imports/uses no filesystem-path machinery.

    Ground: R3. The module defining canonical identity/encoding contains no
    pathlib/os-path/OUTPUT_ROOT/cwd usage, so identity cannot be derived from a
    filesystem path or cache-root context.
    """
    source = pathlib.Path(inspect.getsourcefile(canonical_config_hash)).read_text(encoding="utf-8")
    for forbidden in ("pathlib", "os.path", "OUTPUT_ROOT", "getcwd", "Path("):
        assert forbidden not in source, f"canonical-identity module must not use {forbidden!r}"


def test_canonical_config_hash_is_deterministic_across_path_contexts() -> None:
    """Identical semantic content -> identical hash regardless of path context.

    Ground: R9. The same content hash is produced on every call; because the
    function signature carries no path/root, the hash cannot change with any
    cache-root / filesystem context. (Plan B/C additionally enforce that
    ``seg_config`` application IDs and hashes never incorporate a path or
    per-corpus cache root.)
    """
    base = {
        "backbone": "effnet",
        "bin_mode": "temporal_global",
        "threshold_configured": 1.2,
        "threshold_effective": 1.2,
        "semantics": DIRECT_L2,
        "calibration_record": None,
        "outlier_window": 3,
        "strategy_version": 1,
        "alias_of_config_id": None,
    }
    first = canonical_config_hash(**base)
    second = canonical_config_hash(**base)
    assert first == second  # deterministic
    assert isinstance(first, str) and len(first) == 64  # sha256 hexdigest
    # Semantics is part of identity: same configured under std_scaled differs.
    scaled = dict(
        base, threshold_effective=1.2 * 0.8, semantics=STD_SCALED, calibration_record={"statistic": "p50", "value": 0.8}
    )
    assert canonical_config_hash(**scaled) != first


# ─────────────────────────────────────────────────────────────────────────────
# 4. DuckDB: storage-version is a LABEL, library-version is gated (DD §version)
# ─────────────────────────────────────────────────────────────────────────────


def test_storage_version_is_opaque_label_never_numeric_gate() -> None:
    """A hypothetical DuckDB 2.x STORAGE-format version passes through as a label.

    Ground: DD dependency paragraph. ``storage_version_label`` never parses or
    numerically compares the value — a future 2.x storage version is opaque
    provenance metadata, not a compatibility gate.
    """
    assert db_schema.storage_version_label("2.1.0") == "2.1.0"
    assert db_schema.storage_version_label("2.0.0") == "2.0.0"
    assert db_schema.storage_version_label(2) == "2"  # even a bare 2 is not gated


def test_library_2x_is_gated_while_2x_storage_label_is_not(monkeypatch) -> None:
    """Library-version gate and storage-version label are DISTINCT.

    Ground: DD dependency paragraph. A duckdb LIBRARY version outside 1.5<=v<2.0
    is rejected by ``require_supported_duckdb``, while a 2.x STORAGE-format label
    passes unchanged — proving the numeric compatibility gate applies to the
    library only, and storage-format metadata is never numerically compared.
    """
    # Installed library within range passes the gate.
    db_schema.require_supported_duckdb()
    # A hypothetical 2.x library is rejected.
    monkeypatch.setattr(duckdb, "__version__", "2.0.3")
    with pytest.raises(RuntimeError, match="duckdb"):
        db_schema.require_supported_duckdb()
    # But a 2.x storage-format label is still opaque (no numeric gate).
    assert db_schema.storage_version_label("2.0.3") == "2.0.3"


# ─────────────────────────────────────────────────────────────────────────────
# 5. CTP is never the default path (R13)
# ─────────────────────────────────────────────────────────────────────────────


def test_shipped_config_disables_ctp_by_default() -> None:
    """The shipped default config has ``[archival_ctp] enabled=false``.

    Ground: R13 (CTP archival and truly disabled default). A default run performs
    no CTP work/rows/winners. This is the config-level negative; runtime phase
    gating (Plan E) consumes the same flag.
    """
    from scripts.embedding_research import run as run_mod

    cfg = toml_mod.load_research_config()
    assert cfg["archival_ctp"]["enabled"] is False
    # The live phase-gate helper reads the same shipped flag -> default run: no CTP.
    assert run_mod._ctp_enabled() is False


def test_default_pipeline_vocabulary_excludes_ctp() -> None:
    """The default pipeline vocabulary excludes CTP segment functions/thresholds.

    Ground: R13. The default PTC ``STRATEGY_NAMES`` (and the cosine/medoid scoring
    vocabulary) contain no CTP entry, so CTP can never be selected as a default
    strategy. Enabling it requires the explicit archival opt-in flag
    (``[archival_ctp] enabled=true``), exercised only under an archival run.
    """
    assert PTC_STRATEGY_NAMES  # non-empty default vocabulary
    assert not any(name.startswith("ctp") for name in PTC_STRATEGY_NAMES)
    assert all(name.startswith("ptc_") for name in PTC_STRATEGY_NAMES)
    cfg = toml_mod.load_research_config()
    assert cfg["similarity"]["metrics"] == ["cosine"]  # CTP score-space is not primary
