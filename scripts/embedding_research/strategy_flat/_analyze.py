"""Flat-pool analysis helpers and public analyze() entrypoint."""

from __future__ import annotations

import logging as _logging

import numpy as _np
from tqdm import tqdm as _tqdm

from nomarr.helpers.time_helper import internal_ms as _internal_ms

from ..config import HEAD_LABELS as _HEAD_LABELS
from ..config import HEADS as _HEADS
from ..config import bootstrap_nomarr as _bootstrap_nomarr
from ..db import load_head_labels as _load_head_labels
from ..db import load_pooled_matrix as _load_pooled_matrix
from ..db import query_analysis_done as _query_analysis_done
from ..db import query_embedded_configs as _query_embedded_configs
from ..db import upsert_ann as _upsert_ann
from ..db import upsert_ptc_ctp as _upsert_ptc_ctp
from ..db import upsert_retrieval as _upsert_retrieval
from ..pooling import STRATEGIES as _STRATEGIES
from ..similarity import METRICS as _METRICS
from ..similarity import ann_recall_sweep as _ann_recall_sweep
from ..similarity import compute_retrieval_metrics as _compute_retrieval_metrics
from ..similarity import cosine_matrix as _cosine_matrix

_log = _logging.getLogger(__name__)


def _analyze_strategy(
    con,
    backbone: str,
    strategy: str,
    k: int = 10,
    *,
    song_ids: frozenset[str] | None = None,
) -> None:
    """Compute and store retrieval metrics for all sim metrics for one pair."""
    vecs, sids, artists, albums, genres = _load_pooled_matrix(con, backbone, strategy)
    if len(vecs) == 0:
        _log.info("[%s/%s] no data — skipping", backbone, strategy)
        return
    if song_ids is not None:
        keep = [i for i, s in enumerate(sids) if s in song_ids]
        if len(keep) < len(sids):
            vecs = vecs[keep]
            sids = [sids[i] for i in keep]
            artists = [artists[i] for i in keep]
            albums = [albums[i] for i in keep]
            genres = [genres[i] for i in keep]
    if len(vecs) == 0:
        return

    for metric_name, matrix_fn in _METRICS.items():
        t0_ms = _internal_ms().value
        sim_mat = matrix_fn(vecs)
        metrics = _compute_retrieval_metrics(sim_mat, artists, k=k, albums=albums, genres=genres)
        _upsert_retrieval(con, backbone, strategy, metric_name, k, metrics)
        _log.info(
            "[%s/%s/%s] disc=%.4f map_%d=%.4f  %.1fs",
            backbone, strategy, metric_name,
            metrics["disc_score"], k, metrics[f"map_{k}"],
            (_internal_ms().value - t0_ms) / 1000.0,
        )


def _analyze_ptc_vs_ctp(
    con,
    backbone: str,
    strategies: list[str],
    k: int = 10,
    *,
    song_ids: frozenset[str] | None = None,
) -> None:
    """
    For each (head, strategy): compare PTC vs CTP discrimination on the
    cosine sim matrix of that strategy's pooled embeddings.
    Writes results to DuckDB via upsert_ptc_ctp.
    """
    for head_name in _HEADS.get(backbone, {}):
        label_names = _HEAD_LABELS.get(head_name, ["class_0", "class_1"])

        for strategy in strategies:
            vecs, sids, _artists, _albums, _genres = _load_pooled_matrix(con, backbone, strategy)
            if len(vecs) == 0:
                continue
            if song_ids is not None:
                keep = [i for i, s in enumerate(sids) if s in song_ids]
                if len(keep) < len(sids):
                    vecs = vecs[keep]
                    sids = [sids[i] for i in keep]
            cos_mat = _cosine_matrix(vecs)

            row: dict = {}
            for pathway in ("ptc", "ctp"):
                labels = _load_head_labels(con, sids, backbone, head_name, strategy, pathway, label_names)
                if labels is None:
                    continue
                mask_idx = [i for i, lbl in enumerate(labels) if lbl != "unknown"]
                if len(mask_idx) < 10:
                    continue
                sub_sim = cos_mat[_np.ix_(mask_idx, mask_idx)]
                sub_labels = [labels[i] for i in mask_idx]
                metrics = _compute_retrieval_metrics(sub_sim, sub_labels, k=k)
                row[f"{pathway}_disc"] = metrics["disc_score"]
                row[f"{pathway}_map"] = metrics[f"map_{k}"]

            if "ptc_disc" in row and "ctp_disc" in row:
                row["delta_disc"] = row["ptc_disc"] - row["ctp_disc"]
                row["delta_map"] = row["ptc_map"] - row["ctp_map"]
                _upsert_ptc_ctp(con, backbone, head_name, strategy, row)
                _log.info(
                    "[%s/%s/%s] ptc_disc=%.4f ctp_disc=%.4f delta=%+.4f",
                    backbone, head_name, strategy,
                    row["ptc_disc"], row["ctp_disc"], row["delta_disc"],
                )


def _analyze_ann(
    con,
    backbone: str,
    strategy: str = "mean",
    k: int = 10,
    n_queries: int = 200,
    *,
    song_ids: frozenset[str] | None = None,
) -> None:
    """
    Build HNSW index on cosine space and measure recall@k at various ef_search values.
    Writes results to DuckDB via upsert_ann.
    """
    vecs, sids, artists, _albums, _genres = _load_pooled_matrix(con, backbone, strategy)
    if len(vecs) == 0:
        return
    if song_ids is not None:
        keep = [i for i, s in enumerate(sids) if s in song_ids]
        if len(keep) < len(sids):
            vecs = vecs[keep]
            artists = [artists[i] for i in keep]

    sweep = _ann_recall_sweep(vecs, artists, k=k, n_queries=n_queries)
    for row in sweep.values():
        _upsert_ann(con, backbone, strategy, row["ef_search"], row["recall_k"], row["backend"])
        _log.info("[%s/ann] ef=%3d recall@%d=%.4f (%s)", backbone, row["ef_search"], k, row["recall_k"], row["backend"])


def analyze(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    strategies: list[str] | None = None,
    song_ids: frozenset[str] | None = None,
) -> None:
    """Analyze flat pooled retrieval metrics for incomplete configurations."""
    present = _query_embedded_configs(con)
    if backbones is not None:
        present = {pair for pair in present if pair[0] in backbones}
    if strategies is not None:
        present = {pair for pair in present if pair[1] in strategies}

    done_rows = _query_analysis_done(con)
    required_metrics = set(_METRICS)
    done_by_pair: dict[tuple[str, str], set[str]] = {}
    for backbone, strategy, sim_metric, row_k in done_rows:
        if row_k != k:
            continue
        done_by_pair.setdefault((backbone, strategy), set()).add(sim_metric)

    already_done = {pair for pair in present if required_metrics.issubset(done_by_pair.get(pair, set()))}
    to_do = present - already_done

    if not to_do:
        _log.info("No flat analysis work remaining.")
        return

    _bootstrap_nomarr()

    if backbones is not None:
        bb_names = [bb_name for bb_name in backbones if any(pair[0] == bb_name for pair in to_do)]
    else:
        bb_names = sorted({backbone for backbone, _ in to_do})

    worked_backbones: dict[str, list[str]] = {}
    for bb_name in bb_names:
        bb_strategies = sorted(strategy for backbone, strategy in to_do if backbone == bb_name)
        if not bb_strategies:
            continue

        _log.info("=== %s ===", bb_name)
        for strategy in _tqdm(bb_strategies, desc=f"[{bb_name}] strategies"):
            _analyze_strategy(con, bb_name, strategy, k=k, song_ids=song_ids)
        worked_backbones[bb_name] = bb_strategies

    for bb_name, bb_strategies in worked_backbones.items():
        if _HEADS.get(bb_name):
            _log.info("[%s] Analyzing PTC vs CTP ...", bb_name)
            _analyze_ptc_vs_ctp(con, bb_name, bb_strategies, k=k, song_ids=song_ids)

        _log.info("[%s] Running ANN recall sweep ...", bb_name)
        _analyze_ann(con, bb_name, strategy="mean", k=k, n_queries=200, song_ids=song_ids)

    _log.info("Flat analysis complete.")
