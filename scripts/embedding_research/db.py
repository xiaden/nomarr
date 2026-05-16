"""
DuckDB storage layer for the embedding research package.

Schema
------
songs          (song_id PK, path, artist, album, title)
pooled_vecs    (song_id, backbone, strategy, vec FLOAT[])
head_results   (song_id, backbone, head, strategy, pathway, act FLOAT[])
retrieval_rows (backbone, strategy, sim_metric, map_k, mrr, ndcg_k,
                recall_k, disc_score, mean_within, mean_cross)
ann_rows       (backbone, strategy, ef_search, recall_k, backend)
ptc_ctp_rows   (backbone, head, strategy, ptc_disc, ctp_disc, delta_disc,
                ptc_map, ctp_map, delta_map)

Patches are NOT stored in the DB \u2014 they are kept as .npy sidecars because
they are large and rarely needed for aggregated analysis.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import numpy as np

# Lazy import so the module can be imported without duckdb installed
# (the caller gets an ImportError only when they call connect()).
try:
    import duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False

from .config import DB_PATH

_DDL = """
CREATE TABLE IF NOT EXISTS songs (
    song_id TEXT PRIMARY KEY,
    path    TEXT NOT NULL,
    artist  TEXT,
    album   TEXT,
    title   TEXT
);

CREATE TABLE IF NOT EXISTS pooled_vecs (
    song_id  TEXT NOT NULL,
    backbone TEXT NOT NULL,
    strategy TEXT NOT NULL,
    vec      FLOAT[] NOT NULL,
    PRIMARY KEY (song_id, backbone, strategy)
);

CREATE TABLE IF NOT EXISTS head_results (
    song_id  TEXT NOT NULL,
    backbone TEXT NOT NULL,
    head     TEXT NOT NULL,
    strategy TEXT NOT NULL,
    pathway  TEXT NOT NULL,   -- 'ptc' or 'ctp'
    act      FLOAT[] NOT NULL, -- softmax probabilities [p0, p1]
    PRIMARY KEY (song_id, backbone, head, strategy, pathway)
);

CREATE TABLE IF NOT EXISTS retrieval_rows (
    backbone    TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sim_metric  TEXT NOT NULL,
    k           INTEGER NOT NULL,
    map_k       DOUBLE,
    mrr         DOUBLE,
    ndcg_k      DOUBLE,
    recall_k    DOUBLE,
    disc_score  DOUBLE,
    mean_within DOUBLE,
    mean_cross  DOUBLE,
    PRIMARY KEY (backbone, strategy, sim_metric, k)
);

CREATE TABLE IF NOT EXISTS ann_rows (
    backbone   TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    ef_search  INTEGER NOT NULL,
    recall_k   DOUBLE,
    backend    TEXT,
    PRIMARY KEY (backbone, strategy, ef_search)
);

CREATE TABLE IF NOT EXISTS ptc_ctp_rows (
    backbone   TEXT NOT NULL,
    head       TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    ptc_disc   DOUBLE,
    ctp_disc   DOUBLE,
    delta_disc DOUBLE,
    ptc_map    DOUBLE,
    ctp_map    DOUBLE,
    delta_map  DOUBLE,
    PRIMARY KEY (backbone, head, strategy)
);
"""


def _require_duckdb() -> None:
    if not _HAS_DUCKDB:
        raise ImportError(
            "duckdb is not installed. Run:\n  pip install -r /workspace/scripts/embedding_research/requirements.txt"
        )


@contextmanager
def connect() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open a connection to the research database (creates it if new)."""
    _require_duckdb()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(_DDL)
    try:
        yield con
    finally:
        con.close()


# ── songs ─────────────────────────────────────────────────────────────────────


def upsert_song(con, song_id: str, path: str, artist: str, album: str, title: str) -> None:
    con.execute(
        """
        INSERT INTO songs (song_id, path, artist, album, title) VALUES (?,?,?,?,?)
        ON CONFLICT (song_id) DO NOTHING
        """,
        [song_id, path, artist, album, title],
    )


def song_exists(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM songs WHERE song_id=?", [song_id]).fetchone() is not None


def load_all_songs(con) -> list[dict]:
    rows = con.execute("SELECT song_id, path, artist, album, title FROM songs").fetchall()
    return [dict(zip(("song_id", "path", "artist", "album", "title"), r, strict=False)) for r in rows]


# ── pooled_vecs ───────────────────────────────────────────────────────────────


def upsert_pooled(con, song_id: str, backbone: str, strategy: str, vec: np.ndarray) -> None:
    con.execute(
        """
        INSERT INTO pooled_vecs (song_id, backbone, strategy, vec) VALUES (?,?,?,?)
        ON CONFLICT (song_id, backbone, strategy) DO UPDATE SET vec=excluded.vec
        """,
        [song_id, backbone, strategy, vec.astype(np.float32).tolist()],
    )


def pooled_exists(con, song_id: str, backbone: str, strategy: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM pooled_vecs WHERE song_id=? AND backbone=? AND strategy=?",
            [song_id, backbone, strategy],
        ).fetchone()
        is not None
    )


def load_pooled_matrix(
    con,
    backbone: str,
    strategy: str,
) -> tuple[np.ndarray, list[str], list[str]]:
    """
    Load all pooled vectors for (backbone, strategy).

    Returns:
      vecs    [n, d] float32
      sids    [n] song_id strings
      artists [n] artist label strings
    """
    rows = con.execute(
        """
        SELECT p.song_id, p.vec, s.artist
        FROM pooled_vecs p
        JOIN songs s USING (song_id)
        WHERE p.backbone=? AND p.strategy=?
        ORDER BY p.song_id
        """,
        [backbone, strategy],
    ).fetchall()

    if not rows:
        return np.empty((0, 0), dtype=np.float32), [], []

    sids = [r[0] for r in rows]
    vecs = np.array([r[1] for r in rows], dtype=np.float32)
    artists = [r[2] or "unknown" for r in rows]
    return vecs, sids, artists


# ── head_results ──────────────────────────────────────────────────────────────


def upsert_head(
    con,
    song_id: str,
    backbone: str,
    head: str,
    strategy: str,
    pathway: str,
    act: list[float],
) -> None:
    con.execute(
        """
        INSERT INTO head_results (song_id, backbone, head, strategy, pathway, act)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT (song_id, backbone, head, strategy, pathway)
        DO UPDATE SET act=excluded.act
        """,
        [song_id, backbone, head, strategy, pathway, act],
    )


def head_strategy_done(con, song_id: str, backbone: str, head: str, strategy: str) -> bool:
    n = con.execute(
        """
        SELECT COUNT(*) FROM head_results
        WHERE song_id=? AND backbone=? AND head=? AND strategy=?
        """,
        [song_id, backbone, head, strategy],
    ).fetchone()[0]
    return n >= 2  # both ptc and ctp


def load_head_labels(
    con,
    sids: list[str],
    backbone: str,
    head: str,
    strategy: str,
    pathway: str,
    label_names: list[str],
) -> list[str] | None:
    """
    Return per-song majority-class label for (head, strategy, pathway).
    Returns None if >20% of songs are missing.
    """
    rows = con.execute(
        """
        SELECT song_id, act FROM head_results
        WHERE backbone=? AND head=? AND strategy=? AND pathway=?
        """,
        [backbone, head, strategy, pathway],
    ).fetchall()
    act_map = {r[0]: r[1] for r in rows}

    labels = []
    missing = 0
    for sid in sids:
        act = act_map.get(sid)
        if act is None:
            missing += 1
            labels.append("unknown")
        else:
            cls = int(np.argmax(act))
            labels.append(label_names[cls] if cls < len(label_names) else f"class_{cls}")

    if missing > 0.2 * len(sids):
        return None
    return labels


# ── retrieval_rows ────────────────────────────────────────────────────────────


def upsert_retrieval(con, backbone: str, strategy: str, sim_metric: str, k: int, metrics: dict) -> None:
    con.execute(
        """
        INSERT INTO retrieval_rows
          (backbone, strategy, sim_metric, k, map_k, mrr, ndcg_k, recall_k,
           disc_score, mean_within, mean_cross)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, strategy, sim_metric, k)
        DO UPDATE SET
          map_k=excluded.map_k, mrr=excluded.mrr, ndcg_k=excluded.ndcg_k,
          recall_k=excluded.recall_k, disc_score=excluded.disc_score,
          mean_within=excluded.mean_within, mean_cross=excluded.mean_cross
        """,
        [
            backbone,
            strategy,
            sim_metric,
            k,
            metrics.get(f"map_{k}"),
            metrics.get("mrr"),
            metrics.get(f"ndcg_{k}"),
            metrics.get(f"recall_{k}"),
            metrics.get("disc_score"),
            metrics.get("mean_within"),
            metrics.get("mean_cross"),
        ],
    )


# ── ann_rows ──────────────────────────────────────────────────────────────────


def upsert_ann(con, backbone: str, strategy: str, ef_search: int, recall_k: float, backend: str) -> None:
    con.execute(
        """
        INSERT INTO ann_rows (backbone, strategy, ef_search, recall_k, backend)
        VALUES (?,?,?,?,?)
        ON CONFLICT (backbone, strategy, ef_search) DO UPDATE SET
          recall_k=excluded.recall_k, backend=excluded.backend
        """,
        [backbone, strategy, ef_search, recall_k, backend],
    )


# ── ptc_ctp_rows ──────────────────────────────────────────────────────────────


def upsert_ptc_ctp(con, backbone: str, head: str, strategy: str, row: dict) -> None:
    con.execute(
        """
        INSERT INTO ptc_ctp_rows
          (backbone, head, strategy, ptc_disc, ctp_disc, delta_disc, ptc_map, ctp_map, delta_map)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, head, strategy) DO UPDATE SET
          ptc_disc=excluded.ptc_disc, ctp_disc=excluded.ctp_disc,
          delta_disc=excluded.delta_disc, ptc_map=excluded.ptc_map,
          ctp_map=excluded.ctp_map, delta_map=excluded.delta_map
        """,
        [
            backbone,
            head,
            strategy,
            row.get("ptc_disc"),
            row.get("ctp_disc"),
            row.get("delta_disc"),
            row.get("ptc_map"),
            row.get("ctp_map"),
            row.get("delta_map"),
        ],
    )
