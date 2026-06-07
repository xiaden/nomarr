"""Binned-embedding pipeline: calibration, retrieval, stats."""

from __future__ import annotations

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


# ── binned_retrieval_rows ─────────────────────────────────────────────────────


# ── binned_classify_ctp / binned_ctp_vecs / binned_ptc_ctp_metrics ───────────


def upsert_binned_classify_ctp_bulk(con, rows: list[tuple]) -> None:
    if not rows:
        return
    con.executemany(
        "INSERT INTO binned_classify_ctp "
        "(song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (song_id, backbone, head, bin_mode, std_thresh, bin_id) "
        "DO NOTHING",
        rows,
    )


def query_classify_ctp_sids(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT song_id FROM binned_classify_ctp WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?",
        [backbone, head, bin_mode, float(std_thresh)],
    ).fetchall()
    return [r[0] for r in rows]


def load_classify_ctp_rows(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    *,
    sid_list: list[str] | None = None,
) -> list[tuple]:
    if sid_list is not None:
        rows: list[tuple] = con.execute(
            "SELECT song_id, act, weight FROM binned_classify_ctp "
            "WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?"
            "  AND song_id = ANY(?)",
            [backbone, head, bin_mode, float(std_thresh), sid_list],
        ).fetchall()
        return rows
    result: list[tuple] = con.execute(
        "SELECT song_id, act, weight FROM binned_classify_ctp "
        "WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?",
        [backbone, head, bin_mode, float(std_thresh)],
    ).fetchall()
    return result


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
            AVG(bs.mean_bin_size) AS avg_mean_bin_size
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
        f"""
        INSERT INTO binned_song_stats
          (song_id, backbone, bin_mode, std_thresh,
           n_bins, n_patches, n_outliers,
           min_bin_size, max_bin_size, mean_bin_size)
        VALUES ({",".join(["?"] * 10)})
        ON CONFLICT (song_id, backbone, bin_mode, std_thresh) DO UPDATE SET
          n_bins=excluded.n_bins, n_patches=excluded.n_patches,
          n_outliers=excluded.n_outliers,
          min_bin_size=excluded.min_bin_size, max_bin_size=excluded.max_bin_size,
          mean_bin_size=excluded.mean_bin_size
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
        ],
    )


# ── binned_ctp_retrieval_rows ──────────────────────────────────────────────────


# ── data hygiene ──────────────────────────────────────────────────────────────
