"""Songs table operations and song-level read helpers."""

from __future__ import annotations

import numpy as np


# ── songs ─────────────────────────────────────────────────────────────────────


def upsert_song(con, song_id: str, path: str, artist: str, album: str, title: str, genre: str = "unknown") -> None:
    con.execute(
        """
        INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?,?,?,?,?,?)
        ON CONFLICT (song_id) DO NOTHING
        """,
        [song_id, path, artist, album, title, genre],
    )


def song_exists(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM songs WHERE song_id=?", [song_id]).fetchone() is not None


def load_all_songs(con) -> list[dict]:
    rows = con.execute("SELECT song_id, path, artist, album, title FROM songs").fetchall()
    return [dict(zip(("song_id", "path", "artist", "album", "title"), r, strict=False)) for r in rows]


def load_song_albums(con, sids: list[str]) -> list[str]:
    """Return one album label per song_id (preserves input order). Used for disc_album."""
    if not sids:
        return []
    placeholders = ",".join(["?"] * len(sids))
    rows = con.execute(
        f"SELECT song_id, album FROM songs WHERE song_id IN ({placeholders})",
        sids,
    ).fetchall()
    by_id = {sid: (alb or "unknown") for sid, alb in rows}
    return [by_id.get(s, "unknown") for s in sids]


def load_song_genres(con, sids: list[str]) -> list[str]:
    """Return one genre tag per song_id (preserves input order). Used for disc_genre."""
    if not sids:
        return []
    placeholders = ",".join(["?"] * len(sids))
    rows = con.execute(
        f"SELECT song_id, genre FROM songs WHERE song_id IN ({placeholders})",
        sids,
    ).fetchall()
    by_id = {sid: (g or "unknown") for sid, g in rows}
    return [by_id.get(s, "unknown") for s in sids]


def load_song_head_scores(
    con,
    backbone: str,
    sids: list[str],
    strategy: str = "median",
    pathway: str = "ptc",
) -> tuple[np.ndarray, list[str]] | tuple[None, list[str]]:
    """
    Build a per-song head-score matrix [n_songs, n_heads] from `head_results`.
    Uses act[1] (positive class probability) as the scalar score per head.

    Args:
        strategy: Pooling strategy to filter on (default 'median').
        pathway:  Head pathway to filter on, 'ptc' or 'ctp' (default 'ptc').

    Returns (matrix, head_names). matrix is None when no rows are available.
    Rows missing for a (song, head) become 0.5 (neutral).
    """
    if not sids:
        return None, []
    placeholders = ",".join(["?"] * len(sids))
    params: list[object] = [backbone, pathway, strategy, *sids]
    rows = con.execute(
        f"""
        SELECT song_id, head, act
        FROM head_results
        WHERE backbone=? AND pathway=? AND strategy=?
              AND song_id IN ({placeholders})
        """,
        params,
    ).fetchall()
    if not rows:
        return None, []
    from collections import defaultdict

    per_song: dict[str, dict[str, float]] = defaultdict(dict)
    head_set: set[str] = set()
    for sid, head, act in rows:
        head_set.add(head)
        try:
            v = float(act[1]) if act is not None and len(act) >= 2 else float(act[0])
        except (TypeError, IndexError, ValueError):
            v = 0.5
        per_song[sid][head] = v
    head_names = sorted(head_set)
    if not head_names:
        return None, []
    n = len(sids)
    m = np.full((n, len(head_names)), 0.5, dtype=np.float32)
    for i, sid in enumerate(sids):
        h_map = per_song.get(sid, {})
        for j, h in enumerate(head_names):
            if h in h_map:
                m[i, j] = h_map[h]
    return m, head_names
