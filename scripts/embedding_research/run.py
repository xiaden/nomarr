"""
CLI entrypoint for the embedding research pipeline.

Running with no arguments executes all six phases in order:
  ingest -> embed -> segment -> classify -> analyze -> report

Each phase checks what is already in the DB and skips completed work.
All configuration lives in research_config.toml next to this file.

Usage:
  # First-time setup
  python run.py --install

  # Normal run (reads everything from research_config.toml)
  python run.py

  # Wipe the DB and start fresh (preserves .npy sidecars)
  python run.py --reset
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

# Ensure the workspace root is on sys.path so the package resolves correctly
# when run as `python run.py` inside the container.
_pkg_root = Path(__file__).resolve().parent.parent.parent  # /workspace
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research import common, db, pooling
from scripts.embedding_research.cache import binned_ctp, binned_ptc, flat_vecs
from scripts.embedding_research.common.analyze import AnalyzeCfg
from scripts.embedding_research.config import DB_PATH, HEAD_LABELS, HEADS, OUTPUT_ROOT, PATCHES_DIR
from scripts.embedding_research.helpers.binning import BIN_MODES
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config
from scripts.embedding_research.strategy_binned import _constants as _strategy_binned_constants
from scripts.embedding_research.strategy_ctp import segment_fn as _ctp_seg_fn
from scripts.embedding_research.strategy_global_pool import segment_fn as _gp_seg_fn
from scripts.embedding_research.strategy_ptc import segment_fn as _ptc_seg_fn
from scripts.embedding_research.vector_types import UnitTensor

_REQ = Path(__file__).parent / "requirements.txt"
_log = logging.getLogger(__name__)


GLOBAL_POOL_STRATEGY_NAMES = _gp_seg_fn.STRATEGY_NAMES
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
        for head_name in head_map:
            _head_parts.append(f"{bb_name}/{head_name} ({_head_mb}MB)")
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


def _decode_ctp_strategy_name(strategy_name: str) -> tuple[str, str, float]:
    prefix = "ctp_"
    if not strategy_name.startswith(prefix):
        raise ValueError(f"Unsupported CTP strategy name: {strategy_name}")

    encoded = strategy_name[len(prefix) :]
    encoded_head_mode, std_thresh_text = encoded.rsplit("_", 1)
    for bin_mode in sorted(BIN_MODES, key=len, reverse=True):
        suffix = f"_{bin_mode}"
        if encoded_head_mode.endswith(suffix):
            head_name = encoded_head_mode[: -len(suffix)]
            if head_name:
                return head_name, bin_mode, float(std_thresh_text)

    raise ValueError(f"Unknown CTP bin mode in strategy name: {strategy_name}")


def _global_pool_strategy_key(backbone: str, strategy_name: str, _extra: dict[str, Any]) -> str:
    return f"global_pool:{backbone}:{strategy_name}"


def _ptc_strategy_key(backbone: str, strategy_name: str, extra: dict[str, Any]) -> str:
    bin_mode = str(extra.get("bin_mode") or _decode_ptc_strategy_name(strategy_name)[0])
    std_thresh = float(extra.get("std_thresh", _decode_ptc_strategy_name(strategy_name)[1]))
    return f"ptc:{backbone}:{bin_mode}:{std_thresh:.2f}:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"


def _ctp_strategy_key(backbone: str, strategy_name: str, extra: dict[str, Any]) -> str:
    head_name, bin_mode, std_thresh = _decode_ctp_strategy_name(strategy_name)
    return (
        f"ctp:{backbone}:{extra.get('head', head_name)}:{extra.get('bin_mode', bin_mode)}:"
        f"{float(extra.get('std_thresh', std_thresh)):.2f}:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"
    )


def _load_global_pool_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    _extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    return flat_vecs.load_matrix(backbone, strategy_name, con)


def _load_ptc_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    bin_mode, std_thresh = _decode_ptc_strategy_name(strategy_name)
    rep_types = [str(rep) for rep in extra_cfg.get("rep_types", _strategy_binned_constants.REP_TYPES)]

    sids: list[str] = []
    bin_counts: list[int] = []
    for sid in binned_ptc.list_sids(backbone, bin_mode, std_thresh):
        stats_bins = binned_ptc.load_bin_stats(backbone, bin_mode, std_thresh, sid)
        if not stats_bins:
            continue
        sids.append(sid)
        bin_counts.append(len(stats_bins))

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
                }
            )

    return {"pairs": pairs}, sids, artists, albums, genres


def _load_ctp_analyze_vecs(
    backbone: str,
    strategy_name: str,
    con: Any,
    extra_cfg: dict[str, Any],
) -> tuple[Any, list[str], list[str], list[str], list[str]]:
    head_name, bin_mode, std_thresh = _decode_ctp_strategy_name(strategy_name)
    rep_types = [str(rep) for rep in extra_cfg.get("rep_types", _strategy_binned_constants.REP_TYPES)]
    ctp_sids, _ctp_artists, song_data = binned_ctp.load_all_reps(con, backbone, head_name, bin_mode, std_thresh)

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
PTC_ANALYZE_CFG: AnalyzeCfg = {
    "strategy_names": [f"ptc_{bin_mode}_{std_thresh:.2f}" for bin_mode in BIN_MODES for std_thresh in STD_THRESHOLDS],
    "load_vecs_fn": _load_ptc_analyze_vecs,
    "db_write_fn": db.write_analyze_metrics,
    "strategy_key_fn": _ptc_strategy_key,
    "strategy_type": "ptc",
    "extra_cfg": {"rep_types": list(_strategy_binned_constants.REP_TYPES)},
}

# Wires the centroid-to-patch (CTP) binned strategy (head-guided bins) into the shared analyze phase.
CTP_ANALYZE_CFG: AnalyzeCfg = {
    "strategy_names": [
        f"ctp_{head_name}_{bin_mode}_{std_thresh:.2f}"
        for head_name in _KNOWN_CTP_HEAD_NAMES
        for bin_mode in BIN_MODES
        for std_thresh in STD_THRESHOLDS
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


def _reset_cache_dirs(*, reset_optimizer: bool, reset_binned: bool, reset_sim: bool) -> None:
    dirs: list[Path] = []
    if reset_optimizer:
        dirs.append(OUTPUT_ROOT / "optimizer")
    if reset_binned:
        dirs.extend([OUTPUT_ROOT / "cache" / "binned_ptc", OUTPUT_ROOT / "cache" / "binned_ctp"])
    if reset_sim:
        dirs.append(OUTPUT_ROOT / "sim_cache")

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


def _segment_phase(con, cfg: dict) -> None:
    _kw = {"song_ids": cfg["song_ids"], "force": cfg["force"], "backbones": cfg["backbones"]}
    common.segment.segment(
        con,
        _gp_seg_fn.segment_fn,
        GLOBAL_POOL_STRATEGY_NAMES,
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
            extra_cfg={"skip_check_fn": _ctp_seg_fn.SKIP_CHECK_FN, "cache_write_fn": _ctp_seg_fn.CACHE_WRITE_FN},
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
        thresholds_by_backbone_mode=cfg.get("thresholds_by_backbone_mode"),
        head_sessions=_head_sessions,
    )
    _log.info("  <- sub-phase: binned classify done (%.0fs)", time.perf_counter() - _t0)


def _analyze_phase(con, cfg: dict) -> None:
    con.execute("DELETE FROM analyze_metrics")
    _kw = {"song_ids": cfg["song_ids"], "force": cfg["force"], "backbones": cfg["backbones"], "k": cfg["k"]}
    common.analyze.analyze(con, GLOBAL_POOL_ANALYZE_CFG, **_kw)
    common.analyze.analyze(con, PTC_ANALYZE_CFG, **_kw)
    common.analyze.analyze(con, CTP_ANALYZE_CFG, **_kw)


def _report_phase(con, cfg: dict) -> None:
    from scripts.embedding_research.config import REPORT_DIR
    from scripts.embedding_research.report import run

    run(con, REPORT_DIR)


_PHASES: dict[str, Callable[..., None]] = {
    "ingest": _ingest_phase,
    "embed": _embed_phase,
    "segment": _segment_phase,
    "classify": _classify_phase,
    "analyze": _analyze_phase,
    "report": _report_phase,
}


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


def main() -> None:
    """Configure logging, parse CLI args, and execute the embedding research pipeline."""
    _fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _log_dir = Path(__file__).parent.parent / "outputs" / "embedding_research"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = _log_dir / "post_pipeline_run.log"
    _log_file = open(_log_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    _fh = logging.StreamHandler(_log_file)
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
    for _noisy in ("PIL", "onnxruntime", "numba", "h5py", "numexpr",
                   "nomarr.components.ml.onnx.ml_session_comp"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(
        description="Embedding research pipeline — configure via research_config.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--install", action="store_true", help="Install pip requirements then exit")
    ap.add_argument("--reset", action="store_true", help="Drop the DB and exit (preserves .npy sidecars)")
    ap.add_argument("--reset-binned-cache", action="store_true", help="Delete binned ptc/ctp caches")
    ap.add_argument("--reset-sim-cache", action="store_true", help="Delete similarity matrix cache")
    ap.add_argument("--fresh", action="store_true", help="Reset DB plus binned and sim caches")
    args = ap.parse_args()

    if args.install:
        _install()
        return

    if args.fresh:
        _reset_db()
        _reset_cache_dirs(reset_optimizer=False, reset_binned=True, reset_sim=True)
        return

    if args.reset:
        _reset_db()
        return

    if args.reset_binned_cache or args.reset_sim_cache:
        _reset_cache_dirs(
            reset_optimizer=False,
            reset_binned=args.reset_binned_cache,
            reset_sim=args.reset_sim_cache,
        )
        return

    # Build config from TOML
    _toml = _load_research_config()
    _pipe = _toml.get("pipeline", {})
    _analysis = _toml.get("analysis", {})
    _raw_limit = _pipe.get("limit", 0)
    _pooling = _toml.get("pooling", {})
    cfg: dict = {
        "limit": int(_raw_limit) if _raw_limit else None,
        "force": bool(_pipe.get("force", False)),
        "device": "gpu" if str(_pipe.get("device", "cpu")).lower() in ("cuda", "gpu") else "cpu",
        "backbones": _pipe.get("backbones") or None,  # None = all
        "heads": _pipe.get("heads") or None,  # None = all
        "flat_strategies": _pooling.get("rep_types") or None,  # None = all cached strategies
        "k": int(_analysis.get("k", 10)),
        "workers": int(_analysis.get("workers", 4)),
        "blas_threads": int(_analysis.get("blas_threads", 1)) or None,
        "song_ids": None,  # populated below after discover_audio
    }
    _log.info(
        "Config: limit=%s  force=%s  device=%s  backbones=%s  heads=%s",
        cfg["limit"],
        cfg["force"],
        cfg["device"],
        cfg["backbones"],
        cfg["heads"],
    )

    _watcher = _MemoryWatcher(interval=120.0)
    _watcher.start()
    try:
        with duckdb.connect(str(DB_PATH)) as con:
            from scripts.embedding_research import db as _db_mod

            _db_mod.ensure_schema(con)
            from scripts.embedding_research.config import discover_audio as _discover_audio_fn
            from scripts.embedding_research.config import song_id as _song_id_fn

            cfg["song_ids"] = frozenset(_song_id_fn(p) for p in _discover_audio_fn(limit=cfg["limit"]))
            _log.info(
                "Working set: %d songs selected (limit=%s)",
                len(cfg["song_ids"]),
                cfg["limit"],
            )

            # Build the global model cache once before any phase runs.
            from scripts.embedding_research.config import bootstrap_nomarr as _boot

            _boot()
            cfg["cache"] = _build_model_cache(cfg["device"])

            run_ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            for phase, phase_fn in _PHASES.items():
                _log.info("─── Phase: %s ───────────────────────────────────────────────", phase)
                t0 = time.perf_counter()
                phase_fn(con, cfg)
                elapsed = time.perf_counter() - t0
                _log.info("─── Phase %s complete  (%.0fs / %.1fmin) ─────────────────", phase, elapsed, elapsed / 60)
                _db_mod.upsert_phase_timing(con, run_ts, phase, elapsed)

                # Dispose backbone sessions after embed — they are never needed again.
                if phase == "embed" and cfg.get("cache"):
                    cfg["cache"].backbone_sessions.clear()
                    _log.info("[cache] Backbone sessions released")
                # Dispose the full cache after classify — head sessions are no longer needed.
                if phase == "classify" and cfg.get("cache"):
                    cfg["cache"].head_sessions.clear()
                    cfg.pop("cache")
                    _log.info("[cache] Head sessions released")
    finally:
        _watcher.stop()
        _log.info("Memory watcher stopped")


if __name__ == "__main__":
    main()
