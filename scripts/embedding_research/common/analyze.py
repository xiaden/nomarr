"""Shared analyze phase skeleton for embedding-research strategies.

LEGACY interim full-matrix analysis path — retained until Plan E rewires ``run.py`` to the
catalog-first primary path (``common.catalog_analysis``).  It computes retrieval metrics over the
legacy N-path similarity matrices (flat/PTC/CTP) on the FULL N x N corpus; the catalog-first path is
per-query/per-candidate-song bounded instead.  ``force=False`` (the default) skips strategies already
in the run's ``done_set`` and preserves their rows unchanged.
"""

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
from scripts.embedding_research.config import BACKBONES, HEADS
from scripts.embedding_research.corpus import MatchingCorpusManifest, validate_matching_corpus
from scripts.embedding_research.strategy_binned._constants import (
    _ALLOWED_AGG_METHODS,
    PRIMARY_SCORE_VARIANT,
    SCORE_VARIANTS,
)
from scripts.embedding_research.strategy_binned._process import (
    compute_agg_mats,
    compute_score_variant_mats,
    score_variant_trace_summary,
)

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
    weights_a: list[Any]
    weights_b: list[Any]


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


def _record_skip(cfg: AnalyzeCfg, label: str, reason: object) -> None:
    """Record a skipped-configuration reason into ``extra_cfg`` diagnostics.

    Consumers of a phase (reports, tests, operators) can read
    ``extra_cfg["skip_reasons"]`` to see which configurations were skipped and
    why (incomplete sidecars/bins/reps, corpus mismatch, ...).
    """
    extra = cfg.get("extra_cfg")
    if extra is None:
        extra = {}
        cfg["extra_cfg"] = extra
    extra.setdefault("skip_reasons", []).append(f"{label}: {reason}")


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
            _copy_extra_cfg(extra_cfg, rep_a=rep_a, rep_b=rep_b, agg_method=scoring_method),
        )
        for rep_a in rep_types
        for rep_b in rep_types
        for scoring_method in SCORE_VARIANTS
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


def _resolve_binned_weights(payload: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    """Resolve per-song bin-weight arrays (source and target side) from a payload.

    Prefers explicit ``weights_a``/``weights_b``; falls back to a shared
    ``weights`` key; otherwise derives uniform per-bin weights from
    ``bin_counts`` (compatibility for legacy/tuple payloads that predate
    weighted scoring).  The main PTC/CTP loaders always supply real per-bin
    patch-count weights, so the fallback only affects dead/legacy callers.
    """
    wa = payload.get("weights_a")
    wb = payload.get("weights_b")
    if wa is not None and wb is not None:
        return list(cast("Sequence[Any]", wa)), list(cast("Sequence[Any]", wb))
    shared = payload.get("weights")
    if shared is not None:
        return list(cast("Sequence[Any]", shared)), list(cast("Sequence[Any]", shared))
    counts = np.asarray(payload["bin_counts"], dtype=np.int64)
    uniform = [np.ones(int(c), dtype=np.float32) for c in counts]
    return uniform, uniform


def validate_binned_weights(
    weights_a: Sequence[Any],
    weights_b: Sequence[Any],
    bin_counts: Sequence[Any],
) -> None:
    """Validate per-song per-bin weight arrays against the ordering contract.

    The weighted binned scoring contract requires that for **every** song the
    per-bin patch-count weight array, the ``rep_a`` bin vectors, and the ``rep_b``
    bin vectors are all ordered by the *same* ascending bin index (the PTC/CTP
    loaders build them from the same per-song, per-bin loop, so they are
    co-indexed).  This validates the two structural guarantees:

    * the number of weight arrays equals the number of songs, and each array's
      length equals that song's bin count (``weights_*[i].size == bin_counts[i]``);
    * every weight is strictly positive (patch counts are never zero, so a zeroed
      or dropped weight array is a corruption signal).

    Any violation raises ``ValueError`` so a misaligned/zeroed weight set fails
    loudly instead of silently producing wrong scores.
    """
    counts = [int(c) for c in bin_counts]
    n_songs = len(counts)
    for side, weights in (("a", weights_a), ("b", weights_b)):
        w_list = list(weights)
        if len(w_list) != n_songs:
            raise ValueError(
                f"weights_{side} has {len(w_list)} per-song arrays but {n_songs} songs; "
                "weight arrays must be co-indexed with the per-song bin vectors"
            )
        for i, w in enumerate(w_list):
            w_arr = np.asarray(w)
            if w_arr.ndim != 1:
                raise ValueError(f"weights_{side}[{i}] must be a 1-D per-bin array, got ndim={w_arr.ndim}")
            if w_arr.shape[0] != counts[i]:
                raise ValueError(
                    f"weights_{side}[{i}] length {w_arr.shape[0]} != bin count {counts[i]}; "
                    "weights, rep_a, and rep_b must share the same song/bin ordering"
                )
            if not bool(np.all(w_arr > 0)):
                raise ValueError(f"weights_{side}[{i}] must be strictly positive (patch counts)")


def _coerce_binned_pair_payload(payload: Any, extra_cfg: Mapping[str, Any]) -> _BinnedPairPayload:
    if isinstance(payload, Mapping):
        if {"norm_a_all", "norm_b_all", "bin_counts"}.issubset(payload):
            weights_a, weights_b = _resolve_binned_weights(payload)
            validate_binned_weights(weights_a, weights_b, payload["bin_counts"])
            return {
                "rep_a": cast("str | None", payload.get("rep_a") or extra_cfg.get("rep_a")),
                "rep_b": cast("str | None", payload.get("rep_b") or extra_cfg.get("rep_b")),
                "norm_a_all": list(cast("Sequence[Any]", payload["norm_a_all"])),
                "norm_b_all": list(cast("Sequence[Any]", payload["norm_b_all"])),
                "bin_counts": np.asarray(payload["bin_counts"], dtype=np.float32),
                "weights_a": weights_a,
                "weights_b": weights_b,
            }
        if {"rep_a", "rep_b", "payload"}.issubset(payload):
            nested = _coerce_binned_pair_payload(payload["payload"], extra_cfg)
            nested["rep_a"] = str(payload["rep_a"])
            nested["rep_b"] = str(payload["rep_b"])
            return nested

    if isinstance(payload, tuple) and len(payload) == 3:
        norm_a_all, norm_b_all, bin_counts = payload
        synthetic: dict[str, Any] = {"norm_a_all": norm_a_all, "norm_b_all": norm_b_all, "bin_counts": bin_counts}
        weights_a, weights_b = _resolve_binned_weights(synthetic)
        validate_binned_weights(weights_a, weights_b, bin_counts)
        return {
            "rep_a": cast("str | None", extra_cfg.get("rep_a")),
            "rep_b": cast("str | None", extra_cfg.get("rep_b")),
            "norm_a_all": list(cast("Sequence[Any]", norm_a_all)),
            "norm_b_all": list(cast("Sequence[Any]", norm_b_all)),
            "bin_counts": np.asarray(bin_counts, dtype=np.float32),
            "weights_a": weights_a,
            "weights_b": weights_b,
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
        shared_weights = vecs.get("weights")
        pair_payloads: list[_BinnedPairPayload] = []
        for key, payload in vecs.items():
            if key in {"bin_counts", "weights", "pairs"}:
                continue
            if isinstance(key, tuple) and len(key) == 2 and shared_bin_counts is not None:
                rep_a, rep_b = str(key[0]), str(key[1])
                if isinstance(payload, Mapping):
                    merged_payload = dict(payload)
                    merged_payload.setdefault("rep_a", rep_a)
                    merged_payload.setdefault("rep_b", rep_b)
                    merged_payload.setdefault("bin_counts", shared_bin_counts)
                    if shared_weights is not None:
                        merged_payload.setdefault("weights", shared_weights)
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
            "weights_a": _filter_indexed(payload["weights_a"], keep),
            "weights_b": _filter_indexed(payload["weights_b"], keep),
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
                _record_skip(cfg, f"{cfg['strategy_type']}:{strategy_name}", f"vector load failed: {exc}")
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
                _record_skip(
                    cfg,
                    f"{cfg['strategy_type']}:{strategy_name}",
                    "< 2 matching-corpus songs (incomplete sidecars/bins/reps)",
                )
                continue

            matching_corpus = cfg["extra_cfg"].get("matching_corpus", {}).get(backbone)
            if matching_corpus is not None:
                try:
                    validate_matching_corpus(
                        cast("MatchingCorpusManifest", matching_corpus),
                        sids,
                        f"{cfg['strategy_type']}:{strategy_name}",
                    )
                except ValueError as exc:
                    # Fail loud: never silently intersect or compare a different
                    # n_songs.  Report the reason into diagnostics and skip.
                    _log.warning("[%s/%s] corpus mismatch — skipping config: %s", backbone, strategy_name, exc)
                    skipped_for_backbone += 1
                    _record_skip(cfg, f"{cfg['strategy_type']}:{strategy_name}", exc)
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
            # Score variants actually evaluated for this run: the configured scoring
            # surface — the primary ``max_per_candidate_segment`` variant plus any
            # opt-in weighted hypotheses.  The shipped config sets
            # ``pooling.score_variants=["max_per_candidate_segment"]`` (primary-only);
            # the full surface ``[primary, *AGG_METHODS]`` is evaluated only when the
            # key is absent from the config.
            score_variants = [
                str(v) for v in cast("Iterable[str]", cfg["extra_cfg"].get("score_variants", SCORE_VARIANTS))
            ]
            for pair_payload in pair_payloads:
                rep_a = pair_payload.get("rep_a")
                rep_b = pair_payload.get("rep_b")
                norm_a_all = pair_payload["norm_a_all"]
                norm_b_all = pair_payload["norm_b_all"]
                weights_a = pair_payload["weights_a"]
                weights_b = pair_payload["weights_b"]

                for sim_metric in sim_metric_names:
                    # Legacy weighted hypotheses (opt-in, labelled comparison formulas).
                    # Only build the weighted matrices when at least one weighted
                    # hypothesis is actually on the requested scoring surface — the
                    # default primary-only path never needs them.
                    weighted_mats = None
                    if any(m in score_variants for m in _ALLOWED_AGG_METHODS):
                        weighted_mats = compute_agg_mats(norm_a_all, norm_b_all, weights_a, weights_b, sim_metric)
                    # Primary score variant: scalar matrix + bounded per-pair traces.
                    sv_result = None
                    if PRIMARY_SCORE_VARIANT in score_variants:
                        sv_result = compute_score_variant_mats(
                            norm_a_all,
                            norm_b_all,
                            weights_a,
                            weights_b,
                            sim_metric,
                        )

                    for scoring_method in score_variants:
                        if scoring_method == PRIMARY_SCORE_VARIANT:
                            # sv_result is guaranteed non-None when the primary
                            # variant is part of the requested scoring surface.
                            assert sv_result is not None
                            sim_mat = sv_result.matrix
                        else:
                            # A weighted hypothesis is present in score_variants
                            # (non-primary), so weighted_mats was built above.
                            assert weighted_mats is not None
                            sim_mat = weighted_mats[scoring_method]
                        strategy_key = cfg["strategy_key_fn"](
                            backbone,
                            strategy_name,
                            _copy_extra_cfg(
                                cfg["extra_cfg"],
                                rep_a=rep_a,
                                rep_b=rep_b,
                                agg_method=scoring_method,
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
                        if scoring_method == PRIMARY_SCORE_VARIANT:
                            # Persist only the bounded, finite-only trace summary —
                            # never the raw matrix or per-pair contribution arrays.
                            assert sv_result is not None
                            metrics.update(score_variant_trace_summary(sv_result))
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
