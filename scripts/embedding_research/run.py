"""
CLI entrypoint for the embedding research pipeline.

Phase 4 explicit CLI.  The pipeline is decomposed into exactly eight phases:

  ingest  embed  infer-heads  catalog  catalog-report
  analyze  head-analysis  report

Only the first three phases (ingest, embed, infer-heads) may discover audio,
load ONNX models, create ML sessions, or run inference.  The five derived
phases (catalog, catalog-report, analyze, head-analysis, report) are CPU-only:
they consume only DuckDB catalog/registry rows, manifests, search views and
frozen stream + head artifacts and never touch audio/models/ONNX/CUDA.

Run one phase:

  python run.py <phase>

where <phase> is one of the eight above.  Stratification is catalog input
(config/corpus selection), NOT a separate phase.  Cleanup and reset are explicit
SEPARATE maintenance operations (not pipeline phases):

  python run.py cleanup --scope {staging|views|dead|archival|analysis-run}
                         [--run-id ID] [--confirm] [--dry-run]
  python run.py reset [--binned-cache]

First-time setup:

  python run.py --install

All configuration lives in research_config.toml next to this file.  Each phase
is individually idempotent against the frozen DB/streams, and every invocation
records an auditable run_provenance row (run_id is fresh per invocation).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import numpy as np
from alive_progress import config_handler as _ap_config

_ap_config.set_global(theme="musical")

# Ensure the workspace root is on sys.path so the package resolves correctly
# when run as `python run.py` inside the container.
_pkg_root = Path(__file__).resolve().parent.parent.parent  # /workspace
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research import common, db, pooling
from scripts.embedding_research.cache import binned_ctp, binned_ptc, flat_vecs
from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.common.analyze import validate_binned_weights
from scripts.embedding_research.config import BACKBONES, DB_PATH, HEAD_LABELS, HEADS, OUTPUT_ROOT, PATCHES_DIR
from scripts.embedding_research.corpus import MatchingCorpusManifest, build_matching_corpus
from scripts.embedding_research.helpers.binning import BIN_MODES, CTP_SCORE_THRESHOLDS
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.helpers.cache_utils import build_done_set as _build_done_set
from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config
from scripts.embedding_research.helpers.toml import load_research_config_bytes as _load_raw_cfg
from scripts.embedding_research.strategy_binned import _constants as _strategy_binned_constants
from scripts.embedding_research.strategy_ctp import segment_fn as _ctp_seg_fn
from scripts.embedding_research.strategy_global_pool import segment_fn as _gp_seg_fn
from scripts.embedding_research.strategy_ptc import segment_fn as _ptc_seg_fn
from scripts.embedding_research.vector_types import UnitTensor

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    from scripts.embedding_research.common.analyze import AnalyzeCfg

_REQ = Path(__file__).parent / "requirements.txt"
_log = logging.getLogger(__name__)


PTC_STRATEGY_NAMES = _ptc_seg_fn.STRATEGY_NAMES
# All possible CTP strategy names across every backbone — used by the analyze phase.
# The segment phase must NOT use this; it calls _ctp_seg_fn.make_strategy_names(head_sessions.keys()) instead.
_KNOWN_CTP_HEAD_NAMES: list[str] = sorted(
    {head for head_map in HEADS.values() for head in head_map} or HEAD_LABELS.keys()
)


@dataclass
class ModelCache:
    """Holds all pre-loaded ONNX sessions for the full pipeline run.

    backbone_sessions: backbone_name → session (needed by embed phase only).
    head_sessions: backbone_name → head_name → session (needed by segment + classify).
    run_in_batches_fn: shared batch runner for all head inference.
    """

    backbone_sessions: dict[str, Any] = field(default_factory=dict)
    head_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_in_batches_fn: Callable[..., Any] | None = None


def _build_model_cache(device: str) -> ModelCache:
    """Load all backbone and head ONNX sessions once at pipeline startup.

    Sessions are kept alive for the full pipeline duration (backbone sessions
    are explicitly cleared after the embed phase; head sessions after classify).
    """
    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session
    from scripts.embedding_research.config import HEAD_VRAM_BYTES

    cache = ModelCache()

    def _run_in_batches_fn(predict_fn: Callable[[Any], Any], inputs: Any) -> Any:
        return _run_in_batches(predict_fn, inputs, _BACKBONE_BATCH_SIZE)

    cache.run_in_batches_fn = _run_in_batches_fn

    from scripts.embedding_research.config import BACKBONES as _BB_CFG

    _bb_parts: list[str] = []
    for bb_name, bb_cfg in _BB_CFG.items():
        mb = round((bb_cfg.get("vram_limit_bytes") or 0) / 1_048_576)
        _bb_parts.append(f"{bb_name} ({mb}MB)" if mb else bb_name)
    _log.info("[cache] Loading backbones: %s", ", ".join(_bb_parts))
    for bb_name, bb_cfg in _BB_CFG.items():
        try:
            cache.backbone_sessions[bb_name] = create_session(
                bb_cfg["path"],
                device=device,
                vram_limit_bytes=bb_cfg.get("vram_limit_bytes"),
            )
        except Exception as exc:
            _log.error("[cache] Failed to load backbone %s: %s", bb_name, exc)
    _log.info("[cache] Backbones loaded.")

    _head_mb = round(HEAD_VRAM_BYTES / 1_048_576)
    _head_parts: list[str] = []
    for bb_name, head_map in HEADS.items():
        cache.head_sessions[bb_name] = {}
        _head_parts.extend(f"{bb_name}/{head_name} ({_head_mb}MB)" for head_name in head_map)
    _log.info("[cache] Loading classifiers: %s", ", ".join(_head_parts))
    for bb_name, head_map in HEADS.items():
        for head_name, head_model_path in head_map.items():
            try:
                cache.head_sessions[bb_name][head_name] = create_session(
                    head_model_path,
                    device=device,
                    vram_limit_bytes=HEAD_VRAM_BYTES,
                )
            except Exception as exc:
                _log.error("[cache] Failed to load head %s/%s: %s", bb_name, head_name, exc)
    _log.info("[cache] Classifiers loaded.")
    return cache


def _load_song_metadata(con: Any, sids: list[str]) -> tuple[list[str], list[str], list[str]]:
    if con is None or not sids:
        n = len(sids)
        return ["unknown"] * n, ["unknown"] * n, ["unknown"] * n

    rows = con.execute(
        "SELECT song_id, artist, album, genre FROM songs WHERE song_id = ANY(?)",
        [sids],
    ).fetchall()
    meta = {row[0]: (row[1] or "unknown", row[2] or "unknown", row[3] or "unknown") for row in rows}
    unknown = ("unknown", "unknown", "unknown")
    artists = [meta.get(sid, unknown)[0] for sid in sids]
    albums = [meta.get(sid, unknown)[1] for sid in sids]
    genres = [meta.get(sid, unknown)[2] for sid in sids]
    return artists, albums, genres


def _decode_ptc_strategy_name(strategy_name: str) -> tuple[str, float]:
    prefix = "ptc_"
    if not strategy_name.startswith(prefix):
        raise ValueError(f"Unsupported PTC strategy name: {strategy_name}")

    encoded = strategy_name[len(prefix) :]
    for bin_mode in sorted(BIN_MODES, key=len, reverse=True):
        marker = f"{bin_mode}_"
        if encoded.startswith(marker):
            return bin_mode, float(encoded[len(marker) :])

    raise ValueError(f"Unknown PTC bin mode in strategy name: {strategy_name}")


def _decode_ctp_strategy_name(strategy_name: str) -> tuple[str, float]:
    prefix = "ctp_"
    if not strategy_name.startswith(prefix):
        raise ValueError(f"Unsupported CTP strategy name: {strategy_name}")

    encoded = strategy_name[len(prefix) :]
    try:
        head_name, std_thresh_text = encoded.rsplit("_", 1)
    except ValueError as exc:
        raise ValueError(f"Malformed CTP strategy name: {strategy_name}") from exc

    return head_name, float(std_thresh_text)


def _global_pool_strategy_key(backbone: str, strategy_name: str, _extra: dict[str, Any]) -> str:
    return f"global_pool:{backbone}:{strategy_name}"


def _ptc_strategy_key(backbone: str, strategy_name: str, extra: dict[str, Any]) -> str:
    bin_mode = str(extra.get("bin_mode") or _decode_ptc_strategy_name(strategy_name)[0])
    std_thresh = float(extra.get("std_thresh", _decode_ptc_strategy_name(strategy_name)[1]))
    return f"ptc:{backbone}:{bin_mode}:{std_thresh:.2f}:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"


def _ctp_strategy_key(backbone: str, strategy_name: str, extra: dict[str, Any]) -> str:
    head_name, std_thresh = _decode_ctp_strategy_name(strategy_name)
    return (
        f"ctp:{backbone}:{extra.get('head', head_name)}:"
        f"{float(extra.get('std_thresh', std_thresh)):.2f}:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"
    )


def _load_global_pool_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    vecs, sids, artists, albums, genres = flat_vecs.load_matrix(backbone, strategy_name, con)
    manifest = _manifest_for(extra_cfg, backbone)
    if manifest is not None:
        # Restrict to the matching corpus in manifest (sorted) order so the flat
        # baseline and candidates share the exact same deterministic corpus.
        idx = {sid: i for i, sid in enumerate(sids)}
        present = [sid for sid in manifest.song_ids if sid in idx]
        keep = [idx[sid] for sid in present]
        sids = present
        artists = [artists[i] for i in keep]
        albums = [albums[i] for i in keep]
        genres = [genres[i] for i in keep]
        vecs = vecs[keep]
    return vecs, sids, artists, albums, genres


def _load_ptc_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    bin_mode, std_thresh = _decode_ptc_strategy_name(strategy_name)
    rep_types = [str(rep) for rep in extra_cfg.get("rep_types", _strategy_binned_constants.REP_TYPES)]

    # Discover in manifest order (or by cache listing when no manifest is wired)
    # so the loader only ever yields songs belonging to the matching corpus.
    manifest = _manifest_for(extra_cfg, backbone)
    if manifest is not None:
        discovery_order: list[str] = list(manifest.song_ids)
    else:
        discovery_order = binned_ptc.list_sids(backbone, bin_mode, std_thresh)

    sids: list[str] = []
    bin_counts: list[int] = []
    weights: list[np.ndarray] = []
    for sid in discovery_order:
        stats_bins = binned_ptc.load_bin_stats(backbone, bin_mode, std_thresh, sid)
        if not stats_bins:
            continue
        sids.append(sid)
        bin_counts.append(len(stats_bins))
        # Temporal patch-count weights: the number of raw patches pooled into each bin.
        weights.append(np.array([b["weight"] for b in stats_bins], dtype=np.int32))

    # Ordering contract: for every song the per-bin patch-count weight array, the
    # ``rep_a`` bin vectors, and the ``rep_b`` bin vectors are built from the same
    # ``stats_bins`` loop, so they are all ordered by the same ascending bin index
    # and are co-indexed.  Validate before returning so any misalignment or zeroed
    # weight array fails loudly instead of producing wrong weighted scores.
    validate_binned_weights(weights, weights, bin_counts)

    artists, albums, genres = _load_song_metadata(con, sids)
    pairs: list[dict[str, Any]] = []
    for rep_a in rep_types:
        for rep_b in rep_types:
            norm_a_all: list[Any] = []
            norm_b_all: list[Any] = []
            for sid in sids:
                norm_a, norm_b = binned_ptc.load_norm_pair(backbone, bin_mode, std_thresh, sid, rep_a, rep_b)
                norm_a_all.append(norm_a)
                norm_b_all.append(norm_b)
            pairs.append(
                {
                    "rep_a": rep_a,
                    "rep_b": rep_b,
                    "norm_a_all": norm_a_all,
                    "norm_b_all": norm_b_all,
                    "bin_counts": bin_counts,
                    "weights_a": weights,
                    "weights_b": weights,
                    "weights": weights,
                }
            )

    return {"pairs": pairs}, sids, artists, albums, genres


def _load_ctp_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    head_name, std_thresh = _decode_ctp_strategy_name(strategy_name)
    rep_types = [str(rep) for rep in extra_cfg.get("rep_types", _strategy_binned_constants.REP_TYPES)]
    manifest = _manifest_for(extra_cfg, backbone)
    song_ids_arg: frozenset[str] | None = frozenset(manifest.song_ids) if manifest is not None else None
    ctp_sids, _ctp_artists, song_data = binned_ctp.load_all_reps(con, backbone, head_name, std_thresh, song_ids_arg)

    filtered_sids: list[str] = []
    filtered_song_data: list[list[dict[str, Any]]] = []
    for sid, bins in zip(ctp_sids, song_data, strict=False):
        if not bins:
            continue
        if not all(f"vec_{rep}_norm" in bin_row for rep in rep_types for bin_row in bins):
            continue
        filtered_sids.append(sid)
        filtered_song_data.append(bins)

    n_dropped = len(ctp_sids) - len(filtered_sids)
    if n_dropped > 0:
        _log.warning(
            "[%s/%s] _load_ctp_analyze_vecs: dropped %d/%d songs (empty bins or missing rep keys %s)",
            backbone,
            strategy_name,
            n_dropped,
            len(ctp_sids),
            rep_types,
        )

    artists, albums, genres = _load_song_metadata(con, filtered_sids)
    bin_counts = [len(song_bins) for song_bins in filtered_song_data]
    # Temporal patch-count weights per song: the number of raw patches per bin.
    weights = [np.array([b["weight"] for b in bins], dtype=np.int32) for bins in filtered_song_data]
    # Ordering contract: ``weights`` are derived from the same per-song bin lists as
    # ``norm_a_all``/``norm_b_all`` (each built by stacking rows in ``bins`` order),
    # so weights, rep_a, and rep_b all share the same song/bin ordering and are
    # co-indexed.  Validate before returning.
    validate_binned_weights(weights, weights, bin_counts)
    pairs: list[dict[str, Any]] = []
    for rep_a in rep_types:
        pairs.extend(
            {
                "rep_a": rep_a,
                "rep_b": rep_b,
                "norm_a_all": [
                    UnitTensor(
                        np.stack([np.asarray(bin_row[f"vec_{rep_a}_norm"], dtype=np.float32) for bin_row in bins])
                    )
                    for bins in filtered_song_data
                ],
                "norm_b_all": [
                    UnitTensor(
                        np.stack([np.asarray(bin_row[f"vec_{rep_b}_norm"], dtype=np.float32) for bin_row in bins])
                    )
                    for bins in filtered_song_data
                ],
                "bin_counts": bin_counts,
                "weights_a": weights,
                "weights_b": weights,
                "weights": weights,
            }
            for rep_b in rep_types
        )

    return {"pairs": pairs}, filtered_sids, artists, albums, genres


# Wires the global-pool strategy (mean/max pooling over all frames) into the shared analyze phase.
GLOBAL_POOL_ANALYZE_CFG: AnalyzeCfg = {
    "strategy_names": list(pooling.STRATEGIES.keys()),
    "load_vecs_fn": _load_global_pool_analyze_vecs,
    "db_write_fn": db.write_analyze_metrics,
    "strategy_key_fn": _global_pool_strategy_key,
    "strategy_type": "global_pool",
    "extra_cfg": {},
}

# Wires the patch-to-centroid (PTC) binned strategy into the shared analyze phase.
# The primary score variant is evaluated per selected temporal mode/threshold.
PTC_ANALYZE_CFG: AnalyzeCfg = {
    "strategy_names": [f"ptc_{bin_mode}_{std_thresh:.2f}" for bin_mode in BIN_MODES for std_thresh in STD_THRESHOLDS],
    "load_vecs_fn": _load_ptc_analyze_vecs,
    "db_write_fn": db.write_analyze_metrics,
    "strategy_key_fn": _ptc_strategy_key,
    "strategy_type": "ptc",
    "extra_cfg": {
        "rep_types": list(_strategy_binned_constants.REP_TYPES),
        "score_variants": list(_strategy_binned_constants.SCORE_VARIANTS),
    },
}

# Wires the centroid-to-patch (CTP) binned strategy (head-guided bins) into the shared analyze phase.
CTP_ANALYZE_CFG: AnalyzeCfg = {
    "strategy_names": [
        f"ctp_{head_name}_{std_thresh:.2f}"
        for head_name in _KNOWN_CTP_HEAD_NAMES
        for std_thresh in CTP_SCORE_THRESHOLDS
    ],
    "load_vecs_fn": _load_ctp_analyze_vecs,
    "db_write_fn": db.write_analyze_metrics,
    "strategy_key_fn": _ctp_strategy_key,
    "strategy_type": "ctp",
    "extra_cfg": {"rep_types": list(_strategy_binned_constants.REP_TYPES)},
}


def _install() -> None:
    _log.info("Installing dependencies from %s ...", _REQ)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", str(_REQ)])
    _log.info("Install complete.")


def _reset_db() -> None:
    """Delete the DuckDB file so the next run starts with a clean schema.

    .npy sidecar patches are intentionally preserved — they are the raw backbone
    outputs and are expensive to regenerate.  Everything else in the DB is
    recomputable from those sidecars.
    """
    if DB_PATH.exists():
        _log.info("Removing existing DB at %s", DB_PATH)
        DB_PATH.unlink()
        _wal = Path(str(DB_PATH) + ".wal")
        if _wal.exists():
            _wal.unlink()
            _log.info("WAL file removed: %s", _wal)
        _log.info("DB removed.  Sidecar patches at %s are preserved.", PATCHES_DIR)
    else:
        _log.info("No DB found at %s — nothing to remove.", DB_PATH)
    _log.info(
        "Reset complete.  Run 'embed classify analyze truncate report' (without --force) to"
        " rebuild from the preserved .npy sidecars, or add 'embed --force' to also"
        " regenerate the sidecars from audio."
    )


def _reset_cache_dirs(*, reset_optimizer: bool, reset_binned: bool) -> None:
    """Delete reset-eligible cache directories.

    The similarity-matrix cache (``cache/sim.py`` / ``cache/sim_pairs.py``) was
    removed in Plan C (write-only, zero-caller), so there is no ``sim_cache`` to
    reset.  Only the optimizer and binned PTC/CTP caches remain reset-eligible.
    """
    dirs: list[Path] = []
    if reset_optimizer:
        dirs.append(OUTPUT_ROOT / "optimizer")
    if reset_binned:
        dirs.extend([OUTPUT_ROOT / "cache" / "binned_ptc", OUTPUT_ROOT / "cache" / "binned_ctp"])

    for d in dirs:
        if d.exists():
            _log.info("Removing cache dir: %s", d)
            shutil.rmtree(d, ignore_errors=True)
        else:
            _log.info("Cache dir not present (skip): %s", d)


def _build_ctp_segment_infra(
    backbone_name: str,
    *,
    heads: list[str] | None,
    device: str,
) -> tuple[dict[str, object], Callable[[Callable[[np.ndarray], np.ndarray], np.ndarray], np.ndarray]]:
    """Build ONNX head inference sessions and a run_in_batches_fn for CTP segmentation.
    Sessions that fail to load are logged and excluded from the returned dict."""
    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session
    from scripts.embedding_research.config import HEAD_VRAM_BYTES

    head_map = {head: model for head, model in HEADS.get(backbone_name, {}).items() if heads is None or head in heads}
    head_sessions: dict[str, object] = {}
    for head_name, head_model_path in head_map.items():
        try:
            head_sessions[head_name] = create_session(
                head_model_path,
                device=device,
                vram_limit_bytes=HEAD_VRAM_BYTES,
            )
        except Exception as exc:
            _log.error("[%s/%s] Failed to load head: %s", backbone_name, head_name, exc)

    def run_in_batches_fn(predict_fn: Callable[[np.ndarray], np.ndarray], inputs: np.ndarray) -> np.ndarray:
        return _run_in_batches(predict_fn, inputs, _BACKBONE_BATCH_SIZE)

    return head_sessions, run_in_batches_fn


def _ingest_phase(con, cfg: dict) -> None:
    from scripts.embedding_research.strategy_meta import ingest

    ingest(con, limit=cfg["limit"], force=cfg["force"])


def _embed_phase(con, cfg: dict) -> None:
    common.embed.embed(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        device=cfg["device"],
        backbone_sessions=cfg["cache"].backbone_sessions if cfg.get("cache") else None,
    )


def _stratify_phase(con, cfg: dict) -> None:
    from scripts.embedding_research.common.stratify import run_stratify

    raw_bytes = _load_raw_cfg()
    config_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
    before = len(cfg["song_ids"]) if cfg["song_ids"] is not None else "?"
    stratified = run_stratify(con, cfg, config_hash)
    cfg["song_ids"] = stratified
    _log.info("[stratify] song_ids: %s → %d (config_hash=%s)", before, len(stratified), config_hash)


def _segment_phase(con, cfg: dict) -> None:
    _kw = {"song_ids": cfg["song_ids"], "force": cfg["force"], "backbones": cfg["backbones"]}
    common.segment.segment(
        con,
        _gp_seg_fn.segment_fn,
        cfg["flat_strategies"],
        **_kw,
        extra_cfg={"skip_check_fn": _gp_seg_fn.SKIP_CHECK_FN, "cache_write_fn": _gp_seg_fn.CACHE_WRITE_FN},
    )
    common.segment.segment(
        con,
        _ptc_seg_fn.make_segment_fn(con),
        PTC_STRATEGY_NAMES,
        **_kw,
        extra_cfg={"skip_check_fn": _ptc_seg_fn.SKIP_CHECK_FN, "cache_write_fn": _ptc_seg_fn.CACHE_WRITE_FN},
    )
    # Deferred/archival CTP segmentation is phase-gated: with ``[archival_ctp]
    # enabled=false`` (the default) NO CTP segment work runs here — no head
    # sessions are built, no ``binned_ctp`` segment caches are written, and no
    # CTP strategy rows are produced.  Empty CTP tables/caches are the expected
    # correct state (DD U6: the phase-level zero-row gate accepts empty CTP
    # tables as correct, not corruption).  Explicit opt-in re-enables it.
    if _ctp_enabled():
        cache: ModelCache | None = cfg.get("cache")
        for backbone_name in list(cfg["backbones"]) if cfg["backbones"] is not None else list(HEADS):
            if cache is not None:
                head_sessions = cache.head_sessions.get(backbone_name, {})
                run_in_batches_fn = cache.run_in_batches_fn
            else:
                head_sessions, run_in_batches_fn = _build_ctp_segment_infra(
                    backbone_name, heads=cfg.get("heads"), device=cfg["device"]
                )
            if not head_sessions:
                continue
            common.segment.segment(
                con,
                _ctp_seg_fn.make_segment_fn(head_sessions, run_in_batches_fn),
                _ctp_seg_fn.make_strategy_names(head_sessions.keys()),
                song_ids=cfg["song_ids"],
                force=cfg["force"],
                backbones=[backbone_name],
                extra_cfg={
                    "skip_check_fn": _ctp_seg_fn.SKIP_CHECK_FN,
                    "cache_write_fn": _ctp_seg_fn.CACHE_WRITE_FN,
                },
            )


def _classify_phase(con, cfg: dict) -> None:
    from scripts.embedding_research.classify import run_binned, run_flat

    _cache: ModelCache | None = cfg.get("cache")
    _head_sessions = _cache.head_sessions if _cache is not None else None

    _log.info("  -> sub-phase: flat classify")
    _t0 = time.perf_counter()
    run_flat(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        heads=cfg["heads"],
        device=cfg["device"],
        head_sessions=_head_sessions,
    )
    _log.info("  <- sub-phase: flat classify done (%.0fs)", time.perf_counter() - _t0)

    _log.info("  -> sub-phase: binned classify")
    _t0 = time.perf_counter()
    run_binned(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        heads=cfg["heads"],
        device=cfg["device"],
        thresholds_by_backbone=cfg.get("thresholds_by_backbone"),
        head_sessions=_head_sessions,
    )
    _log.info("  <- sub-phase: binned classify done (%.0fs)", time.perf_counter() - _t0)


def _manifest_for(extra_cfg: Mapping[str, Any] | None, backbone: str) -> MatchingCorpusManifest | None:
    """Resolve the per-backbone matching corpus from an analyze extra_cfg."""
    manifests = (extra_cfg or {}).get("matching_corpus") or {}
    return manifests.get(backbone)  # type: ignore[return-value]


def _ctp_enabled() -> bool:
    """Return whether the deferred/archival CTP switch is enabled.

    Reads ``[archival_ctp] enabled`` from research_config.toml.  Default is
    disabled: CTP requirements, rows, and winner candidates are excluded from
    the default primary corpus and primary report grid, while CTP segment
    functions, caches, and archival loaders remain available for explicit
    opt-in (set ``enabled = true``).
    """
    return bool(_load_research_config().get("archival_ctp", {}).get("enabled", False))


def _corpus_requirements(backbone: str, flat_strategies: Sequence[str]) -> dict[str, list[str]]:
    """Availability of every sidecar/bin/rep requirement for one backbone.

    Follow-on primary algorithm: the matching corpus for a backbone is the
    stratified candidate universe intersected with ``flat:medoid`` and every
    selected PTC ``(bin_mode, threshold, rep_type=medoid, score_variant)``
    sidecar, canonically sorted and hashed with the backbone plus eligibility
    and scoring-semantics dimensions.  Each requirement maps a
    namespace-separated label to the sorted list of song IDs for which that
    sidecar/bin/rep is available on disk; a song is eligible only if it appears
    in every requirement.  CTP is omitted from this intersection unless the
    ``[archival_ctp]`` deferred/archival switch is explicitly enabled.
    """
    reqs: dict[str, list[str]] = {}
    for strat in flat_strategies:
        reqs[f"flat:{strat}"] = flat_vecs.list_done_sids(backbone, strat)
    for bin_mode in BIN_MODES:
        for std_thresh in STD_THRESHOLDS:
            reqs[f"ptc:{bin_mode}:{std_thresh:.2f}"] = binned_ptc.list_sids(backbone, bin_mode, std_thresh)
    if _ctp_enabled():
        for head_name in _KNOWN_CTP_HEAD_NAMES:
            for std_thresh in CTP_SCORE_THRESHOLDS:
                cfg_dir = binned_ctp.config_dir(backbone, head_name, std_thresh)
                reqs[f"ctp:{head_name}:{std_thresh:.2f}"] = sorted(_build_done_set(cfg_dir, suffix=".npz"))
    return reqs


def _build_backbone_manifests(cfg: Mapping[str, Any]) -> dict[str, MatchingCorpusManifest]:
    """Deterministic per-backbone matching corpus over the candidate universe.

    The corpus for a backbone is the sorted intersection of the stratified
    candidate universe with ``flat:medoid`` and every selected PTC
    ``(bin_mode, threshold, rep_type=medoid, score_variant)`` requirement
    (CTP excluded unless the archival switch is enabled), so every compared
    primary configuration runs on the exact same ``n_songs``.  The backbone,
    membership, eligibility dimensions, scoring-semantics version, and boundary
    configuration feed the stable corpus hash.
    """
    backbones = list(cfg.get("backbones") or BACKBONES)
    flat_strategies = list(cfg.get("flat_strategies") or [])
    candidate_ids = cfg.get("song_ids")
    # Eligibility dimensions hashed with the backbone, membership, and scoring-
    # semantics version: the scoring surface actually evaluated (score_variants),
    # the per-bin representations, and the scoring-semantics version.  The
    # per-config boundary configuration (PTC bin modes/thresholds) is already
    # folded into the corpus hash via the sorted requirement labels.
    eligibility: dict[str, object] = {
        "rep_types": sorted(_strategy_binned_constants.REP_TYPES),
        "score_variants": list(_strategy_binned_constants.SCORE_VARIANTS),
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "k": cfg.get("k", 10),
    }
    manifests: dict[str, MatchingCorpusManifest] = {}
    for backbone in backbones:
        reqs = _corpus_requirements(backbone, flat_strategies)
        if candidate_ids is not None:
            universe: Collection[str] = candidate_ids
        else:
            universe = sorted({sid for avail in reqs.values() for sid in avail})
        manifest = build_matching_corpus(backbone, universe, reqs, eligibility_inputs=eligibility)
        manifests[backbone] = manifest
        _log.info(
            "[%s] matching corpus: %d songs hash=%s",
            backbone,
            len(manifest),
            manifest.corpus_hash[:12],
        )
    return manifests


def _analyze_phase(con, cfg: dict) -> None:
    # LEGACY interim full-matrix analysis path (common.analyze) — retained until Plan E rewires run.py
    # to the catalog-first primary path (common/catalog_analysis.py).  P3-S4: the old global
    # `DELETE FROM analyze_metrics` is removed.  An analysis run only touches rows it owns.  With
    # force=False (the default) common.analyze SKIPS every strategy already in its done_set — a second
    # normal run writes nothing new and preserves those strategies' existing rows unchanged; only
    # force=True or a cold (empty) analyze_metrics table triggers the per-strategy INSERT OR REPLACE
    # (replacing that strategy's own (strategy_key, sim_metric, k) rows and clearing only that
    # strategy's per-song rows).  baseline/corpus rows and unrelated retained runs
    # (run_provenance.retained=True) are preserved.  The physical run_id migration and per-run row
    # identification are owned by the reset/cleanup plan (Plan E); the run-scoped write/reader
    # contract that prepares for it lives in db.analyze_scope.
    _kw = {"song_ids": cfg["song_ids"], "force": cfg["force"], "backbones": cfg["backbones"], "k": cfg["k"]}
    manifests = _build_backbone_manifests(cfg)
    cfg["matching_corpus"] = manifests
    _corpus_kw = {"matching_corpus": manifests}
    _gp_cfg = dict(GLOBAL_POOL_ANALYZE_CFG)
    _gp_cfg["strategy_names"] = cfg["flat_strategies"]
    _gp_cfg["extra_cfg"] = dict(_gp_cfg["extra_cfg"], **_corpus_kw)
    common.analyze.analyze(con, _gp_cfg, **_kw)
    _ptc_cfg = dict(PTC_ANALYZE_CFG)
    _ptc_cfg["extra_cfg"] = dict(_ptc_cfg["extra_cfg"], **_corpus_kw)
    common.analyze.analyze(con, _ptc_cfg, **_kw)
    # Deferred/archival CTP path: opt-in only, visibly separated from primary
    # output.  Disabled by default so CTP rows never enter the primary grid.
    if _ctp_enabled():
        _ctp_cfg = dict(CTP_ANALYZE_CFG)
        _ctp_cfg["extra_cfg"] = dict(_ctp_cfg["extra_cfg"], **_corpus_kw)
        common.analyze.analyze(con, _ctp_cfg, **_kw)


def _head_phase(con, cfg: dict) -> None:
    """Optional shared-boundary head phase: pool EffNet PTC boundary head outputs.

    Runs AFTER primary analysis (``analyze``) so the PTC boundaries/classification
    prerequisites and the primary EffNet corpus manifest already exist.  It is
    non-blocking: ``classify.run_shared_ptc_head_pooling`` returns a
    :class:`HeadPhaseManifest` and never raises, so primary EffNet PTC-vs-medoid
    analysis completes regardless of head-model/head-cache availability.  It never
    deletes primary rows and never mutates the corpus.

    The head phase operates on exactly the primary EffNet corpus songs that also
    have head-cache availability (a clearly declared derived head-availability
    subset).  LEGACY interim (Phase 1 D1): this glue remains callable through
    Phase 4 and appends ONLY read-only archival provenance rows
    (``run_id='legacy'`` with the legacy ``threshold`` populated and canonical-only
    fields NULL).  It never dual-writes, never creates a canonical current row, and
    never calls the canonical CPU runner/persistence.  The manifest is stored on
    *cfg* for the report phase's status hook.
    """
    from scripts.embedding_research.classify import run_shared_ptc_head_pooling
    from scripts.embedding_research.db.head_phase import (
        append_head_phase_archival_rows,
        build_archival_provenance_rows,
    )

    # Reference corpus: the primary EffNet matching-corpus manifest built during
    # analyze.  The head phase is scoped to these songs (derived subset), so it
    # never silently discovers a different set.
    reference_song_ids: frozenset[str] | None = None
    reference_corpus_hash: str | None = None
    primary_manifests = cfg.get("matching_corpus") or {}
    effnet_manifest = primary_manifests.get("effnet")
    if effnet_manifest is None and primary_manifests:
        effnet_manifest = next(iter(primary_manifests.values()))
    if effnet_manifest is not None:
        reference_song_ids = frozenset(effnet_manifest.song_ids)
        reference_corpus_hash = effnet_manifest.corpus_hash

    manifest = run_shared_ptc_head_pooling(
        con,
        song_ids=reference_song_ids,
        backbones=cfg.get("backbones"),
        heads=cfg.get("heads"),
        force=cfg.get("force", False),
    )
    append_head_phase_archival_rows(
        con,
        build_archival_provenance_rows(manifest, reference_corpus_hash=reference_corpus_hash),
    )
    cfg["head_phase_manifest"] = manifest
    if manifest.errors or (manifest.done == 0 and sum(r.n_pooled for r in manifest.results) == 0):
        _log.warning(
            "head phase produced no pooled output (done=%d skipped=%d errors=%d); "
            "surfacing as a report warning; primary analysis is unaffected",
            manifest.done,
            manifest.skipped,
            manifest.errors,
        )


def _report_phase(con, cfg: dict) -> None:
    from scripts.embedding_research.config import REPORT_DIR
    from scripts.embedding_research.report import run

    # Minimal head-phase status hook (Plan B, Phase 2).  A head-phase failure or
    # total-skip is surfaced as a report warning — it is NEVER a primary-row
    # deletion or corpus mutation, and Phase 3 owns the full head-output report
    # section.  Here we only warn so the operator sees the preparation status.
    _manifest = cfg.get("head_phase_manifest")
    if _manifest is not None:
        if _manifest.errors:
            _log.warning(
                "head phase finished with %d error config(s); primary analysis is unaffected",
                _manifest.errors,
            )
        if _manifest.done == 0 and sum(r.n_pooled for r in _manifest.results) == 0:
            _log.warning(
                "head phase produced no pooled output (skipped=%d errors=%d); "
                "shared-boundary head outputs are unavailable in this report",
                _manifest.skipped,
                _manifest.errors,
            )
        else:
            _log.info(
                "head phase: done=%d skipped=%d errors=%d (reference EffNet corpus declared)",
                _manifest.done,
                _manifest.skipped,
                _manifest.errors,
            )

    run(
        con,
        REPORT_DIR,
        matching_corpora=cfg.get("matching_corpus"),
        head_phase_manifest=cfg.get("head_phase_manifest"),
    )


# ---------------------------------------------------------------------------
# LEGACY all-in-one orchestration (retired from the CLI in Phase 4).
# ---------------------------------------------------------------------------
# The run.py-owned orchestration functions above (`_ingest_phase` …
# `_report_phase`) and the `_LEGACY_PHASES` map drove the old whole-pipeline
# loop (ingest->embed->stratify->segment->classify->analyze->head->report) in a
# single sequential pass.  The Phase 4 CLI below replaces that loop with the
# eight explicit phases + cleanup/reset maintenance.  These legacy functions are
# RETAINED — not deleted — because tests import their helpers (`_head_phase`,
# `_load_global_pool_analyze_vecs`, `_ptc_strategy_key`, `_ctp_strategy_key`,
# …) and because the D1 interim contract keeps classify.py's LEGACY
# `run_shared_ptc_head_pooling` + head_pooling.py + the run.py `_head_phase`
# archival glue callable through Phase 4 (archival-only; residual cleanup is
# Plan F).  They are intentionally NOT wired into the new dispatch, so derived
# phases cannot reach them.
# ---------------------------------------------------------------------------

_LEGACY_PHASES: dict[str, Callable[..., None]] = {
    "ingest": _ingest_phase,
    "embed": _embed_phase,
    "stratify": _stratify_phase,
    "segment": _segment_phase,
    "classify": _classify_phase,
    "analyze": _analyze_phase,
    "head": _head_phase,
    "report": _report_phase,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — explicit phase CLI + run provenance (DD "CLI and provenance").
# ═══════════════════════════════════════════════════════════════════════════════
#
# The CLI exposes EXACTLY eight phases: ingest, embed, infer-heads, catalog,
# catalog-report, analyze, head-analysis, report — plus cleanup and reset as
# EXPLICIT SEPARATE maintenance operations (wired to cleanup.py scopes / the
# legacy reset helpers, not to the phase sequence).
#
# CPU/inference boundaries (DD): only the first three phases may discover audio,
# load models, create ML sessions or run ONNX.  The five derived phases are
# routed exclusively through the canonical CPU modules below; they never reach
# the audio/model/ONNX/CUDA surfaces in this file (legacy orchestration,
# model-cache builders) or classify.py/head_pooling.py.  Each derived-phase
# runner below imports ONLY from CPU-only modules — see tests
# test_phase4_dispatch_boundaries.py for the structural (phase-call-graph) proof.
#
# Stratification is catalog input/config generation, NOT a phase: the `catalog`
# phase selects its corpus subset from the song registry using the [stratify]
# budget/config (common.stratify.run_stratify) and then builds the segmentation
# catalog over that subset.  There is no `stratify` CLI phase.
#
# run_id scheme: every phase records one auditable run_provenance row per
# invocation.  run_id = "{phase}-{started_at_ms}" (INTEGER millisecond
# timestamp) — FRESH per invocation.  Idempotency is provided by each canonical
# phase's own skip/replace semantics (embed/infer-heads skip already-ready
# streams; catalog reuses config_id by canonical hash and replaces only that
# config's rows; analyze writes run-scoped replace), so run_id is deliberately
# NOT reused across invocations.  `--retained` opts a run into retained=true so
# view/reset GC protects it.  embed / infer-heads / analyze record their own
# run_provenance row(s) inside their canonical modules (single-source); ingest,
# catalog, catalog-report, head-analysis and report have their row recorded
# here by the CLI.
# ═══════════════════════════════════════════════════════════════════════════════

CLI_PHASES: tuple[str, ...] = (
    "ingest",
    "embed",
    "infer-heads",
    "catalog",
    "catalog-report",
    "analyze",
    "head-analysis",
    "report",
)

# Legacy phase names that previously mapped to opaque orchestration.  They are
# NOT valid new-CLI phase names: selecting one is a clear error (never a silent
# alias), per CONTRACTS.md CLI boundaries.
LEGACY_PHASE_ALIASES: frozenset[str] = frozenset({"stratify", "segment", "classify", "head"})

AUDIO_PHASES: frozenset[str] = frozenset({"ingest", "embed", "infer-heads"})
DERIVED_PHASES: frozenset[str] = frozenset(CLI_PHASES) - AUDIO_PHASES

# A derived-phase runner may import/reference ONLY from these CPU-only modules
# (research-relative dotted paths under ``scripts.embedding_research``).
# (Used by tests/test_phase4_dispatch_boundaries.py as the phase-call-graph
# proof that derived paths cannot reach audio/model/ONNX/CUDA surfaces.)
DERIVED_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        # top-level CPU modules
        "catalog",
        "catalog_identity",
        "catalog_report",
        "config",
        "report",
        "streams",
        # db/* CPU persistence modules
        "db.analyze_scope",
        "db.songs",
        "db.head_phase",
        # common/* canonical CPU analysis modules
        "common.catalog_analysis",
        "common.head_analysis",
    }
)

# Forbidden on derived-phase paths.  (mirrors the P2-S3 sentinel surfaces)
DERIVED_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "discover_audio",
        "create_session",
        "inference_session",
        "_run_in_batches",
        "run_in_batches_fn",
        "onnxruntime",
        "torch",
        "cuda",
        "bootstrap_nomarr",
        "model_cache",
        "classify",
        "head_pooling",
        "segment_fn",
    }
)


# ── provenance / run helpers ───────────────────────────────────────────────────


def _software_versions() -> str:
    """Compact software-version line recorded in run_provenance."""
    return f"python={sys.version.split()[0]} duckdb={duckdb.__version__} numpy={np.__version__}"


def _command_line() -> str:
    """The argv line that invoked this CLI (recorded in run_provenance)."""
    return " ".join(sys.argv)


def _record_phase_run(
    con,
    *,
    run_id: str,
    phase: str,
    status: str,
    started_at: int,
    finished_at: int,
    config_hash: str = "",
    song_count: int = 0,
    warning_count: int = 0,
    retained: bool = False,
    output_artifact_hashes: str = "",
    input_artifact_hashes: str = "",
    structural_change_summary: str = "",
) -> None:
    """Append one run_provenance row for a phase invocation (INTEGER-ms stamps)."""
    from scripts.embedding_research.db.provenance import write_run_provenance

    write_run_provenance(
        con,
        run_id=run_id,
        phase=phase,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        output_artifact_hashes=output_artifact_hashes,
        input_artifact_hashes=input_artifact_hashes,
        config_hash=config_hash,
        song_count=song_count,
        warning_count=warning_count,
        software_versions=_software_versions(),
        command_line=_command_line(),
        structural_change_summary=structural_change_summary,
        retained=retained,
    )


def _mark_run_retained(con, run_id: str, phase: str) -> None:
    """Flip a phase's own provenance row(s) to retained=true (post --retained)."""
    con.execute(
        "UPDATE run_provenance SET retained = 1 WHERE run_id = ? AND phase = ?",
        (run_id, phase),
    )


# ── catalog input generation (stratification-as-input, never a phase) ──────────


def _catalog_seg_configs(cfg: dict) -> list:
    """Build the segmentation-config list for one pass over the [binning] grid.

    One :class:`~scripts.embedding_research.catalog.SegConfigInput` per
    (backbone, bin_mode, threshold) combination.  Backbones/bin-modes/thresholds
    come from ``cfg`` (populated from research_config.toml ``[pipeline]`` /
    ``[binning]`` by main; overridable in tests).
    """
    from scripts.embedding_research.catalog import SegConfigInput

    backbones = cfg.get("backbones") or ["effnet"]
    bin_modes = cfg.get("catalog_bin_modes") or ["temporal_global"]
    thresholds = [float(t) for t in (cfg.get("catalog_thresholds") or [0.7])]
    return [
        SegConfigInput(
            backbone=backbone,
            bin_mode=bin_mode,
            threshold_configured=threshold,
            threshold_effective=threshold,
            semantics="direct_l2",
        )
        for backbone in backbones
        for bin_mode in bin_modes
        for threshold in thresholds
    ]


def _catalog_corpus_song_ids(con, cfg: dict) -> list[str]:
    """Select the corpus subset the `catalog` phase catalogs.

    Stratification is represented as catalog input/config generation (never a
    standalone phase): with a positive ``[pipeline].limit`` the corpus is the
    budgeted subset from ``common.stratify.run_stratify``; with the default
    limit (0 = no cap) the corpus is the full song registry.  Falls back to the
    full registry if stratification cannot select (defensive; never blocks).
    """
    from scripts.embedding_research.db.songs import load_all_songs

    registry = sorted(r["song_id"] for r in load_all_songs(con))
    limit = cfg.get("limit")
    if not limit:
        return registry
    try:
        config_hash = cfg.get("config_hash") or ""
        from scripts.embedding_research.common.stratify import run_stratify

        selected = run_stratify(con, cfg, config_hash)
        if selected:
            return sorted(selected)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("stratification could not select a corpus; using full registry: %s", exc)
    return registry


def _analysis_corpus_song_ids(con, backbone: str) -> list[str]:
    """The songs actually cataloged (seg_meta rows) for *backbone*'s canonical configs.

    Derived `analyze` reads its corpus from the frozen catalog rows (the real
    cataloged corpus) rather than re-selecting.
    """
    rows = con.execute(
        """
        SELECT DISTINCT sm.song_id
        FROM seg_meta sm
        JOIN seg_config c ON c.config_id = sm.config_id
        WHERE c.backbone = ? AND c.alias_of_config_id IS NULL
        ORDER BY 1
        """,
        (backbone,),
    ).fetchall()
    return [r[0] for r in rows]


# ── phase runners ──────────────────────────────────────────────────────────────
# ingest / embed / infer-heads are AUDIO phases (may load models / run ONNX).


def _run_ingest(con, cfg: dict, _run_id: str) -> dict:
    """ingest: discover audio + register normalized corpus songs (AUDIO phase)."""
    from scripts.embedding_research.db.songs import load_all_songs
    from scripts.embedding_research.strategy_meta import ingest as _strategy_meta_ingest

    _strategy_meta_ingest(con, force=bool(cfg.get("force", False)))
    return {"song_count": len(load_all_songs(con))}


def _run_embed(con, cfg: dict, run_id: str) -> dict:
    """embed: bounded backbone inference -> immutable streams/registry (AUDIO phase)."""
    from scripts.embedding_research.common.embed import embed as _embed

    _embed(
        con,
        force=bool(cfg.get("force", False)),
        backbones=cfg.get("backbones"),
        device=cfg.get("device", "cpu"),
        run_id=run_id,
    )
    # embed records its own run_provenance row (single source).
    return {"self_recorded": True}


def _run_infer_heads(con, cfg: dict, run_id: str) -> dict:
    """infer-heads: aligned classifier head streams -> registry (AUDIO phase)."""
    from scripts.embedding_research.common.infer_heads import infer_heads as _infer_heads

    _infer_heads(
        con,
        force=bool(cfg.get("force", False)),
        backbones=cfg.get("backbones"),
        heads=cfg.get("heads"),
        device=cfg.get("device", "cpu"),
        run_id=run_id,
    )
    # infer-heads records its own run_provenance row (single source).
    return {"self_recorded": True}


# ── phase runners: DERIVED (CPU-only) ──────────────────────────────────────────
# Each derived runner imports only from DERIVED_ALLOWED_IMPORT_ROOTS and never
# references DERIVED_FORBIDDEN_TOKENS (proved by test_phase4_dispatch_boundaries.py).


def _run_catalog(con, cfg: dict, run_id: str) -> dict:
    """catalog: verify streams, select corpus + configs, build seg catalog (CPU)."""
    from scripts.embedding_research.catalog import build_segmentation_catalog
    from scripts.embedding_research.streams import StreamStore

    out_root = cfg.get("output_root") or OUTPUT_ROOT
    configs = _catalog_seg_configs(cfg)
    song_ids = _catalog_corpus_song_ids(con, cfg)
    store = StreamStore(con, output_root=str(out_root))
    build_segmentation_catalog(
        con,
        store,
        configs,
        song_ids,
        run_id=run_id,
        verify=bool(cfg.get("verify", False)),
    )
    return {"song_count": len(song_ids)}


def _run_catalog_report(con, cfg: dict, _run_id: str) -> dict:
    """catalog-report: render catalog configs/aliases/segments + provenance (CPU)."""
    from scripts.embedding_research.catalog_identity import CATALOG_SEMANTICS_VERSION
    from scripts.embedding_research.catalog_report import build_catalog_report, report_to_text

    report = build_catalog_report(con, schema_version=CATALOG_SEMANTICS_VERSION)
    out_dir = Path(cfg.get("report_dir") or OUTPUT_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "catalog_report.txt").write_text(report_to_text(report), encoding="utf-8")
    _log.info("catalog-report: canonical configs=%d aliases=%d", len(report.canonical_config_ids), report.alias_count)
    return {"song_count": 0, "output_artifact_hashes": "catalog_report.txt"}


def _run_analyze(con, cfg: dict, run_id: str) -> dict:
    """analyze: gather disposable views + bounded exact scoring -> run-scoped metrics (CPU)."""
    from scripts.embedding_research.common.catalog_analysis import (
        CatalogAnalysisConfig,
        analyze_catalog_corpus,
    )
    from scripts.embedding_research.db.analyze_scope import write_catalog_analyze_rows
    from scripts.embedding_research.db.songs import load_all_songs
    from scripts.embedding_research.streams import StreamStore

    out_root = cfg.get("output_root") or OUTPUT_ROOT
    store = StreamStore(con, output_root=str(out_root))
    artists = {r["song_id"]: (r["artist"] or "unknown") for r in load_all_songs(con)}
    total = 0
    for backbone in cfg.get("backbones") or ["effnet"]:
        song_ids = _analysis_corpus_song_ids(con, backbone)
        if not song_ids:
            _log.warning("analyze: no cataloged corpus for backbone %r — run `catalog` first", backbone)
            continue
        analysis_cfg = CatalogAnalysisConfig(
            run_id=run_id,
            backbone=backbone,
            song_ids=tuple(song_ids),
            artists=artists,
            k=int(cfg.get("k", 10)),
        )
        result = analyze_catalog_corpus(store, con, analysis_cfg)
        write_catalog_analyze_rows(con, run_id=run_id, result=result)
        total += len(song_ids)
    # analyze records its own run_provenance row via materialize/record_*_scope.
    return {"song_count": total, "self_recorded": True}


def _run_head_analysis(con, cfg: dict, run_id: str) -> dict:
    """head-analysis: CPU head pooling/medoid over memberships + shared PTC (CPU)."""
    from scripts.embedding_research.common.head_analysis import run_shared_ptc_head_pooling
    from scripts.embedding_research.db.head_phase import (
        build_head_phase_provenance_rows,
        write_head_phase_provenance,
    )
    from scripts.embedding_research.streams import HeadStreamStore

    out_root = cfg.get("output_root") or OUTPUT_ROOT
    head_store = HeadStreamStore(con, output_root=str(out_root))
    manifest = run_shared_ptc_head_pooling(
        con,
        head_store,
        run_id=run_id,
        force=bool(cfg.get("force", False)),
    )
    rows = build_head_phase_provenance_rows(manifest)
    write_head_phase_provenance(con, rows)
    _log.info(
        "head-analysis: run_id=%s done=%d skipped=%d errors=%d finite=%s",
        run_id,
        manifest.done,
        manifest.skipped,
        manifest.errors,
        manifest.finite,
    )
    return {"song_count": len(manifest.song_ids)}


def _run_report(con, cfg: dict, _run_id: str) -> dict:
    """report: render results + provenance, never infers (CPU)."""
    from scripts.embedding_research.config import REPORT_DIR as _REPORT_DIR
    from scripts.embedding_research.report import run as _report_run

    out_dir = Path(cfg.get("report_dir") or _REPORT_DIR)
    _report_run(con, out_dir)
    return {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}


CLI_PHASE_RUNNERS: dict[str, Callable[..., dict]] = {
    "ingest": _run_ingest,
    "embed": _run_embed,
    "infer-heads": _run_infer_heads,
    "catalog": _run_catalog,
    "catalog-report": _run_catalog_report,
    "analyze": _run_analyze,
    "head-analysis": _run_head_analysis,
    "report": _run_report,
}


# ── single-phase executor (provenance wrapper) ─────────────────────────────────


_DERIVED_CONSUMER_PHASES = frozenset({"catalog-report", "analyze", "head-analysis", "report"})


def _has_canonical_catalog(con) -> bool:
    """True when at least one canonical (non-alias) seg_config row exists."""
    n = con.execute("SELECT count(*) FROM seg_config WHERE alias_of_config_id IS NULL").fetchone()[0]
    return bool(n)


def _has_analyze_metrics(con) -> bool:
    """True when at least one non-legacy (run-scoped) analyze_metrics row exists."""
    n = con.execute("SELECT count(*) FROM analyze_metrics WHERE run_id <> 'legacy'").fetchone()[0]
    return bool(n)


def _canonical_config_duplicates(con) -> int:
    """Count of canonical seg_config identities (by canonical_config_hash) that collide."""
    return int(
        con.execute(
            "SELECT count(*) FROM ("
            "  SELECT canonical_config_hash FROM seg_config"
            "  WHERE alias_of_config_id IS NULL"
            "  GROUP BY canonical_config_hash HAVING count(*) > 1)"
        ).fetchone()[0]
    )


def _preflight_derived_phase(con, phase: str, cfg: dict, *, db_path=None) -> list[str]:
    """Post-crash canary + artifact-presence gate for the five derived phases.

    Thin by default: a clean run with no ``--verify`` and no detected post-crash
    state performs only the cheap post-crash detection and returns immediately.
    ``--verify`` (and therefore ``--strict``) additionally run the rollback-only
    canary over every surviving PK/UNIQUE table (DD ``Post-crash verification
    canary``) and check required derived inputs are present.  Under ``--strict``
    any recorded corruption, unresolved duplicate, or missing required artifact
    becomes a hard refusal (raised here, recorded as a ``failed`` provenance row,
    and propagated to the caller).  Plain ``--verify`` records the same conditions
    as warnings and continues — never blocks on a warning.

    Returns the list of verification/reuse notes to fold into the phase's
    run_provenance ``structural_change_summary`` / ``warning_count``.
    """
    if phase not in DERIVED_PHASES:
        return []
    verify = bool(cfg.get("verify"))
    strict = bool(cfg.get("strict"))
    from scripts.embedding_research.db.canary import detect_post_crash, run_rollback_canary

    post_crash = detect_post_crash(con, db_path=db_path)
    if not verify and not post_crash:
        return []  # thin gate: clean run without --verify pays no probe cost.

    notes: list[str] = []
    # 1) rollback-only canary over every surviving PK/UNIQUE table.
    canary_report = run_rollback_canary(con)
    notes.append(f"canary ok: {len(canary_report.ok)} probed, {len(canary_report.empty)} empty")
    # 2) required derived inputs (only consumers read catalog/analyze artifacts).
    if phase in _DERIVED_CONSUMER_PHASES:
        if not _has_canonical_catalog(con):
            msg = f"phase {phase!r}: no canonical catalog (seg_config canonical rows) present"
            if strict:
                raise _MissingArtifactError(msg)
            notes.append(f"warning: {msg}")
        elif phase == "report" and not _has_analyze_metrics(con):
            msg = "phase 'report': no run-scoped analyze_metrics rows present to render"
            if strict:
                raise _MissingArtifactError(msg)
            notes.append(f"warning: {msg}")
        elif _canonical_config_duplicates(con):
            msg = f"phase {phase!r}: unresolved duplicate canonical config identity"
            if strict:
                raise _DuplicateIdentityError(msg)
            notes.append(f"warning: {msg}")
        else:
            notes.append(f"{phase}: reuse existing verified catalog/analyze inputs")
    return notes


class _MissingArtifactError(RuntimeError):
    """Raised under ``--verify --strict`` when a required derived input is absent."""


class _DuplicateIdentityError(RuntimeError):
    """Raised under ``--verify --strict`` on an unresolved duplicate application identity."""


def _run_single_phase(con, phase: str, cfg: dict, *, db_path=None) -> None:
    """Execute exactly one CLI phase with run-scoped provenance."""
    started_at = int(time.time() * 1000)
    run_id = cfg.get("run_id") or f"{phase}-{started_at}"
    runner = CLI_PHASE_RUNNERS[phase]
    meta: dict = {}
    pre_notes: list[str] = []
    try:
        pre_notes = _preflight_derived_phase(con, phase, cfg, db_path=db_path)
        meta = runner(con, cfg, run_id) or {}
    except Exception:
        _record_phase_run(
            con,
            run_id=run_id,
            phase=phase,
            status="failed",
            started_at=started_at,
            finished_at=int(time.time() * 1000),
            config_hash=cfg.get("config_hash", ""),
            song_count=int(meta.get("song_count", 0)),
            warning_count=int(meta.get("warning_count", 0)),
            retained=bool(cfg.get("retained", False)),
        )
        _log.error("phase %r failed (run_id=%s)", phase, run_id)
        raise
    finished_at = int(time.time() * 1000)
    notes = list(pre_notes)
    if meta.get("notes"):
        notes.extend(str(n) for n in meta["notes"])
    summary = "; ".join(notes) if notes else ""
    warning_count = int(meta.get("warning_count", len(notes)))
    if meta.get("self_recorded"):
        # The canonical module owns its run_provenance row(s); only honor --retained.
        if cfg.get("retained"):
            _mark_run_retained(con, run_id, phase)
        _log.info("phase %s complete  run_id=%s  (module-recorded provenance)", phase, run_id)
        return
    _record_phase_run(
        con,
        run_id=run_id,
        phase=phase,
        status="completed",
        started_at=started_at,
        finished_at=finished_at,
        config_hash=cfg.get("config_hash", ""),
        song_count=int(meta.get("song_count", 0)),
        warning_count=warning_count,
        retained=bool(cfg.get("retained", False)),
        output_artifact_hashes=meta.get("output_artifact_hashes", ""),
        input_artifact_hashes=meta.get("input_artifact_hashes", ""),
        structural_change_summary=summary,
    )
    _log.info("phase %s complete  run_id=%s", phase, run_id)


class _MemoryWatcher:
    """Background daemon thread that logs process RSS memory every *interval* seconds."""

    def __init__(self, interval: float = 120.0) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mem-watcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 2)

    @staticmethod
    def _rss_mb() -> float | None:
        try:
            import psutil as _ps  # type: ignore[import]

            return float(_ps.Process().memory_info().rss) / 1_048_576
        except ImportError:
            pass
        try:
            # Linux fallback: /proc/self/status (no psutil required)
            _status = Path("/proc/self/status").read_text()
            for _line in _status.splitlines():
                if _line.startswith("VmRSS:"):
                    return int(_line.split()[1]) / 1024  # kB -> MB
        except OSError:
            pass
        return None

    def _run(self) -> None:
        _wlog = logging.getLogger(__name__ + ".mem")
        while not self._stop.wait(self._interval):
            _mb = self._rss_mb()
            if _mb is not None:
                _wlog.info("[mem]  RSS %.0f MB", _mb)


def _validate_verify_flags(verify: bool, strict: bool) -> None:
    """Reject ``--strict`` without ``--verify`` (strict refusal is meaningless otherwise).

    Chosen semantics (documented in --strict help text): ``--strict`` REQUIRES
    ``--verify``; it is rejected (not silently implied) so a user who believes they
    requested verification cannot be surprised.  ``--verify --strict`` escalates
    every recorded corruption / unresolved duplicate / missing-required-artifact /
    canary failure into a hard phase refusal.
    """
    if strict and not verify:
        _log.error(
            "--strict is only meaningful with --verify (strict refusal refuses on "
            "corruption/duplicates/missing artifacts found during verification); "
            "pass --verify --strict, or drop --strict."
        )
        raise SystemExit(2)


def _resolve_command(cmd: str) -> str:
    """Validate a CLI command string against the explicit phase/maintenance set.

    Returns the command unchanged when it is one of the eight phase names or a
    maintenance keyword (``cleanup`` / ``reset``).  Retired legacy aliases and
    unknown commands raise ``SystemExit(2)`` with an error naming the valid
    phases — they are never silently aliased to a phase.
    """
    if cmd in LEGACY_PHASE_ALIASES:
        _log.error(
            "%r is a retired/legacy phase name and is not a valid new-CLI phase. Valid phases: %s",
            cmd,
            ", ".join(CLI_PHASES),
        )
        raise SystemExit(2)
    if cmd not in CLI_PHASES and cmd not in ("cleanup", "reset"):
        _log.error(
            "unknown command %r. Valid phases: %s. Maintenance: cleanup, reset.",
            cmd,
            ", ".join(CLI_PHASES),
        )
        raise SystemExit(2)
    return cmd


def main() -> None:
    """Configure logging, parse CLI args, and execute one explicit phase or maintenance op."""
    _fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _log_dir = OUTPUT_ROOT
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = _log_dir / "post_pipeline_run.log"
    _log_file_handle = open(_log_path, "w", encoding="utf-8", buffering=1)
    _fh = logging.StreamHandler(_log_file_handle)
    _fh.setFormatter(_fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(_sh)
    root.addHandler(_fh)
    # Route mem-watcher logs to file only (they split tqdm progress bars)
    _mem_logger = logging.getLogger(__name__ + ".mem")
    _mem_logger.propagate = False
    _mem_logger.addHandler(_fh)
    # Suppress verbose DEBUG spam from third-party libraries
    for _noisy in ("PIL", "onnxruntime", "numba", "h5py", "numexpr", "nomarr.components.ml.onnx.ml_session_comp"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    ap = argparse.ArgumentParser(
        description="Embedding research CLI — exactly 8 phases + cleanup/reset maintenance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("command", nargs="?", default=None, help="phase or maintenance command (see below)")
    ap.add_argument("--install", action="store_true", help="Install pip requirements then exit")
    ap.add_argument("--force", action="store_true", help="Recompute/override existing rows for this phase")
    ap.add_argument("--device", default=None, help="ONNX device (cpu|cuda) for audio phases")
    ap.add_argument("--retained", action="store_true", help="Mark this run retained (protected from view/reset GC)")
    ap.add_argument("--verify", action="store_true", help="Verify artifacts/catalog while running (relevant phases)")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="With --verify: refuse the phase (nonzero exit) on corruption, unresolved "
        "duplicates, missing required artifacts, or a failed post-crash canary. "
        "--strict requires --verify.",
    )
    ap.add_argument("--scope", choices=("staging", "views", "dead", "archival", "analysis-run"), help="cleanup scope")
    ap.add_argument("--run-id", default=None, help="run_id (cleanup --scope analysis-run)")
    ap.add_argument("--confirm", action="store_true", help="Confirm destructive cleanup")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="cleanup: report without deleting")
    ap.add_argument("--binned-cache", action="store_true", help="reset also clears binned ptc/ctp caches")
    args = ap.parse_args()
    _validate_verify_flags(verify=bool(args.verify), strict=bool(args.strict))

    try:
        cmd = args.command
        if args.install:
            _install()
            return
        if cmd is None:
            ap.print_help()
            raise SystemExit(2)
        cmd = _resolve_command(cmd)

        # Startup duckdb version gate (1.5 <= v < 2.0) before ANY DB work.
        from scripts.embedding_research.db._schema import require_supported_duckdb as _require_supported_duckdb

        _require_supported_duckdb()

        if cmd == "cleanup":
            _cmd_cleanup(args)
            return
        if cmd == "reset":
            if args.binned_cache:
                _reset_db()
                _reset_cache_dirs(reset_optimizer=False, reset_binned=True)
            else:
                _reset_db()
            _log.info("reset complete")
            return

        cfg = _build_run_config(args)
        _log.info(
            "Config: phase=%s limit=%s force=%s device=%s backbones=%s heads=%s retained=%s",
            cmd,
            cfg.get("limit"),
            cfg.get("force"),
            cfg.get("device"),
            cfg.get("backbones"),
            cfg.get("heads"),
            cfg.get("retained"),
        )

        _watcher = _MemoryWatcher(interval=120.0)
        _watcher.start()
        try:
            with duckdb.connect(str(DB_PATH)) as con:
                from scripts.embedding_research import db as _db_mod

                _db_mod.ensure_schema(con)
                _run_single_phase(con, cmd, cfg, db_path=str(DB_PATH))
        finally:
            _watcher.stop()
            _log.info("Memory watcher stopped")
            _log_file_handle.close()
    except SystemExit:
        _log_file_handle.close()
        raise
    except Exception as exc:
        _log.exception("command %r failed: %s", args.command, exc)
        _log_file_handle.close()
        raise SystemExit(1) from exc


def _build_run_config(args) -> dict:
    """Build the per-phase config dict from research_config.toml + CLI overrides."""
    _toml = _load_research_config()
    _pipe = _toml.get("pipeline", {})
    _analysis = _toml.get("analysis", {})
    _binning = _toml.get("binning", {})
    _raw_limit = _pipe.get("limit", 0)
    device = args.device or ("cpu" if not _pipe.get("device") else _pipe["device"])
    cfg: dict = {
        "limit": int(_raw_limit) if _raw_limit else None,
        "force": bool(args.force or _pipe.get("force", False)),
        "device": "gpu" if str(device).lower() in ("cuda", "gpu") else "cpu",
        "backbones": _pipe.get("backbones") or None,  # None = all
        "heads": _pipe.get("heads") or None,  # None = all
        "k": int(_analysis.get("k", 10)),
        "workers": int(_analysis.get("workers", 4)),
        "blas_threads": int(_analysis.get("blas_threads", 1)) or None,
        # catalog input generation: [binning] grid + [pipeline] corpus budget.
        "catalog_bin_modes": list(_binning.get("bin_modes") or ["temporal_global"]),
        "catalog_thresholds": [float(t) for t in (_binning.get("dist_thresholds") or [0.7])],
        # derived phases read/write frozen artifacts under the configured output root.
        "output_root": OUTPUT_ROOT,
        "report_dir": OUTPUT_ROOT / "report",
        "retained": bool(args.retained),
        "verify": bool(args.verify),
        "strict": bool(args.strict),
        "run_id": None,
        "config_hash": hashlib.sha256(_load_raw_cfg()).hexdigest()[:16],
    }
    return cfg


def _cmd_cleanup(args) -> None:
    """Explicit maintenance: cleanup --scope <staging|views|dead|archival|analysis-run>.

    Wired to cleanup.py (P3-S2) scopes.  Analysis-run requires --run-id and --confirm;
    archival requires --confirm.  No default/global delete of Tier 1/2 rows.
    """
    from scripts.embedding_research import cleanup as _cleanup

    scope = args.scope
    if scope is None:
        _log.error("cleanup requires --scope {staging|views|dead|archival|analysis-run}")
        raise SystemExit(2)
    if scope == "staging":
        report = _cleanup.cleanup_staging(OUTPUT_ROOT, dry_run=args.dry_run)
    elif scope == "archival":
        if not args.confirm:
            _log.error("cleanup --scope archival is destructive; pass --confirm to proceed")
            raise SystemExit(2)
        report = _cleanup.cleanup_archival_caches(OUTPUT_ROOT, confirm=True, dry_run=args.dry_run)
    else:
        with duckdb.connect(str(DB_PATH)) as con:
            from scripts.embedding_research import db as _db_mod

            _db_mod.ensure_schema(con)
            if scope == "views":
                report = _cleanup.cleanup_views(con, OUTPUT_ROOT, dry_run=args.dry_run)
            elif scope == "dead":
                report = _cleanup.cleanup_dead_tables(con, dry_run=args.dry_run)
            elif scope == "analysis-run":
                if not args.run_id:
                    _log.error("cleanup --scope analysis-run requires --run-id")
                    raise SystemExit(2)
                if not args.confirm:
                    _log.error("cleanup --scope analysis-run is destructive; pass --confirm to proceed")
                    raise SystemExit(2)
                report = _cleanup.reset_analysis_run(con, args.run_id, override=True, dry_run=args.dry_run)
            else:  # pragma: no cover - guarded by argparse choices
                raise SystemExit(2)
    _log.info(
        "cleanup scope=%s dry_run=%s removed=%d skipped=%d refused=%d",
        scope,
        bool(args.dry_run),
        len(report.removed),
        len(report.skipped),
        len(report.refused),
    )


if __name__ == "__main__":
    main()
