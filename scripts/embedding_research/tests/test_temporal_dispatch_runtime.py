"""Temporal dispatch runtime — selected bin_mode drives the real segmentation metric.

Plan C P1-S1 spec-first golden tests for the corrective-pass temporal dispatch fix.

The retained catalog modes are advertised as ``temporal_global`` (direct unit-vector L2)
and ``temporal_perdim`` (per-dimension Chebyshev).  Before this pass the *advertised*
metric could diverge from the *implemented* one: the compact producer
(``catalog._build_and_persist_song``) called ``run_spherical_segmentation`` without a
``bin_mode`` and the runner hardcoded a direct-L2 boundary, so a ``temporal_perdim``
config was segmented as if it were L2.  This file proves the fix end-to-end:

* the run.py config generator selects exactly the two retained modes;
* building through the ACTUAL catalog producer dispatches the selected mode's real
  boundary metric (a fixture whose L2 and Chebyshev boundaries DIFFER produces different
  segmentations per mode — a runner that ignored ``bin_mode`` / hardcoded L2 would fail);
* the exact-threshold strictness contract holds for both modes at the builder path;
* the config layer fails closed on the retired ``"direct"`` vocabulary and unknown modes;
* no advertised mode is implemented by a mismatched distance function.

The differing-boundary fixture is two unit 2-D patches ``a=(1, 0)`` and ``b=(0.6, 0.8)``:
``dist_global = ||b - a||_2 = sqrt(0.8) ~ 0.8944`` while ``dist_perdim = max|b - a| = 0.8``.
At threshold ``0.85`` the L2 mode splits (0.8944 > 0.85) and the Chebyshev mode does not
(0.8 <= 0.85) — a genuinely different segmentation, impossible for a runner that always
uses L2.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.binning import DIST_FNS
from scripts.embedding_research.helpers.segmentation import run_spherical_segmentation

# Threshold strictly between Chebyshev (0.8) and L2 (sqrt(0.8) ~ 0.8944) of the fixture.
_DIFF_THRESHOLD = 0.85
# Chebyshev boundary of the integer-exact orthogonal fixture (strict ">" = not a split).
_CHEB_EXACT = 1.0


def _diff_stream() -> np.ndarray:
    """Two unit 2-D patches whose L2 and Chebyshev inter-patch distances differ."""
    return np.asarray([[1.0, 0.0], [0.6, 0.8]], dtype=np.float32)


def _ortho_stream() -> np.ndarray:
    """Unit 2-D patches whose Chebyshev distance is integer-exact (1.0)."""
    return np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)


def _seg_counts(con) -> dict[str, int]:
    """Map ``bin_mode`` -> persisted ``seg_meta`` row count in a compact snapshot."""
    rows = con.execute(
        "SELECT c.bin_mode, COUNT(m.config_id) "
        "FROM seg_meta m JOIN seg_config c ON m.config_id = c.config_id "
        "GROUP BY c.bin_mode ORDER BY c.bin_mode"
    ).fetchall()
    return dict(rows)


# --------------------------------------------------------------------------- #
# run.py config generator: selects exactly the retained temporal modes           #
# --------------------------------------------------------------------------- #


def test_run_config_generator_selects_only_the_two_retained_modes():
    """``run._catalog_seg_configs`` advertises exactly the DIST_FNS temporal modes."""
    from scripts.embedding_research import run

    cfg = {
        "backbones": ["effnet"],
        "catalog_bin_modes": ["temporal_global", "temporal_perdim"],
        "catalog_thresholds": [_DIFF_THRESHOLD],
    }
    configs = run._catalog_seg_configs(cfg)
    assert {c.bin_mode for c in configs} == {"temporal_global", "temporal_perdim"}
    # The generator's accepted modes are exactly the runner's advertised modes.
    assert {c.bin_mode for c in configs} == set(DIST_FNS)


# --------------------------------------------------------------------------- #
# Golden: selected mode dispatches the REAL boundary metric through the builder   #
# --------------------------------------------------------------------------- #


def test_selected_mode_dispatches_real_boundary_metric_through_catalog_builder(con, tmp_path, compact_catalog_factory):
    """Both retained modes build the same stream into DIFFERENT segmentations.

    ``temporal_global`` (L2, 0.8944 > 0.85) hard-splits into two structural segments;
    ``temporal_perdim`` (Chebyshev, 0.8 <= 0.85) keeps one.  A runner that hardcoded L2
    or ignored ``bin_mode`` would report two segments for BOTH modes — breaking the
    ``temporal_perdim -> 1`` assertion below.  Configs flow through the exact
    ``run._catalog_seg_configs`` -> :class:`SegConfigInput` -> producer path.
    """
    from scripts.embedding_research import run

    cfg = {
        "backbones": ["effnet"],
        "catalog_bin_modes": ["temporal_global", "temporal_perdim"],
        "catalog_thresholds": [_DIFF_THRESHOLD],
    }
    configs = run._catalog_seg_configs(cfg)
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _diff_stream()},
        configs=configs,
        song_ids=["s1"],
        run_id="dispatch-run",
    )
    counts = _seg_counts(harness.con)
    assert counts == {"temporal_global": 2, "temporal_perdim": 1}


def test_catalog_dispatch_is_strictly_greater_than_threshold_for_perdim(con, tmp_path, compact_catalog_factory):
    """Exact-threshold strictness holds for Chebyshev at the builder path.

    Threshold set exactly to the Chebyshev boundary (0.8) must NOT be a split for
    ``temporal_perdim`` (strict ``>``), so the two patches land in a single segment.
    A ``>=`` boundary would hard-split and yield two ``seg_meta`` rows.
    """
    from scripts.embedding_research import run

    cfg = {
        "backbones": ["effnet"],
        "catalog_bin_modes": ["temporal_perdim"],
        "catalog_thresholds": [_CHEB_EXACT],
    }
    configs = run._catalog_seg_configs(cfg)
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _ortho_stream()},
        configs=configs,
        song_ids=["s1"],
        run_id="strict-run",
    )
    assert _seg_counts(harness.con) == {"temporal_perdim": 1}


# --------------------------------------------------------------------------- #
# Config layer fails closed on the retired / unknown bin modes                    #
# --------------------------------------------------------------------------- #


def test_catalog_config_layer_refuses_retired_and_unknown_bin_modes(con, tmp_path, compact_catalog_factory):
    """The obsolete ``"direct"`` vocabulary and unknown modes are refused (fail closed)."""
    from scripts.embedding_research import catalog

    for bad_mode in ("direct", "temporal_quantile", "bogus"):
        config = {
            "backbone": "effnet",
            "bin_mode": bad_mode,
            "threshold_configured": _DIFF_THRESHOLD,
            "threshold_effective": _DIFF_THRESHOLD,
        }
        with pytest.raises(catalog.CatalogValidationError, match="bin_mode"):
            compact_catalog_factory(
                con,
                tmp_path,
                streams={("s1", "effnet"): _diff_stream()},
                configs=[config],
                song_ids=["s1"],
                run_id=f"refuse-{bad_mode}",
            )


def test_segmentation_helper_refuses_unknown_bin_mode():
    """The runner itself fails closed: unknown / retired modes raise ``ValueError``."""
    for bad_mode in ("direct", "temporal_quantile", "bogus"):
        with pytest.raises(ValueError, match="bin_mode"):
            run_spherical_segmentation(_diff_stream(), _DIFF_THRESHOLD, bin_mode=bad_mode)
    with pytest.raises(ValueError, match="temporal_global"):
        run_spherical_segmentation(_diff_stream(), _DIFF_THRESHOLD, bin_mode="direct")


# --------------------------------------------------------------------------- #
# No advertised mode is backed by a mismatched distance implementation            #
# --------------------------------------------------------------------------- #


def test_no_advertised_mode_has_mismatched_implementation():
    """Advertised modes map to distinct metrics that genuinely differ on the fixture."""
    # Exactly the two retained temporal modes are advertised (no 'direct'/ghost modes).
    assert set(DIST_FNS) == {"temporal_global", "temporal_perdim"}
    # The two mode implementations are genuinely distinct functions.
    assert DIST_FNS["temporal_global"] is not DIST_FNS["temporal_perdim"]
    # Each advertised mode's real boundary behavior is reproduced end-to-end: L2 splits
    # the fixture at 0.85, Chebyshev does not.
    stream = _diff_stream()
    global_segs = run_spherical_segmentation(stream, _DIFF_THRESHOLD, bin_mode="temporal_global")
    perdim_segs = run_spherical_segmentation(stream, _DIFF_THRESHOLD, bin_mode="temporal_perdim")
    assert len(global_segs) == 2
    assert [(s.start_idx, s.end_idx) for s in global_segs] == [(0, 1), (1, 2)]
    assert len(perdim_segs) == 1
    assert (perdim_segs[0].start_idx, perdim_segs[0].end_idx) == (0, 2)
