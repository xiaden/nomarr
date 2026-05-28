"""Shared analyze phase skeleton for embedding-research strategies."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, TypedDict, cast

import numpy as np
from tqdm import tqdm

from scripts.embedding_research import db, similarity
from scripts.embedding_research.config import BACKBONES
from scripts.embedding_research.strategy_binned._constants import AGG_METHODS
from scripts.embedding_research.strategy_binned._process import compute_agg_mats

StrategyType = Literal["global_pool", "ptc", "ctp"]
LoadVecsFn = Callable[[str, str, Any, dict[str, Any]], tuple[Any, list[str], list[str], list[str], list[str]]]
DbWriteFn = Callable[[Any, str, str, str, int, dict[str, Any]], None]
StrategyKeyFn = Callable[[str, str, dict[str, Any]], str]


class AnalyzeCfg(TypedDict):
    """Configuration bag for one analyze phase run."""

    strategy_names: list[str]
    load_vecs_fn: LoadVecsFn
    db_write_fn: DbWriteFn
    strategy_key_fn: StrategyKeyFn
    strategy_type: StrategyType
    extra_cfg: dict[str, Any]


class _BinnedPairPayload(TypedDict, total=False):
    rep_a: str | None
    rep_b: str | None
    norm_a_all: list[Any]
    norm_b_all: list[Any]
    bin_counts: np.ndarray


_log = logging.getLogger(__name__)


def _copy_extra_cfg(extra_cfg: Mapping[str, Any], **updates: Any) -> dict[str, Any]:
    merged = dict(extra_cfg)
    merged.update({key: value for key, value in updates.items() if value is not None})
    return merged


def _build_expected_strategy_keys(backbone: str, strategy_name: str, cfg: AnalyzeCfg) -> set[str]:
    strategy_key_fn = cfg["strategy_key_fn"]
    extra_cfg = cfg["extra_cfg"]
    if cfg["strategy_type"] == "global_pool":
        return {strategy_key_fn(backbone, strategy_name, dict(extra_cfg))}

    rep_types = [str(rep) for rep in cast("Iterable[str]", extra_cfg.get("rep_types", []))]
    if not rep_types:
        return {strategy_key_fn(backbone, strategy_name, dict(extra_cfg))}

    return {
        strategy_key_fn(
            backbone,
            strategy_name,
            _copy_extra_cfg(extra_cfg, rep_a=rep_a, rep_b=rep_b, agg_method=agg_method),
        )
        for rep_a in rep_types
        for rep_b in rep_types
        for agg_method in AGG_METHODS
    }


def _strategy_fully_done(
    done_set: set[tuple[str, str, int]],
    backbone: str,
    strategy_name: str,
    cfg: AnalyzeCfg,
    k: int,
) -> bool:
    expected_keys = _build_expected_strategy_keys(backbone, strategy_name, cfg)
    return all(
        (strategy_key, sim_metric, k) in done_set for strategy_key in expected_keys for sim_metric in similarity.METRICS
    )


def _filter_indexed(values: Sequence[Any], keep: list[int]) -> list[Any]:
    return [values[idx] for idx in keep]


def _filter_global_pool_vecs(vecs: Any, keep: list[int]) -> Any:
    try:
        return vecs[keep]
    except Exception:
        return np.asarray(vecs)[keep]


def _coerce_binned_pair_payload(payload: Any, extra_cfg: Mapping[str, Any]) -> _BinnedPairPayload:
    if isinstance(payload, Mapping):
        if {"norm_a_all", "norm_b_all", "bin_counts"}.issubset(payload):
            return {
                "rep_a": cast("str | None", payload.get("rep_a") or extra_cfg.get("rep_a")),
                "rep_b": cast("str | None", payload.get("rep_b") or extra_cfg.get("rep_b")),
                "norm_a_all": list(cast("Sequence[Any]", payload["norm_a_all"])),
                "norm_b_all": list(cast("Sequence[Any]", payload["norm_b_all"])),
                "bin_counts": np.asarray(payload["bin_counts"], dtype=np.float32),
            }
        if {"rep_a", "rep_b", "payload"}.issubset(payload):
            nested = _coerce_binned_pair_payload(payload["payload"], extra_cfg)
            nested["rep_a"] = str(payload["rep_a"])
            nested["rep_b"] = str(payload["rep_b"])
            return nested

    if isinstance(payload, tuple) and len(payload) == 3:
        norm_a_all, norm_b_all, bin_counts = payload
        return {
            "rep_a": cast("str | None", extra_cfg.get("rep_a")),
            "rep_b": cast("str | None", extra_cfg.get("rep_b")),
            "norm_a_all": list(cast("Sequence[Any]", norm_a_all)),
            "norm_b_all": list(cast("Sequence[Any]", norm_b_all)),
            "bin_counts": np.asarray(bin_counts, dtype=np.float32),
        }

    raise TypeError(
        "Unsupported binned vec payload. Expected a mapping with norm arrays or a "
        "(norm_a_all, norm_b_all, bin_counts) tuple."
    )


def _normalise_binned_pairs(vecs: Any, extra_cfg: Mapping[str, Any]) -> list[_BinnedPairPayload]:
    if isinstance(vecs, Mapping):
        if {"norm_a_all", "norm_b_all", "bin_counts"}.issubset(vecs):
            return [_coerce_binned_pair_payload(vecs, extra_cfg)]
        if "pairs" in vecs:
            return [_coerce_binned_pair_payload(pair, extra_cfg) for pair in cast("Sequence[Any]", vecs["pairs"])]

        shared_bin_counts = vecs.get("bin_counts")
        pair_payloads: list[_BinnedPairPayload] = []
        for key, payload in vecs.items():
            if key in {"bin_counts", "pairs"}:
                continue
            if isinstance(key, tuple) and len(key) == 2 and shared_bin_counts is not None:
                rep_a, rep_b = str(key[0]), str(key[1])
                if isinstance(payload, Mapping):
                    merged_payload = dict(payload)
                    merged_payload.setdefault("rep_a", rep_a)
                    merged_payload.setdefault("rep_b", rep_b)
                    merged_payload.setdefault("bin_counts", shared_bin_counts)
                    pair_payloads.append(_coerce_binned_pair_payload(merged_payload, extra_cfg))
                elif isinstance(payload, tuple) and len(payload) == 2:
                    pair_payloads.append(
                        _coerce_binned_pair_payload(
                            {
                                "rep_a": rep_a,
                                "rep_b": rep_b,
                                "norm_a_all": payload[0],
                                "norm_b_all": payload[1],
                                "bin_counts": shared_bin_counts,
                            },
                            extra_cfg,
                        )
                    )
        if pair_payloads:
            return pair_payloads

    if isinstance(vecs, tuple) and len(vecs) == 3:
        return [_coerce_binned_pair_payload(vecs, extra_cfg)]

    if isinstance(vecs, Sequence) and not isinstance(vecs, (str, bytes, bytearray)):
        return [_coerce_binned_pair_payload(payload, extra_cfg) for payload in vecs]

    raise TypeError("Unsupported binned vec collection returned by load_vecs_fn().")


def _filter_binned_pairs(vecs: Any, keep: list[int], extra_cfg: Mapping[str, Any]) -> list[_BinnedPairPayload]:
    pair_payloads = _normalise_binned_pairs(vecs, extra_cfg)
    return [
        {
            "rep_a": payload.get("rep_a"),
            "rep_b": payload.get("rep_b"),
            "norm_a_all": _filter_indexed(payload["norm_a_all"], keep),
            "norm_b_all": _filter_indexed(payload["norm_b_all"], keep),
            "bin_counts": np.asarray(payload["bin_counts"], dtype=np.float32)[keep],
        }
        for payload in pair_payloads
    ]


def _load_head_scores_and_names(
    con, backbone: str, sids: list[str]
) -> tuple[list[list[float]] | None, list[str] | None]:
    head_scores = cast("list[list[float]] | None", db.query_flat_head_labels(con, backbone, sids))
    if not head_scores:
        return None, None

    head_rows = con.execute(
        "SELECT DISTINCT head FROM flat_head_labels WHERE backbone = ? ORDER BY head",
        [backbone],
    ).fetchall()
    head_names: list[str] | None = [str(row[0]) for row in head_rows]
    if len(head_names) != len(head_scores):
        _log.warning(
            "[%s] head score/name mismatch (%d score rows vs %d names); disabling per-head labels",
            backbone,
            len(head_scores),
            len(head_names),
        )
        head_names = None
    return head_scores, head_names


def analyze(
    con,
    cfg: AnalyzeCfg,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    k: int = 10,
) -> None:
    """Shared analyze phase. Runs retrieval metrics and writes rows to DB."""
    bb_names = list(backbones) if backbones is not None else list(BACKBONES)
    strategy_names = list(cfg["strategy_names"])
    done_set = db.query_analysis_done(con)
    sim_metric_names = list(similarity.METRICS)

    total_written = 0
    for backbone in bb_names:
        written_for_backbone = 0
        skipped_for_backbone = 0
        progress = tqdm(strategy_names, desc=f"[{backbone}] analyze", unit="strategy")
        for strategy_name in progress:
            progress.set_postfix(written=written_for_backbone, skip=skipped_for_backbone, refresh=False)
            if not force and _strategy_fully_done(done_set, backbone, strategy_name, cfg, k):
                skipped_for_backbone += 1
                continue

            t0 = time.perf_counter()
            try:
                vecs, sids, artists, albums, genres = cfg["load_vecs_fn"](
                    backbone, strategy_name, con, cfg["extra_cfg"]
                )
            except Exception as exc:
                _log.warning("[%s/%s] vector load failed: %s", backbone, strategy_name, exc)
                continue

            if song_ids is not None:
                keep = [idx for idx, sid in enumerate(sids) if sid in song_ids]
                if len(keep) < len(sids):
                    sids = _filter_indexed(sids, keep)
                    artists = _filter_indexed(artists, keep)
                    albums = _filter_indexed(albums, keep)
                    genres = _filter_indexed(genres, keep)
                    if cfg["strategy_type"] == "global_pool":
                        vecs = _filter_global_pool_vecs(vecs, keep)
                    else:
                        vecs = _filter_binned_pairs(vecs, keep, cfg["extra_cfg"])

            if len(sids) < 2:
                _log.info("[%s/%s] < 2 songs after filtering; skipping", backbone, strategy_name)
                skipped_for_backbone += 1
                continue

            head_scores, head_names = _load_head_scores_and_names(con, backbone, sids)

            if cfg["strategy_type"] == "global_pool":
                strategy_key = cfg["strategy_key_fn"](backbone, strategy_name, dict(cfg["extra_cfg"]))
                rows_written = 0
                for sim_metric in sim_metric_names:
                    if not force and (strategy_key, sim_metric, k) in done_set:
                        continue
                    sim_mat = similarity.METRICS[sim_metric](vecs)
                    metrics = similarity.compute_retrieval_metrics(
                        sim_mat,
                        artists,
                        k=k,
                        albums=albums,
                        genres=genres,
                        head_scores=cast("list[list[float]] | None", head_scores),
                        head_names=head_names,
                    )
                    cfg["db_write_fn"](con, strategy_key, cfg["strategy_type"], sim_metric, k, metrics)
                    done_set.add((strategy_key, sim_metric, k))
                    rows_written += 1
                if rows_written:
                    written_for_backbone += rows_written
                    total_written += rows_written
                _log.info(
                    "[%s/%s] wrote %d sim-metric row(s) in %.1fs",
                    backbone,
                    strategy_name,
                    rows_written,
                    time.perf_counter() - t0,
                )
                continue

            rows_all: list[tuple[str, str, dict[str, Any]]] = []
            pair_payloads = _normalise_binned_pairs(vecs, cfg["extra_cfg"])
            for pair_payload in pair_payloads:
                rep_a = pair_payload.get("rep_a")
                rep_b = pair_payload.get("rep_b")
                norm_a_all = pair_payload["norm_a_all"]
                norm_b_all = pair_payload["norm_b_all"]
                bin_counts = np.asarray(pair_payload["bin_counts"], dtype=np.float32)

                for sim_metric in sim_metric_names:
                    inner_bar = tqdm(
                        total=len(sids),
                        leave=False,
                        desc=f"  {strategy_name}:{rep_a or '?'}:{rep_b or '?'}:{sim_metric}",
                    )
                    try:
                        agg_mats = compute_agg_mats(
                            norm_a_all,
                            norm_b_all,
                            bin_counts,
                            sim_metric,
                            progress=inner_bar,
                        )
                    finally:
                        inner_bar.close()

                    for agg_method, sim_mat in agg_mats.items():
                        strategy_key = cfg["strategy_key_fn"](
                            backbone,
                            strategy_name,
                            _copy_extra_cfg(
                                cfg["extra_cfg"],
                                rep_a=rep_a,
                                rep_b=rep_b,
                                agg_method=agg_method,
                            ),
                        )
                        if not force and (strategy_key, sim_metric, k) in done_set:
                            continue
                        metrics = similarity.compute_retrieval_metrics(
                            sim_mat,
                            artists,
                            k=k,
                            albums=albums,
                            genres=genres,
                            head_scores=cast("list[list[float]] | None", head_scores),
                            head_names=head_names,
                        )
                        rows_all.append((strategy_key, sim_metric, metrics))

            for strategy_key, sim_metric, metrics in rows_all:
                cfg["db_write_fn"](con, strategy_key, cfg["strategy_type"], sim_metric, k, metrics)
                done_set.add((strategy_key, sim_metric, k))

            if rows_all:
                written_for_backbone += len(rows_all)
                total_written += len(rows_all)
            else:
                skipped_for_backbone += 1
            _log.info(
                "[%s/%s] wrote %d sim-metric row(s) in %.1fs",
                backbone,
                strategy_name,
                len(rows_all),
                time.perf_counter() - t0,
            )

        _log.info(
            "[%s] analyze complete for type=%s: wrote=%d skipped=%d",
            backbone,
            cfg["strategy_type"],
            written_for_backbone,
            skipped_for_backbone,
        )

    _log.info("Analyze phase complete for type=%s: wrote=%d", cfg["strategy_type"], total_written)


__all__ = ["AnalyzeCfg", "analyze"]
