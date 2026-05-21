"""Binned-embedding pipeline: calibration, binned_vecs, binned_head_results, retrieval, stats."""

from __future__ import annotations

import numpy as np


# ── binned_calibration ───────────────────────────────────────────────────────


def upsert_calibration(
    con,
    backbone: str,
    dist_mode: str,
    p10: float,
    p25: float,
    p50: float,
    p75: float,
    mean_d: float,
    sigma_d: float,
    n_patches: int,
) -> None:
    con.execute(
        """
        INSERT INTO binned_calibration
          (backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d, n_patches)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, dist_mode) DO UPDATE SET
          p10=excluded.p10, p25=excluded.p25, p50=excluded.p50, p75=excluded.p75,
          mean_d=excluded.mean_d, sigma_d=excluded.sigma_d, n_patches=excluded.n_patches
        """,
        [backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d, n_patches],
    )


def load_calibration(con, backbone: str, dist_mode: str) -> dict | None:
    row = con.execute(
        "SELECT p10, p25, p50, p75, mean_d, sigma_d, n_patches FROM binned_calibration "
        "WHERE backbone=? AND dist_mode=?",
        [backbone, dist_mode],
    ).fetchone()
    if row is None:
        return None
    return dict(zip(("p10", "p25", "p50", "p75", "mean_d", "sigma_d", "n_patches"), row, strict=False))


# ── binned_vecs ───────────────────────────────────────────────────────────────


def upsert_binned_vec(
    con,
    song_id: str,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    bin_id: int,
    pool_strategy: str,
    vec_raw: np.ndarray,
    vec_norm: np.ndarray,
    weight: int,
    outlier_count: int = 0,
) -> None:
    con.execute(
        """
        INSERT INTO binned_vecs
          (song_id, backbone, bin_mode, std_thresh, bin_id, pool_strategy,
           vec_raw, vec_norm, weight, outlier_count)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (song_id, backbone, bin_mode, std_thresh, bin_id, pool_strategy) DO UPDATE SET
          vec_raw=excluded.vec_raw, vec_norm=excluded.vec_norm,
          weight=excluded.weight, outlier_count=excluded.outlier_count
        """,
        [
            song_id,
            backbone,
            bin_mode,
            std_thresh,
            bin_id,
            pool_strategy,
            vec_raw.astype(np.float32).tobytes(),
            vec_norm.astype(np.float32).tobytes(),
            weight,
            outlier_count,
        ],
    )


def binned_song_done(con, song_id: str, backbone: str, bin_mode: str, std_thresh: float) -> bool:
    """Return True if this (song, backbone, bin_mode, std_thresh) has at least one binned_vecs row."""
    return (
        con.execute(
            "SELECT 1 FROM binned_vecs WHERE song_id=? AND backbone=? AND bin_mode=? AND std_thresh=? LIMIT 1",
            [song_id, backbone, bin_mode, std_thresh],
        ).fetchone()
        is not None
    )


def load_binned_matrix(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    pool_strategy: str,
    vec_type: str,  # 'raw' or 'norm'
) -> tuple[list[list[dict]], list[str], list[str]]:
    """
    Load all binned vectors for (backbone, bin_mode, std_thresh, pool_strategy, vec_type).

    Returns:
      song_bins : list[list[dict]]   — per-song list of {"vec": [d], "weight": int, "bin_id": int}
      sids      : list[str]          — song_id per song (same order as song_bins)
      artists   : list[str]          — artist label per song
    """
    col = "vec_raw" if vec_type == "raw" else "vec_norm"
    rows = con.execute(
        f"""
        SELECT bv.song_id, bv.bin_id, bv.{col}, bv.weight, s.artist
        FROM binned_vecs bv
        JOIN songs s USING (song_id)
        WHERE bv.backbone=? AND bv.bin_mode=? AND bv.std_thresh=? AND bv.pool_strategy=?
        ORDER BY bv.song_id, bv.bin_id
        """,
        [backbone, bin_mode, std_thresh, pool_strategy],
    ).fetchall()

    if not rows:
        return [], [], []

    # Group by song_id (rows are sorted by song_id, bin_id)
    song_bins: list[list[dict]] = []
    sids: list[str] = []
    artists: list[str] = []

    prev_sid: str | None = None
    current_bins: list[dict] = []
    current_artist: str = "unknown"

    for sid, bin_id, vec, weight, artist in rows:
        if sid != prev_sid:
            if prev_sid is not None:
                song_bins.append(current_bins)
                sids.append(prev_sid)
                artists.append(current_artist)
            current_bins = []
            current_artist = artist or "unknown"
            prev_sid = sid
        current_bins.append({"vec": np.frombuffer(vec, dtype=np.float32), "weight": weight, "bin_id": bin_id})

    if prev_sid is not None:
        song_bins.append(current_bins)
        sids.append(prev_sid)
        artists.append(current_artist)

    return song_bins, sids, artists


# ── binned_head_results ───────────────────────────────────────────────────────


def upsert_binned_head(
    con,
    song_id: str,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    bin_id: int,
    act: list[float],
    weight: int,
) -> None:
    con.execute(
        """
        INSERT INTO binned_head_results
          (song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (song_id, backbone, head, bin_mode, std_thresh, bin_id) DO UPDATE SET
          act=excluded.act, weight=excluded.weight
        """,
        [song_id, backbone, head, bin_mode, std_thresh, bin_id, np.array(act, dtype=np.float32).tobytes(), weight],
    )


def load_binned_head_decisions(
    con,
    sids: list[str],
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    label_names: list[str],
) -> list[str] | None:
    """
    Return per-song weighted-majority label from binned_head_results.
    Weight = number of patches in the bin. Returns None if >20% missing.
    """
    rows = con.execute(
        """
        SELECT song_id, bin_id, act, weight
        FROM binned_head_results
        WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?
        """,
        [backbone, head, bin_mode, std_thresh],
    ).fetchall()

    # Group by song: accumulate weighted activations
    song_acts: dict[str, np.ndarray] = {}
    for sid, _bin_id, act, weight in rows:
        arr = np.frombuffer(act, dtype=np.float32) * weight
        if sid in song_acts:
            song_acts[sid] = song_acts[sid] + arr
        else:
            song_acts[sid] = arr

    labels = []
    missing = 0
    for sid in sids:
        if sid not in song_acts:
            missing += 1
            labels.append("unknown")
        else:
            cls = int(np.argmax(song_acts[sid]))
            labels.append(label_names[cls] if cls < len(label_names) else f"class_{cls}")

    if missing > 0.2 * len(sids):
        return None
    return labels


# ── binned_retrieval_rows ─────────────────────────────────────────────────────


def upsert_binned_retrieval(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    sim_metric: str,
    agg_method: str,
    k: int,
    metrics: dict,
) -> None:
    con.execute(
        """
        INSERT INTO binned_retrieval_rows
          (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k,
           disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre,
           mean_within, mean_cross, disc_artist, disc_album, disc_genre, disc_head)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)
        DO UPDATE SET
          disc_score=excluded.disc_score, map_k=excluded.map_k, mrr=excluded.mrr,
          ndcg_k=excluded.ndcg_k, recall_k=excluded.recall_k,
          recall_k_album=excluded.recall_k_album, recall_k_genre=excluded.recall_k_genre,
          mean_within=excluded.mean_within, mean_cross=excluded.mean_cross,
          disc_artist=excluded.disc_artist, disc_album=excluded.disc_album,
          disc_genre=excluded.disc_genre, disc_head=excluded.disc_head
        """,
        [
            backbone,
            bin_mode,
            std_thresh,
            rep_a,
            rep_b,
            sim_metric,
            agg_method,
            k,
            metrics.get("disc_score"),
            metrics.get(f"map_{k}"),
            metrics.get("mrr"),
            metrics.get(f"ndcg_{k}"),
            metrics.get(f"recall_{k}"),
            metrics.get(f"recall_{k}_album"),
            metrics.get(f"recall_{k}_genre"),
            metrics.get("mean_within"),
            metrics.get("mean_cross"),
            metrics.get("disc_artist"),
            metrics.get("disc_album"),
            metrics.get("disc_genre"),
            metrics.get("disc_head"),
        ],
    )


def upsert_binned_retrieval_bulk(con, rows: list[tuple]) -> None:
    """
    Bulk-insert/upsert a list of binned retrieval metric rows.

    Each tuple must be ordered as:
      (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k,
       disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre,
       mean_within, mean_cross, disc_artist, disc_album, disc_genre, disc_head)
    """
    if not rows:
        return
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_album DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE")
    con.executemany(
        """
        INSERT INTO binned_retrieval_rows
          (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k,
           disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre,
           mean_within, mean_cross, disc_artist, disc_album, disc_genre, disc_head)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)
        DO UPDATE SET
          disc_score=excluded.disc_score, map_k=excluded.map_k, mrr=excluded.mrr,
          ndcg_k=excluded.ndcg_k, recall_k=excluded.recall_k,
          recall_k_album=excluded.recall_k_album, recall_k_genre=excluded.recall_k_genre,
          mean_within=excluded.mean_within, mean_cross=excluded.mean_cross,
          disc_artist=excluded.disc_artist, disc_album=excluded.disc_album,
          disc_genre=excluded.disc_genre, disc_head=excluded.disc_head
        """,
        rows,
    )


# ── head_sim_corr_rows ────────────────────────────────────────────────────────


def upsert_head_sim_corr_batch(con, rows: list[tuple]) -> None:
    """
    Bulk-insert per-head Spearman correlation rows.

    Each tuple must be ordered as:
      (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head, corr)
    """
    if not rows:
        return
    con.executemany(
        """
        INSERT INTO head_sim_corr_rows
          (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head, corr)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head)
        DO UPDATE SET corr=excluded.corr
        """,
        rows,
    )


def query_head_sim_corr(con):
    """Return the head_sim_corr_rows table as a pandas DataFrame."""
    import pandas as pd

    return con.execute(
        """
        SELECT backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head, corr
        FROM head_sim_corr_rows
        ORDER BY backbone, head, bin_mode, std_thresh
        """
    ).df()


# ── head_agreement_rows ───────────────────────────────────────────────────────


def upsert_head_agreement(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    agreement_rate: float,
    n_songs: int,
) -> None:
    con.execute(
        """
        INSERT INTO head_agreement_rows (backbone, head, bin_mode, std_thresh, agreement_rate, n_songs)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT (backbone, head, bin_mode, std_thresh) DO UPDATE SET
          agreement_rate=excluded.agreement_rate, n_songs=excluded.n_songs
        """,
        [backbone, head, bin_mode, std_thresh, agreement_rate, n_songs],
    )


# ── binned_ptc_ctp_metrics ────────────────────────────────────────────────────


def upsert_binned_ptc_ctp_metrics(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    head: str,
    divergence_mean: float,
    bin_count_var: float,
    sim_align_corr: float,
) -> None:
    con.execute(
        """
        INSERT INTO binned_ptc_ctp_metrics
          (backbone, bin_mode, std_thresh, head,
           divergence_mean, bin_count_var, sim_align_corr)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (backbone, bin_mode, std_thresh, head) DO UPDATE SET
          divergence_mean=excluded.divergence_mean,
          bin_count_var=excluded.bin_count_var,
          sim_align_corr=excluded.sim_align_corr
        """,
        [backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr],
    )


# ── load_binned_all_reps ──────────────────────────────────────────────────────


def load_binned_all_reps(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    vec_type: str = "raw",
    song_ids: list[str] | None = None,
) -> tuple[list[str], list[str], list[list[dict]]]:
    """
    Load all pool-strategy vectors for every bin of every song from the file cache.

    Returns
    -------
    sids       : list[str]         - song_id per song (sorted)
    artists    : list[str]         - artist label per song
    song_data  : list[list[dict]]  - per-song list of bin dicts, each containing:
                   bin_id, weight, outlier_count,
                   vec_mean, vec_median, vec_max, vec_min  (float32 arrays)

    Songs missing any of the four pool strategies for any bin are excluded.
    """
    from ..strategy_binned._cache import list_sids_for_config as _list_sids
    from ..strategy_binned._cache import load_bins as _cache_load_bins

    # Artist map from DB
    song_rows = con.execute("SELECT song_id, artist FROM songs").fetchall()
    artist_map: dict[str, str] = {str(r[0]): r[1] or "unknown" for r in song_rows}

    config_sids = _list_sids(backbone, bin_mode, std_thresh)
    # Always restrict to songs actually in the DB — avoids loading stale
    # corpus data from previous larger runs that are still on disk.
    config_sids &= set(artist_map.keys())
    if song_ids is not None:
        config_sids &= set(song_ids)

    required = {"vec_mean", "vec_median", "vec_max", "vec_min"}
    sids_out: list[str] = []
    artists_out: list[str] = []
    song_data_out: list[list[dict]] = []

    for sid in sorted(config_sids):
        try:
            bins = _cache_load_bins(backbone, bin_mode, std_thresh, sid, vec_type=vec_type)
        except Exception:
            continue
        if not bins:
            continue
        if not all(required.issubset(b) for b in bins):
            continue
        sids_out.append(sid)
        artists_out.append(artist_map.get(sid, "unknown"))
        song_data_out.append(bins)

    return sids_out, artists_out, song_data_out


# ── load_sids_and_artists ─────────────────────────────────────────────────────


def load_sids_and_artists(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
) -> tuple[list[str], list[str]]:
    """Lightweight metadata-only load for the incremental analyze() flow.

    Returns the sorted list of song IDs that are present in **both** the DB
    and the filesystem cache for the given config, paired with their artist
    labels.  No bin data is loaded — callers that need bin arrays should use
    ``_cache.load_norm_pair`` or ``_cache.load_bin_stats`` per song.

    Returns
    -------
    sids    : sorted list[str]
    artists : list[str] aligned with sids
    """
    from ..strategy_binned._cache import list_sids_for_config as _list_sids

    song_rows = con.execute("SELECT song_id, artist FROM songs").fetchall()
    artist_map: dict[str, str] = {str(r[0]): r[1] or "unknown" for r in song_rows}

    config_sids = _list_sids(backbone, bin_mode, std_thresh) & set(artist_map.keys())
    sids = sorted(config_sids)
    return sids, [artist_map[s] for s in sids]


def retrieval_rows_exist(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
) -> bool:
    """Return True if binned_retrieval_rows already contains rows for this pair."""
    count = con.execute(
        """
        SELECT COUNT(*) FROM binned_retrieval_rows
        WHERE backbone=? AND bin_mode=? AND std_thresh=?
          AND rep_a=? AND rep_b=? AND sim_metric=?
        """,
        [backbone, bin_mode, std_thresh, rep_a, rep_b, metric],
    ).fetchone()[0]
    return count > 0


# ── binned_song_stats ─────────────────────────────────────────────────────────


def load_binned_sampling_stats(con) -> list[dict]:
    """
    Load one row per song with aggregated binned-analysis stats across all
    completed configs.

    Intended for deterministic stratified sampling of the overall library.
    """
    rows = con.execute(
        """
        SELECT
            bs.song_id,
            s.artist,
            COUNT(*) AS n_configs,
            AVG(bs.n_bins) AS avg_n_bins,
            AVG(bs.n_patches) AS avg_n_patches,
            AVG(bs.n_outliers) AS avg_n_outliers,
            AVG(bs.mean_bin_size) AS avg_mean_bin_size,
            AVG(bs.bin_div_std) AS avg_bin_div_std
        FROM binned_song_stats bs
        JOIN songs s USING (song_id)
        GROUP BY bs.song_id, s.artist
        ORDER BY bs.song_id
        """
    ).fetchall()
    return [
        {
            "song_id": r[0],
            "artist": r[1],
            "n_configs": int(r[2]),
            "avg_n_bins": float(r[3]) if r[3] is not None else 0.0,
            "avg_n_patches": float(r[4]) if r[4] is not None else 0.0,
            "avg_n_outliers": float(r[5]) if r[5] is not None else 0.0,
            "avg_mean_bin_size": float(r[6]) if r[6] is not None else 0.0,
            "avg_bin_div_std": float(r[7]) if r[7] is not None else 0.0,
        }
        for r in rows
    ]


def upsert_binned_song_stats(
    con,
    song_id: str,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    stats: dict,
) -> None:
    con.execute(
        """
        INSERT INTO binned_song_stats
          (song_id, backbone, bin_mode, std_thresh,
           n_bins, n_patches, n_outliers,
           min_bin_size, max_bin_size, mean_bin_size, bin_div_std)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (song_id, backbone, bin_mode, std_thresh) DO UPDATE SET
          n_bins=excluded.n_bins, n_patches=excluded.n_patches,
          n_outliers=excluded.n_outliers,
          min_bin_size=excluded.min_bin_size, max_bin_size=excluded.max_bin_size,
          mean_bin_size=excluded.mean_bin_size, bin_div_std=excluded.bin_div_std
        """,
        [
            song_id,
            backbone,
            bin_mode,
            std_thresh,
            stats.get("n_bins"),
            stats.get("n_patches"),
            stats.get("n_outliers"),
            stats.get("min_bin_size"),
            stats.get("max_bin_size"),
            stats.get("mean_bin_size"),
            stats.get("bin_div_std"),
        ],
    )


# ── binned_pair_sims ──────────────────────────────────────────────────────────


def upsert_binned_pair_sims_bulk(
    con,
    rows: list[tuple],
) -> None:
    """
    Bulk-upsert per-pair sim scores.
    Each tuple: (song_a, song_b, backbone, bin_mode, std_thresh,
                 rep_a, rep_b, sim_metric, agg_method, score)
    Always stores with song_a < song_b.
    """
    normalised = [
        (min(a, b), max(a, b), bb, bm, st, ra, rb, sm, am, sc) for (a, b, bb, bm, st, ra, rb, sm, am, sc) in rows
    ]
    con.executemany(
        """
        INSERT INTO binned_pair_sims
          (song_a, song_b, backbone, bin_mode, std_thresh,
           rep_a, rep_b, sim_metric, agg_method, score)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (song_a, song_b, backbone, bin_mode, std_thresh,
                     rep_a, rep_b, sim_metric, agg_method)
        DO UPDATE SET score=excluded.score
        """,
        normalised,
    )


# ── binned_ctp_vecs / binned_ctp_retrieval_rows ───────────────────────────────


def query_ctp_configs(con) -> set[tuple[str, str, str, float]]:
    """Return all (backbone, head, bin_mode, std_thresh) present in binned_ctp_vecs."""
    try:
        rows = con.execute(
            "SELECT DISTINCT backbone, head, bin_mode, std_thresh FROM binned_ctp_vecs"
        ).fetchall()
    except Exception:
        return set()
    return {(bb, hd, bm, float(st)) for bb, hd, bm, st in rows}


def query_ctp_analysis_done(con) -> set[tuple[str, str, str, float, int]]:
    """Return all (backbone, head, bin_mode, std_thresh, k) in binned_ctp_retrieval_rows."""
    try:
        rows = con.execute(
            "SELECT DISTINCT backbone, head, bin_mode, std_thresh, k FROM binned_ctp_retrieval_rows"
        ).fetchall()
    except Exception:
        return set()
    return {(bb, hd, bm, float(st), int(k)) for bb, hd, bm, st, k in rows}


def load_ctp_all_reps(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_ids: frozenset[str] | None = None,
) -> tuple[list[str], list[str], list[list[dict]]]:
    """
    Load all four pool-strategy CTP vectors for every bin of every song.

    Queries binned_ctp_vecs (segments driven by head score-stream STD-binning).

    Returns
    -------
    sids       : list[str]         - song_id per song (sorted)
    artists    : list[str]         - artist label per song
    song_data  : list[list[dict]]  - per-song list of bin dicts, each containing:
                   bin_id, weight, outlier_count,
                   vec_mean, vec_median, vec_max, vec_min  (float32 arrays)

    Songs missing any of the four pool strategies for any bin are excluded.
    """
    rows = con.execute(
        """
        SELECT cv.song_id, cv.bin_id, cv.pool_strategy, cv.vec_raw,
               cv.weight, cv.outlier_count, s.artist
        FROM   binned_ctp_vecs cv
        JOIN   songs           s  USING (song_id)
        WHERE  cv.backbone=? AND cv.head=? AND cv.bin_mode=? AND cv.std_thresh=?
        ORDER  BY cv.song_id, cv.bin_id, cv.pool_strategy
        """,
        [backbone, head, bin_mode, std_thresh],
    ).fetchall()

    if not rows:
        return [], [], []

    from collections import defaultdict

    raw: dict[str, dict[int, dict]] = defaultdict(dict)
    artist_map: dict[str, str] = {}

    for sid, bin_id, pool_strategy, vec, weight, outlier_count, artist in rows:
        artist_map[sid] = artist or "unknown"
        if bin_id not in raw[sid]:
            raw[sid][bin_id] = {"weight": weight, "outlier_count": outlier_count}
        raw[sid][bin_id][f"vec_{pool_strategy}"] = np.frombuffer(vec, dtype=np.float32)

    if song_ids is not None:
        raw = {k: v for k, v in raw.items() if k in song_ids}

    required = {"vec_mean", "vec_median", "vec_max", "vec_min"}
    sids: list[str] = []
    artists: list[str] = []
    song_data: list[list[dict]] = []

    for sid in sorted(raw):
        bins_dict = raw[sid]
        bins_list: list[dict] = []
        complete = True
        for bin_id in sorted(bins_dict):
            b = bins_dict[bin_id]
            if not required.issubset(b):
                complete = False
                break
            bins_list.append(
                {
                    "bin_id": bin_id,
                    "weight": b["weight"],
                    "outlier_count": b["outlier_count"],
                    "vec_mean": b["vec_mean"],
                    "vec_median": b["vec_median"],
                    "vec_max": b["vec_max"],
                    "vec_min": b["vec_min"],
                }
            )
        if complete and bins_list:
            sids.append(sid)
            artists.append(artist_map[sid])
            song_data.append(bins_list)

    return sids, artists, song_data


def upsert_ctp_retrieval_bulk(con, rows: list[tuple]) -> None:
    """
    Bulk-insert/upsert CTP retrieval metric rows into binned_ctp_retrieval_rows.

    Each tuple must be ordered as:
      (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k,
       disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre,
       mean_within, mean_cross, disc_artist, disc_album, disc_genre, disc_head)
    """
    if not rows:
        return
    con.execute("ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_album DOUBLE")
    con.execute("ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE")
    con.executemany(
        """
        INSERT INTO binned_ctp_retrieval_rows
          (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k,
           disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_album, recall_k_genre,
           mean_within, mean_cross, disc_artist, disc_album, disc_genre, disc_head)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)
        DO UPDATE SET
          disc_score=excluded.disc_score, map_k=excluded.map_k, mrr=excluded.mrr,
          ndcg_k=excluded.ndcg_k, recall_k=excluded.recall_k,
          recall_k_album=excluded.recall_k_album, recall_k_genre=excluded.recall_k_genre,
          mean_within=excluded.mean_within, mean_cross=excluded.mean_cross,
          disc_artist=excluded.disc_artist, disc_album=excluded.disc_album,
          disc_genre=excluded.disc_genre, disc_head=excluded.disc_head
        """,
        rows,
    )


def query_ctp_retrieval(con):
    """Return binned_ctp_retrieval_rows as a pandas DataFrame."""
    import pandas as pd

    try:
        return con.execute(
            """
            SELECT backbone, head, bin_mode, std_thresh, rep_a, rep_b,
                   sim_metric, agg_method, k,
                   disc_score, map_k, mrr, ndcg_k, recall_k,
                   recall_k_album, recall_k_genre,
                   mean_within, mean_cross,
                   disc_artist, disc_album, disc_genre, disc_head
            FROM binned_ctp_retrieval_rows
            ORDER BY backbone, head, bin_mode, std_thresh
            """
        ).df()
    except Exception:
        return pd.DataFrame()
