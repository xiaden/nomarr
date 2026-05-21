"""Flat-embedding pipeline: pooled_vecs, head_results, retrieval_rows, ann_rows, ptc_ctp_rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


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
) -> tuple[np.ndarray, list[str], list[str], list[str], list[str]]:
    """
    Load all pooled vectors for (backbone, strategy).

    Returns:
      vecs    [n, d] float32
      sids    [n] song_id strings
      artists [n] artist label strings
      albums  [n] album label strings (used for disc_album)
      genres  [n] genre tag strings (used for disc_genre)
    """
    rows = con.execute(
        """
        SELECT p.song_id, p.vec, s.artist, s.album, s.genre
        FROM pooled_vecs p
        JOIN songs s USING (song_id)
        WHERE p.backbone=? AND p.strategy=?
        ORDER BY p.song_id
        """,
        [backbone, strategy],
    ).fetchall()

    if not rows:
        return np.empty((0, 0), dtype=np.float32), [], [], [], []

    sids = [r[0] for r in rows]
    vecs = np.array([r[1] for r in rows], dtype=np.float32)
    artists = [r[2] or "unknown" for r in rows]
    albums = [r[3] or "unknown" for r in rows]
    genres = [r[4] or "unknown" for r in rows]
    return vecs, sids, artists, albums, genres


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
    return bool(n >= 2)  # both ptc and ctp


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


def load_retrieval_flat(con) -> "pd.DataFrame":
    """Return all retrieval_rows as a DataFrame, ordered by disc_score DESC."""
    import pandas as pd

    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_album DOUBLE")
    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE")
    return con.execute(
        "SELECT backbone, strategy, sim_metric, k, "
        "disc_artist, disc_album, disc_genre, disc_head, disc_score, "
        "mean_within, mean_cross, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre "
        "FROM retrieval_rows ORDER BY disc_score DESC"
    ).df()


def load_retrieval_binned(con) -> "pd.DataFrame":
    """Return all binned_retrieval_rows as a DataFrame, ordered by disc_score DESC."""
    import pandas as pd

    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_album DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE")
    return con.execute(
        "SELECT backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, "
        "disc_artist, disc_album, disc_genre, disc_head, disc_score, "
        "mean_within, mean_cross, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre "
        "FROM binned_retrieval_rows ORDER BY disc_score DESC"
    ).df()


def upsert_retrieval(con, backbone: str, strategy: str, sim_metric: str, k: int, metrics: dict) -> None:
    # Ensure disc_album column exists (forward migration for alpha DBs).
    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS disc_album DOUBLE")
    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_album DOUBLE")
    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE")
    con.execute(
        """
        INSERT INTO retrieval_rows
          (backbone, strategy, sim_metric, k, map_k, mrr, ndcg_k, recall_k,
           recall_k_album, recall_k_genre,
           disc_score, mean_within, mean_cross,
           disc_artist, disc_album, disc_genre, disc_head)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, strategy, sim_metric, k)
        DO UPDATE SET
          map_k=excluded.map_k, mrr=excluded.mrr, ndcg_k=excluded.ndcg_k,
          recall_k=excluded.recall_k, recall_k_album=excluded.recall_k_album,
          recall_k_genre=excluded.recall_k_genre, disc_score=excluded.disc_score,
          mean_within=excluded.mean_within, mean_cross=excluded.mean_cross,
          disc_artist=excluded.disc_artist, disc_album=excluded.disc_album,
          disc_genre=excluded.disc_genre, disc_head=excluded.disc_head
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
            metrics.get(f"recall_{k}_album"),
            metrics.get(f"recall_{k}_genre"),
            metrics.get("disc_score"),
            metrics.get("mean_within"),
            metrics.get("mean_cross"),
            metrics.get("disc_artist"),
            metrics.get("disc_album"),
            metrics.get("disc_genre"),
            metrics.get("disc_head"),
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
