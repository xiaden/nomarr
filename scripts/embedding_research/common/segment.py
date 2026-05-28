"""Shared segment-phase skeleton for embedding research strategies."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, cast

import numpy as np
from tqdm import tqdm

from scripts.embedding_research import db as _db
from scripts.embedding_research.common.embed import _patches_path as patches_path
from scripts.embedding_research.config import BACKBONES as _BACKBONES

_log = logging.getLogger(__name__)

#: ``(patches, backbone, strategy_name) -> {strategy_name: pooled_vector}``
#: Callable type for per-song segment functions. ``patches`` is the ``[T, D]``
#: patch matrix, ``backbone`` names the encoder, ``strategy_name`` selects the
#: pooling/segmentation variant. Returns a dict mapping each produced strategy
#: name to its pooled ``[D]`` float32 vector.
SegmentFn = Callable[[np.ndarray, str, str], dict[str, np.ndarray]]
SkipCheckFn = Callable[[str, str, str], bool]
CacheWriteFn = Callable[[str, str, str, dict[str, np.ndarray]], None]


def _skip_never(song_id: str, backbone: str, strategy_name: str) -> bool:
    del song_id, backbone, strategy_name
    return False


def segment(
    con,
    segment_fn: SegmentFn,
    strategy_names: list[str],
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    extra_cfg: dict | None = None,
) -> None:
    """Run the shared segment loop for each in-scope song, backbone, and strategy."""
    cfg: dict[str, Any] = extra_cfg or {}
    skip_check_fn = cast("SkipCheckFn", cfg.get("skip_check_fn", _skip_never))
    cache_write_fn = cast("CacheWriteFn | None", cfg.get("cache_write_fn"))
    if cache_write_fn is None:
        raise ValueError("segment() requires extra_cfg['cache_write_fn']")

    _log.info("Loading song list from DB ...")
    t0_prep = time.perf_counter()
    all_songs = _db.load_all_songs(con)
    songs = [song for song in all_songs if str(song["song_id"]) in song_ids] if song_ids is not None else all_songs
    bb_names = list(backbones) if backbones is not None else list(_BACKBONES)
    _log.info(
        "  -> %d songs loaded for %d backbone(s) x %d strategy(s)  (%.1fs)",
        len(songs),
        len(bb_names),
        len(strategy_names),
        time.perf_counter() - t0_prep,
    )

    for backbone in bb_names:
        _log.info("[%s] ── backbone segment start ──", backbone)
        done = 0
        skipped = 0
        errors = 0
        started_at = time.perf_counter()
        progress = tqdm(songs, desc=f"[{backbone}] segment", unit="song")
        for song in progress:
            sid = str(song["song_id"])
            sidecar = patches_path(sid, backbone)
            if not sidecar.exists():
                skipped += len(strategy_names)
                _log.warning("[%s] Missing patches sidecar for %s: %s", backbone, sid, sidecar)
                progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)
                continue

            pending_strategy_names: list[str] = []
            for strategy_name in strategy_names:
                if not force and skip_check_fn(sid, backbone, strategy_name):
                    skipped += 1
                    continue
                pending_strategy_names.append(strategy_name)

            if not pending_strategy_names:
                progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)
                continue

            try:
                patches = np.load(str(sidecar), allow_pickle=False).astype(np.float32, copy=False)
            except Exception as exc:
                errors += len(pending_strategy_names)
                _log.error("%s %s: failed to load patches: %s", backbone, sid, exc)
                progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)
                continue

            for strategy_name in pending_strategy_names:
                try:
                    result = segment_fn(patches, backbone, strategy_name)
                    cache_write_fn(sid, backbone, strategy_name, result)
                    done += 1
                except Exception as exc:
                    errors += 1
                    _log.error("%s %s %s: %s", backbone, sid, strategy_name, exc)

            progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)

        elapsed = time.perf_counter() - started_at
        rate = done / elapsed if elapsed > 0 and done > 0 else 0.0
        _log.info(
            "[%s] done=%d skipped=%d errors=%d  %.0fs  (%.2f strategy-runs/s)",
            backbone,
            done,
            skipped,
            errors,
            elapsed,
            rate,
        )
