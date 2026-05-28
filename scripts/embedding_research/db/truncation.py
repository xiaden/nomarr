from __future__ import annotations


def upsert_truncation_robustness(
    con,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    flat_mean_sim: float,
    binned_mean_sim: float,
    truncation_robustness_delta: float,
) -> None:
    con.execute(
        """
        INSERT INTO truncation_robustness_rows
          (backbone, bin_mode, std_thresh, flat_mean_sim, binned_mean_sim, truncation_robustness_delta)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (backbone, bin_mode, std_thresh) DO UPDATE SET
          flat_mean_sim = excluded.flat_mean_sim,
          binned_mean_sim = excluded.binned_mean_sim,
          truncation_robustness_delta = excluded.truncation_robustness_delta
        """,
        [backbone, bin_mode, std_thresh, flat_mean_sim, binned_mean_sim, truncation_robustness_delta],
    )
