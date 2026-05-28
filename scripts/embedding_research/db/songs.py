"""Songs table operations and song-level read helpers."""

from __future__ import annotations

import numpy as np

# ── songs ─────────────────────────────────────────────────────────────────────


def upsert_song(con, song_id: str, path: str, artist: str, album: str, title: str, genre: str = "unknown") -> None:
    con.execute(
        """
        INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?,?,?,?,?,?)
        ON CONFLICT (song_id) DO UPDATE SET
            path   = EXCLUDED.path,
            artist = EXCLUDED.artist,
            album  = EXCLUDED.album,
            title  = EXCLUDED.title,
            genre  = EXCLUDED.genre
        """,
        [song_id, path, artist, album, title, genre],
    )


def song_exists(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM songs WHERE song_id=?", [song_id]).fetchone() is not None


def load_all_songs(con) -> list[dict]:
    rows = con.execute("SELECT song_id, path, artist, album, title, genre FROM songs").fetchall()
    return [dict(zip(("song_id", "path", "artist", "album", "title", "genre"), r, strict=False)) for r in rows]


def load_sids_and_artists(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
) -> tuple[list[str], list[str]]:
    """Return (song_ids, artists) for all songs in the filesystem cache for the given config.

    Uses the filesystem cache as the source of truth (not binned_song_stats, which is a
    derived output written by the analyze loop itself).
    """
    from scripts.embedding_research.cache.binned_ptc import list_sids as _list_cache_sids

    cache_sids = _list_cache_sids(backbone, bin_mode, std_thresh)
    if not cache_sids:
        return [], []
    placeholders = ",".join(["?"] * len(cache_sids))
    rows = con.execute(
        f"SELECT song_id, artist FROM songs WHERE song_id IN ({placeholders}) ORDER BY song_id",
        cache_sids,
    ).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    sids = [s for s in cache_sids if s in by_id]
    artists = [by_id[s] for s in sids]
    return sids, artists


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
    backbone: str,
    sids: list[str],
    strategy: str = "median",
    pathway: str = "ptc",
) -> tuple[np.ndarray, list[str]] | tuple[None, list[str]]:
    """Build a per-song head-score matrix [n_songs, n_heads] from the filesystem cache.

    Uses act[1] (positive class probability) as the scalar score per head.

    Args:
        strategy: Pooling strategy to filter on (default 'median').
        pathway:  Head pathway to filter on, 'ptc' or 'ctp' (default 'ptc').

    Returns (matrix, head_names). matrix is None when no rows are available.
    Rows missing for a (song, head) become 0.5 (neutral).
    """
    from scripts.embedding_research.cache import flat_heads as _fh

    if not sids:
        return None, []

    head_names = _fh.list_all_heads(backbone)
    if not head_names:
        return None, []

    n = len(sids)
    m = np.full((n, len(head_names)), 0.5, dtype=np.float32)
    any_found = False
    for j, head in enumerate(head_names):
        act_map = _fh.load_bulk(backbone, head, strategy, pathway, sids)
        for i, sid in enumerate(sids):
            act = act_map.get(sid)
            if act is not None and len(act) >= 2:
                m[i, j] = float(act[1])
                any_found = True
            elif act is not None and len(act) == 1:
                m[i, j] = float(act[0])
                any_found = True

    if not any_found:
        return None, []
    return m, head_names
