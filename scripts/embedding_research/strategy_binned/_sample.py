"""Stratified sample selection helpers."""

from __future__ import annotations

import hashlib as _hashlib

import numpy as _np

from .. import db as _db


def _quantile_bucket(values: _np.ndarray, n_buckets: int) -> _np.ndarray:
    """Assign values to quantile buckets [0..n_buckets-1]."""
    if len(values) == 0:
        return _np.array([], dtype=_np.int32)
    if _np.allclose(values, values[0]):
        return _np.zeros(len(values), dtype=_np.int32)
    edges = _np.quantile(values, _np.linspace(0.0, 1.0, n_buckets + 1))
    edges = _np.unique(edges)
    if len(edges) <= 2:
        return _np.zeros(len(values), dtype=_np.int32)
    return _np.digitize(values, edges[1:-1], right=True).astype(_np.int32)


def _artist_pop_bucket(count: int) -> int:
    if count <= 1:
        return 0
    if count <= 3:
        return 1
    if count <= 7:
        return 2
    return 3


def _stable_stratum_seed(seed: int, key: tuple[int, int, int]) -> int:
    payload = f"{seed}|{key[0]}|{key[1]}|{key[2]}".encode()
    return int.from_bytes(_hashlib.blake2b(payload, digest_size=8).digest(), "little", signed=False)


def _select_stratified_sample(
    con,
    sample_size: int,
    seed: int,
    n_buckets: int = 4,
) -> list[str]:
    """Pick a deterministic stratified song sample from existing binned stats."""
    rows = _db.load_binned_sampling_stats(con)
    if not rows:
        return []

    total = len(rows)
    if sample_size <= 0 or sample_size >= total:
        return [r["song_id"] for r in rows]

    n_bins = _np.array([r["avg_n_bins"] for r in rows], dtype=_np.float64)
    divs = _np.array([r["avg_bin_div_std"] for r in rows], dtype=_np.float64)
    artist_counts: dict[str, int] = {}
    for r in rows:
        artist_counts[r["artist"]] = artist_counts.get(r["artist"], 0) + 1

    bins_bucket = _quantile_bucket(n_bins, n_buckets)
    div_bucket = _quantile_bucket(divs, n_buckets)
    artist_bucket = _np.array(
        [_artist_pop_bucket(artist_counts[r["artist"]]) for r in rows], dtype=_np.int32
    )

    strata: dict[tuple[int, int, int], list[int]] = {}
    for idx, key in enumerate(zip(bins_bucket.tolist(), div_bucket.tolist(), artist_bucket.tolist(), strict=False)):
        strata.setdefault(key, []).append(idx)

    ordered_keys = sorted(strata)
    quotas: dict[tuple[int, int, int], int] = dict.fromkeys(ordered_keys, 0)

    if sample_size >= len(ordered_keys):
        for key in ordered_keys:
            quotas[key] = 1
        remaining = sample_size - len(ordered_keys)
        if remaining > 0:
            fractional: list[tuple[float, tuple[int, int, int]]] = []
            weight_total = float(sum(len(strata[key]) for key in ordered_keys))
            for key in ordered_keys:
                ideal = remaining * len(strata[key]) / weight_total
                fractional.append((ideal - int(ideal), key))
                quotas[key] += int(ideal)
            assigned = sum(quotas.values()) - len(ordered_keys)
            for _frac, key in sorted(fractional, reverse=True)[: max(0, remaining - assigned)]:
                quotas[key] += 1
    else:
        fractional = []
        assigned = 0
        for key in ordered_keys:
            share = sample_size * len(strata[key]) / float(total)
            base = int(share)
            quotas[key] = base
            assigned += base
            fractional.append((share - base, key))
        for _frac, key in sorted(fractional, reverse=True)[: max(0, sample_size - assigned)]:
            quotas[key] += 1

    selected: list[str] = []
    for key in ordered_keys:
        idxs = strata[key][:]
        if not idxs or quotas[key] <= 0:
            continue
        rng = _np.random.default_rng(_stable_stratum_seed(seed, key))
        rng.shuffle(idxs)
        selected.extend(rows[i]["song_id"] for i in idxs[: quotas[key]])

    return selected
