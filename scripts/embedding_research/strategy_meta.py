"""Metadata ingest phase.

Reads audio tags for every discovered file once and persists them to the
``songs`` table.  Subsequent phases (embed, classify, analyze) can rely on
the DB being already populated — they never need to open audio files just
to read metadata.
"""

from __future__ import annotations

import logging as _logging

from tqdm import tqdm as _tqdm

from .config import (
    bootstrap_nomarr as _bootstrap_nomarr,
    discover_audio as _discover_audio,
    path_to_meta as _path_to_meta,
    song_id as _song_id,
)
from .db import (
    song_exists as _song_exists,
    upsert_song as _upsert_song,
)

__all__ = ["ingest"]

_log = _logging.getLogger(__name__)


def ingest(con, *, limit: int | None = None, force: bool = False) -> None:
    """Read tags for all audio files and persist to the songs table.

    Skips files that are already in the DB unless *force* is True.
    Artist / album / title fall back to path-derived values when tags are
    absent.  Genre falls back to ``"unknown"``.
    """
    _bootstrap_nomarr()

    audio_paths = _discover_audio(limit=limit)
    _log.info("Ingesting metadata for %d audio file(s) ...", len(audio_paths))

    new = skipped = errors = 0
    for path in _tqdm(audio_paths, desc="[ingest]", unit="song"):
        sid = _song_id(path)
        if not force and _song_exists(con, sid):
            skipped += 1
            continue
        try:
            meta = _path_to_meta(path)
            _upsert_song(
                con, sid,
                meta["path"], meta["artist"], meta["album"],
                meta["title"], meta.get("genre", "unknown"),
            )
            new += 1
        except Exception as exc:
            errors += 1
            _tqdm.write(f"  [ERROR] {path.name}: {exc}")

    _log.info("Ingest complete: new=%d  skipped=%d  errors=%d", new, skipped, errors)
