"""Shared analyze phase skeleton for embedding-research strategies."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, TypedDict, cast

import numpy as _np
import numpy as np
from alive_progress import alive_it

try:
    from scipy.stats import kurtosis as _scipy_kurtosis

    def _kurt(arr: list[float] | _np.ndarray) -> float:
        return float(_scipy_kurtosis(arr, fisher=True))

except ImportError:

    def _kurt(arr: list[float] | _np.ndarray) -> float:
        return float("nan")


from scripts.embedding_research import db, similarity
from scripts.embedding_research.cache import flat_heads as _flat_heads_cache
from scripts.embedding_research.cache.sim_pairs import sim_pair_exists, store_sim_pair
from scripts.embedding_research.config import BACKBONES, HEADS
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


def _var_kurt(values_possibly_none: Sequence[float | None]) -> tuple[float | None, float | None]:
    vals = [v for v in values_possibly_none if v is not None]
    if len(vals) < 2:
        return None, None
    return float(_np.var(vals)), _kurt(vals)


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


def _load_head_scores_and_names(backbone: str, sids: list[str]) -> tuple[list[list[float]] | None, list[str] | None]:
    """Load mean/ptc head scores from the filesystem cache.

    Returns one row per head (sorted by head name), each row a list of
    per-song scores aligned to *sids*.  Missing activations default to 0.0.
    """
    head_map = HEADS.get(backbone, {})
    if not head_map:
        return None, None
    head_names = sorted(head_map)
    matrix: list[list[float]] = []
    sids_with_any: set[str] = set()
    for head_name in head_names:
        acts = _flat_heads_cache.load_bulk(backbone, head_name, "mean", "ptc", sids)
        row = [float(acts[sid][-1]) if sid in acts and acts[sid].size >= 2 else 0.0 for sid in sids]
        matrix.append(row)
        sids_with_any.update(acts)
    if not sids_with_any:
        _log.warning(
            "[%s] no head scores found in filesystem cache (mean/ptc) — disc_head will be 0",
            backbone,
        )
        return None, None
    missing = sum(1 for sid in sids if sid not in sids_with_any)
    if missing:
        _log.warning(
            "[%s] %d/%d songs have no head scores in filesystem cache — defaulting to 0.0 (classify ran partially?)",
            backbone,
            missing,
            len(sids),
        )
    return matrix, head_names


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
        progress = alive_it(strategy_names, title=f"[{backbone}] analyze")
        for strategy_name in progress:
            progress.text(f"written={written_for_backbone} skip={skipped_for_backbone}")
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

            head_scores, head_names = _load_head_scores_and_names(backbone, sids)

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
                        sids=sids,
                    )
                    per_song = metrics.pop("per_song", {})
                    metrics.pop("ap_k_genre", None)
                    metrics.pop("ap_k_head", None)
                    db.clear_song_retrieval_metrics(con, strategy_key, sim_metric, k)
                    db.write_song_retrieval_metrics(con, strategy_key, sim_metric, k, per_song)
                    extra: dict[str, float] = {}
                    for flat_name, src_key in [
                        ("var_ap_k", "ap_k"),
                        ("var_disc_artist", "disc_artist_contrib"),
                        ("var_disc_genre", "disc_genre_contrib"),
                        ("var_disc_head", "disc_head_contrib"),
                        ("var_ap_k_genre", "ap_k_genre"),
                        ("var_ap_k_head", "ap_k_head"),
                        ("var_mrr_genre", "mrr_genre"),
                        ("var_mrr_head", "mrr_head"),
                    ]:
                        value, kurt = _var_kurt(per_song.get(src_key, []))
                        if value is not None:
                            extra[flat_name] = value
                            extra[flat_name.replace("var_", "kurt_")] = cast("float", kurt)
                    metrics.update(extra)
                    _map_vals = [
                        metrics.get(_mk)
                        for _mk in ("map_k_artist", "map_k_genre", "map_k_head")
                        if metrics.get(_mk) is not None
                    ]
                    metrics["map_k_general"] = float(np.mean(_map_vals)) if _map_vals else None
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

            rows_all: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
            pair_payloads = _normalise_binned_pairs(vecs, cfg["extra_cfg"])
            for pair_payload in pair_payloads:
                rep_a = pair_payload.get("rep_a")
                rep_b = pair_payload.get("rep_b")
                norm_a_all = pair_payload["norm_a_all"]
                norm_b_all = pair_payload["norm_b_all"]
                bin_counts = np.asarray(pair_payload["bin_counts"], dtype=np.float32)

                data_a = [v.data for v in norm_a_all]
                data_b = [v.data for v in norm_b_all]
                for i in range(len(sids)):
                    for j in range(i + 1, len(sids)):
                        if sim_pair_exists(backbone, strategy_name, sids[i], sids[j]):
                            continue
                        raw_sim = (data_a[i] @ data_b[j].T).astype(np.float32)
                        store_sim_pair(backbone, strategy_name, sids[i], sids[j], raw_sim)

                for sim_metric in sim_metric_names:
                    agg_mats = compute_agg_mats(
                        norm_a_all,
                        norm_b_all,
                        bin_counts,
                        sim_metric,
                    )

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
                            sids=sids,
                        )
                        per_song = metrics.pop("per_song", {})
                        metrics.pop("ap_k_genre", None)
                        metrics.pop("ap_k_head", None)
                        rows_all.append((strategy_key, sim_metric, metrics, per_song))

            for strategy_key, sim_metric, metrics, per_song in rows_all:
                db.clear_song_retrieval_metrics(con, strategy_key, sim_metric, k)
                db.write_song_retrieval_metrics(con, strategy_key, sim_metric, k, per_song)
                extra: dict[str, float] = {}
                for flat_name, src_key in [
                    ("var_ap_k", "ap_k"),
                    ("var_disc_artist", "disc_artist_contrib"),
                    ("var_disc_genre", "disc_genre_contrib"),
                    ("var_disc_head", "disc_head_contrib"),
                    ("var_ap_k_genre", "ap_k_genre"),
                    ("var_ap_k_head", "ap_k_head"),
                    ("var_mrr_genre", "mrr_genre"),
                    ("var_mrr_head", "mrr_head"),
                ]:
                    value, kurt = _var_kurt(per_song.get(src_key, []))
                    if value is not None:
                        extra[flat_name] = value
                        extra[flat_name.replace("var_", "kurt_")] = cast("float", kurt)
                metrics.update(extra)
                _map_vals = [
                    metrics.get(_mk)
                    for _mk in ("map_k_artist", "map_k_genre", "map_k_head")
                    if metrics.get(_mk) is not None
                ]
                metrics["map_k_general"] = float(np.mean(_map_vals)) if _map_vals else None
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
