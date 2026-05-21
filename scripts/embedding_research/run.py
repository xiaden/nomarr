"""
CLI entrypoint for the embedding research pipeline.

Running with no arguments executes all five phases in order:
  ingest -> embed -> classify -> analyze -> report

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
import datetime
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import duckdb

# Ensure the workspace root is on sys.path so the package resolves correctly
# when run as `python run.py` inside the container.
_pkg_root = Path(__file__).resolve().parent.parent.parent  # /workspace
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research.config import DB_PATH, PATCHES_DIR
from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config

_REQ = Path(__file__).parent / "requirements.txt"
_log = logging.getLogger(__name__)


def _install() -> None:
    _log.debug("Installing dependencies from %s ...", _REQ)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(_REQ)])
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
        "Reset complete.  Run 'embed classify analyze report' (without --force) to"
        " rebuild from the preserved .npy sidecars, or add 'embed --force' to also"
        " regenerate the sidecars from audio."
    )


def _ingest(con, cfg: dict) -> None:
    from scripts.embedding_research.strategy_meta import ingest

    ingest(con, limit=cfg["limit"], force=cfg["force"])


def _embed(con, cfg: dict) -> None:
    from scripts.embedding_research.strategy_binned import embed as _strat_binned_embed
    from scripts.embedding_research.strategy_flat import embed as flat_embed

    _log.info("  -> sub-phase: flat embed")
    _t0 = time.perf_counter()
    flat_embed(con, song_ids=cfg["song_ids"], force=cfg["force"], backbones=cfg["backbones"], device=cfg["device"])
    _log.info("  <- sub-phase: flat embed done (%.0fs)", time.perf_counter() - _t0)

    _log.info("  -> sub-phase: binned embed")
    _t0 = time.perf_counter()
    _strat_binned_embed(con, song_ids=cfg["song_ids"], force=cfg["force"], backbones=cfg["backbones"], device=cfg["device"])
    _log.info("  <- sub-phase: binned embed done (%.0fs)", time.perf_counter() - _t0)


def _classify(con, cfg: dict) -> None:
    from scripts.embedding_research.classify import run_binned, run_flat

    _log.info("  -> sub-phase: flat classify")
    _t0 = time.perf_counter()
    run_flat(con, song_ids=cfg["song_ids"], force=cfg["force"], backbones=cfg["backbones"], heads=cfg["heads"], device=cfg["device"])
    _log.info("  <- sub-phase: flat classify done (%.0fs)", time.perf_counter() - _t0)

    _log.info("  -> sub-phase: binned classify")
    _t0 = time.perf_counter()
    run_binned(con, song_ids=cfg["song_ids"], force=cfg["force"], backbones=cfg["backbones"], heads=cfg["heads"], device=cfg["device"])
    _log.info("  <- sub-phase: binned classify done (%.0fs)", time.perf_counter() - _t0)


def _analyze(con, cfg: dict) -> None:
    from scripts.embedding_research.strategy_binned import analyze as _strat_binned_analyze
    from scripts.embedding_research.strategy_binned import analyze_ctp as _strat_ctp_analyze
    from scripts.embedding_research.strategy_flat import analyze as flat_analyze

    _log.info("  -> sub-phase: flat analyze")
    _t0 = time.perf_counter()
    flat_analyze(con, k=cfg["k"], backbones=cfg["backbones"], song_ids=cfg["song_ids"])
    _log.info("  <- sub-phase: flat analyze done (%.0fs)", time.perf_counter() - _t0)

    _log.info("  -> sub-phase: binned analyze")
    _t0 = time.perf_counter()
    _strat_binned_analyze(con, k=cfg["k"], backbones=cfg["backbones"], workers=cfg["workers"], blas_threads=cfg["blas_threads"], song_ids=cfg["song_ids"])
    _log.info("  <- sub-phase: binned analyze done (%.0fs)", time.perf_counter() - _t0)

    _log.info("  -> sub-phase: CTP analyze")
    _t0 = time.perf_counter()
    _strat_ctp_analyze(con, k=cfg["k"], backbones=cfg["backbones"], workers=cfg["workers"], blas_threads=cfg["blas_threads"], song_ids=cfg["song_ids"])
    _log.info("  <- sub-phase: CTP analyze done (%.0fs)", time.perf_counter() - _t0)


def _report(con, cfg: dict) -> None:
    from scripts.embedding_research.report import run

    run(con)


_PHASES: dict[str, Callable[..., None]] = {
    "ingest":   _ingest,
    "embed":    _embed,
    "classify": _classify,
    "analyze":  _analyze,
    "report":   _report,
}


class _MemoryWatcher:
    """Background daemon thread that logs process RSS memory every *interval* seconds."""

    def __init__(self, interval: float = 5.0) -> None:
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


import re as _re

_ANSI_ESCAPE_RE = _re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class _Tee:
    """Write to both the original stream and a log file.

    The stream receives verbatim bytes (full ANSI control codes so tqdm renders
    correctly in a live terminal).  The file receives the same content with all
    ANSI escape sequences stripped, leaving just plain text and ``\\r`` so that
    ``tail -f`` shows readable progress bar updates.
    """

    def __init__(self, stream, file_obj) -> None:
        self._stream = stream
        self._file = file_obj

    def write(self, data: str) -> int:
        self._stream.write(data)
        self._file.write(_ANSI_ESCAPE_RE.sub("", data))
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def main() -> None:
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
    # Suppress verbose DEBUG spam from third-party libraries
    for _noisy in ("matplotlib", "PIL", "onnxruntime", "numba", "h5py", "numexpr"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    # Tee stdout and stderr so tqdm bars and raw prints also land in the log
    sys.stdout = _Tee(sys.stdout, _log_file)
    sys.stderr = _Tee(sys.stderr, _log_file)

    ap = argparse.ArgumentParser(
        description="Embedding research pipeline — configure via research_config.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--install", action="store_true", help="Install pip requirements then exit")
    ap.add_argument("--reset", action="store_true", help="Drop the DB and exit (preserves .npy sidecars)")
    args = ap.parse_args()

    if args.install:
        _install()
        return

    if args.reset:
        _reset_db()
        return

    # Build config from TOML
    _toml = _load_research_config()
    _pipe = _toml.get("pipeline", {})
    _analysis = _toml.get("analysis", {})
    _raw_limit = _pipe.get("limit", 0)
    cfg: dict = {
        "limit":        int(_raw_limit) if _raw_limit else None,
        "force":        bool(_pipe.get("force", False)),
        "device":       "gpu" if str(_pipe.get("device", "cpu")).lower() in ("cuda", "gpu") else "cpu",
        "backbones":    _pipe.get("backbones") or None,  # None = all
        "heads":        _pipe.get("heads") or None,      # None = all
        "k":            int(_analysis.get("k", 10)),
        "workers":      int(_analysis.get("workers", 4)),
        "blas_threads": int(_analysis.get("blas_threads", 1)) or None,
        "song_ids":     None,  # populated below after discover_audio
    }
    _log.info("Config: limit=%s  force=%s  device=%s  backbones=%s  heads=%s",
              cfg["limit"], cfg["force"], cfg["device"], cfg["backbones"], cfg["heads"])

    _watcher = _MemoryWatcher(interval=5.0)
    _watcher.start()
    _log.info("Memory watcher started (5s interval)")
    try:
        with duckdb.connect(str(DB_PATH)) as con:
            from scripts.embedding_research import db as _db_mod

            _db_mod.ensure_schema(con)
            from scripts.embedding_research.config import discover_audio as _discover_audio_fn
            from scripts.embedding_research.config import song_id as _song_id_fn
            cfg["song_ids"] = frozenset(
                _song_id_fn(p) for p in _discover_audio_fn(limit=cfg["limit"])
            )
            _log.info(
                "Working set: %d songs selected (limit=%s)",
                len(cfg["song_ids"]), cfg["limit"],
            )
            run_ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            for phase, phase_fn in _PHASES.items():
                _log.info("─── Phase: %s ───────────────────────────────────────────────", phase)
                t0 = time.perf_counter()
                phase_fn(con, cfg)
                elapsed = time.perf_counter() - t0
                _log.info("─── Phase %s complete  (%.0fs / %.1fmin) ─────────────────", phase, elapsed, elapsed / 60)
                _db_mod.upsert_phase_timing(con, run_ts, phase, elapsed)
    finally:
        _watcher.stop()
        _log.info("Memory watcher stopped")


if __name__ == "__main__":
    main()
