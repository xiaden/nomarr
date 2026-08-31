"""Thin segment-phase adapter for global pooling strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.embedding_research.cache import flat_vecs
from scripts.embedding_research.pooling import STRATEGIES

if TYPE_CHECKING:
    import numpy as np

STRATEGY_NAMES: list[str] = list(STRATEGIES.keys())

_DONE_KEYS_CACHE: set[tuple[str, str, str]] | None = None


def _get_done_keys() -> set[tuple[str, str, str]]:
    global _DONE_KEYS_CACHE
    if _DONE_KEYS_CACHE is None:
        _DONE_KEYS_CACHE = flat_vecs.list_done_keys()
    return _DONE_KEYS_CACHE


def segment_fn(patches: np.ndarray, backbone: str, strategy_name: str) -> dict[str, np.ndarray]:
    """Pool one song's patch matrix for a single named global strategy."""
    del backbone
    return {strategy_name: STRATEGIES[strategy_name](patches)}


def _skip_check(song_id: str, backbone: str, strategy_name: str) -> bool:
    return (song_id, backbone, strategy_name) in _get_done_keys()


SKIP_CHECK_FN = _skip_check


def _cache_write(song_id: str, backbone: str, strategy_name: str, result: dict[str, np.ndarray]) -> None:
    flat_vecs.save_pooled(song_id, backbone, strategy_name, result[strategy_name])


CACHE_WRITE_FN = _cache_write
