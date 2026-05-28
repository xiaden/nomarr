"""Global-pool embed: delegate inference to common embed, then pool sidecars."""

from __future__ import annotations

import logging as _logging
import time as _time

import numpy as _np
from tqdm import tqdm as _tqdm

from scripts.embedding_research.cache.flat_vecs import list_configs as _list_embedded_configs
from scripts.embedding_research.cache.flat_vecs import save_pooled as _save_pooled
from scripts.embedding_research.common.embed import embed as _common_embed
from scripts.embedding_research.config import BACKBONES as _BACKBONES
from scripts.embedding_research.config import discover_audio as _discover_audio
from scripts.embedding_research.config import patches_path as _patches_path
from scripts.embedding_research.config import song_id as _song_id
from scripts.embedding_research.pooling import STRATEGIES as _STRATEGIES

_log = _logging.getLogger(__name__)


def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
) -> None:
    """Run shared inference, then global-pool any missing strategy vectors from sidecars."""
    _common_embed(
        con,
        song_ids=song_ids,
        force=force,
        backbones=backbones,
        device=device,
    )

    embedded_configs = _list_embedded_configs()
    _all_paths = _discover_audio()
    audio_paths = [p for p in _all_paths if _song_id(p) in song_ids] if song_ids is not None else _all_paths
    bb_names = backbones or list(_BACKBONES)

    _log.info("Pooling %d songs x %d backbone(s) ...", len(audio_paths), len(bb_names))

    for bb_name in bb_names:
        done = skipped = errors = 0
        t0 = _time.perf_counter()
        pbar = _tqdm(audio_paths, desc=f"[{bb_name}]", unit="song")
        for path in pbar:
            sid = _song_id(path)
            sidecar = _patches_path(sid, bb_name)
            if not sidecar.exists():
                skipped += 1
                _log.warning("[%s] missing sidecar for %s; skipping pooling", bb_name, path.name)
                pbar.set_postfix(done=done, skip=skipped, err=errors)
                continue

            try:
                embeddings = _np.load(str(sidecar))
                worked = False
                for strategy_name, pool_fn in _STRATEGIES.items():
                    if force or (bb_name, strategy_name) not in embedded_configs:
                        pooled = pool_fn(embeddings).astype(_np.float32)
                        _save_pooled(sid, bb_name, strategy_name, pooled)
                        worked = True
                if worked:
                    done += 1
                else:
                    skipped += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
            except Exception as exc:
                errors += 1
                _log.error("%s %s: %s", bb_name, path.name, exc)

        elapsed = _time.perf_counter() - t0
        rate = done / elapsed if elapsed > 0 and done > 0 else 0
        _log.info(
            "[%s] done=%d skipped=%d errors=%d  %.0fs  (%.2f songs/s)",
            bb_name,
            done,
            skipped,
            errors,
            elapsed,
            rate,
        )
