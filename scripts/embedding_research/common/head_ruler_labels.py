"""Frozen semantic-head ruler label resolution (Experiment One Plan A Phase 3).

This is the concrete owner of the HEAD ruler's semantic label.  For ONE
``(song_id, backbone)`` it resolves the song's CURRENT committed head suite through the
supplied ``HeadStreamStore`` root seam, loads the CURRENT committed observation group
through the supplied ``StreamStore`` seam, and pools each canonical head's frozen
activation over EXACTLY the committed whole-song searchable rows (``mask == 1``).
The class-1 probability ``act[1]`` of that pooled mean classifies the head side
(``1`` iff finite and ``>= 0.5`` else ``0``); the canonical text comes from
``config.HEAD_LABELS[head][side]``.

The resolved :class:`HeadSongLabel` carries the ordered ``full_tuple`` over EVERY canonical
head in canonical (sorted head-suite) order and, SEPARATELY, the head-suite identity/
fingerprint plus the stream/mask refs+digests and per-head dimensions.  Two songs are
head-relevant exactly when their complete ordered ``full_tuple`` values are identical;
the suite identity is retained only as provenance and is never the ruler label.

Missing evidence (no CURRENT marker, no committed observation, no mask, no searchable row,
no head id, an absent payload, a non-binary head dimension, a misaligned row count, or a
head id with no canonical label) yields NO label (``None``) for that song — it is excluded
from the HEAD ruler only and ``"unknown"`` is never fabricated.

Reconciliation of the two non-finite rules: an *absent/unusable* activation (missing rows,
non-binary or misaligned layout) is missing evidence and yields ``None``; a physically
PRESENT stored activation that actually contains a non-finite value is corruption and fails
closed with :class:`IntegrityRefused` (it is never silently classified or excluded).  The
side is classified only from a finite pooled value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scripts.embedding_research import config
from scripts.embedding_research.db.geometry import IntegrityRefused
from scripts.embedding_research.streams.heads_current import (
    HeadSuiteCurrentError,
    resolve_current_head_suite,
)
from scripts.embedding_research.streams.records import parse_head_ids
from scripts.embedding_research.streams.store import StreamValidationError

__all__ = ["HeadSongLabel", "resolve_head_ruler_labels"]


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class HeadSongLabel:
    """The frozen semantic-head label and its SEPARATE suite provenance for ONE song.

    ``full_tuple`` is the ordered ``((head_id, side_index), ...)`` tuple over every
    canonical head of the song's CURRENT committed head suite; ``labels`` exposes the
    canonical ``HEAD_LABELS[head][side_index]`` text aligned to it and ``pooled`` the
    finite pooled class-1 means aligned to it.  The ``head_set_fingerprint``/``head_ids``/
    ``dim_by_head`` and stream/mask ref+digest fields are the head-suite identity retained
    as provenance only — they are never used as the ruler label.
    """

    song_id: str
    backbone: str
    full_tuple: tuple[tuple[str, int], ...]
    labels: tuple[str, ...]
    pooled: tuple[float, ...]
    searchable_rows: int
    head_set_fingerprint: str
    head_ids: str
    dim_by_head: str
    stream_ref: str
    stream_digest: str
    mask_ref: str
    mask_digest: str
    present: bool

    def __post_init__(self) -> None:
        _require_text(self.song_id, "song_id")
        _require_text(self.backbone, "backbone")
        full_tuple: list[tuple[str, int]] = []
        for entry in self.full_tuple:
            head, side = entry
            head = _require_text(head, "head")
            if isinstance(side, bool) or not isinstance(side, int) or side not in (0, 1):
                raise ValueError("side must be the integer 0 or 1")
            full_tuple.append((head, side))
        if not full_tuple:
            raise ValueError("full_tuple must contain at least one head")
        labels = tuple(_require_text(label, "label") for label in self.labels)
        pooled = tuple(float(value) for value in self.pooled)
        if len(labels) != len(full_tuple) or len(pooled) != len(full_tuple):
            raise ValueError("full_tuple, labels, and pooled must be aligned")
        if not all(np.isfinite(value) for value in pooled):
            raise ValueError("pooled values must be finite")
        if isinstance(self.searchable_rows, bool) or not isinstance(self.searchable_rows, int):
            raise ValueError("searchable_rows must be a positive integer")
        if self.searchable_rows < 1:
            raise ValueError("searchable_rows must be a positive integer")
        for name in (
            "head_set_fingerprint",
            "head_ids",
            "dim_by_head",
            "stream_ref",
            "stream_digest",
            "mask_ref",
            "mask_digest",
        ):
            _require_text(getattr(self, name), name)
        if not isinstance(self.present, bool):
            raise ValueError("present must be boolean")
        object.__setattr__(self, "full_tuple", tuple(full_tuple))
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "pooled", pooled)


def resolve_head_ruler_labels(
    *,
    head_store: Any,
    stream_store: Any,
    song_id: str,
    backbone: str,
) -> HeadSongLabel | None:
    """Resolve the frozen semantic-head ruler label for ONE ``(song_id, backbone)``.

    Read-only, CPU-only over the committed artifacts.  Every missing/absent/unusable piece
    of evidence yields ``None`` (a per-song exclusion from the HEAD ruler only); a present
    non-finite stored activation fails closed with :class:`IntegrityRefused`.
    """
    _require_text(song_id, "song_id")
    _require_text(backbone, "backbone")
    root = Path(head_store.output_root)
    try:
        selection = resolve_current_head_suite(root, song_id, backbone)
    except HeadSuiteCurrentError:
        return None
    try:
        observation = stream_store.load_committed_observation(song_id, backbone)
    except StreamValidationError:
        return None
    identity = getattr(observation, "identity", None)
    mask = getattr(observation, "mask", None)
    if identity is None or mask is None:
        return None
    mask_array = np.asarray(mask)
    if mask_array.ndim != 1 or mask_array.dtype not in (np.dtype("uint8"), np.dtype("int8")):
        return None
    idx = np.flatnonzero(mask_array == 1)
    if idx.size == 0:
        return None
    record = selection.record
    head_ids = parse_head_ids(record.head_ids)
    if not head_ids:
        return None
    artifact_ref = getattr(record, "artifact_ref", None)
    if not isinstance(artifact_ref, str) or not artifact_ref:
        return None
    try:
        payload = np.load(root / artifact_ref, allow_pickle=False)
    except (OSError, ValueError, TypeError):
        return None

    pooled: list[float] = []
    sides: list[tuple[str, int]] = []
    for head in head_ids:
        canonical = config.HEAD_LABELS.get(head)
        if canonical is None or head not in payload.files:
            return None
        arr = payload[head]
        if not hasattr(arr, "ndim") or arr.ndim != 2 or int(arr.shape[1]) != 2:
            return None
        if int(arr.shape[0]) != int(mask_array.shape[0]):
            return None
        rows = np.asarray(arr, dtype=np.float32)[idx]
        if not np.isfinite(rows).all():
            raise IntegrityRefused(
                f"INTEGRITY_REFUSED: head ruler: present non-finite activation for "
                f"song {song_id!r} head {head!r}; refusing to classify"
            )
        pooled_value = float(rows.mean(axis=0)[1])
        if not np.isfinite(pooled_value):
            raise IntegrityRefused(
                f"INTEGRITY_REFUSED: head ruler: non-finite pooled value for "
                f"song {song_id!r} head {head!r}; refusing to classify"
            )
        pooled.append(pooled_value)
        sides.append((head, 1 if pooled_value >= 0.5 else 0))

    return HeadSongLabel(
        song_id=song_id,
        backbone=backbone,
        full_tuple=tuple(sides),
        labels=tuple(config.HEAD_LABELS[head][side] for head, side in sides),
        pooled=tuple(pooled),
        searchable_rows=int(idx.size),
        head_set_fingerprint=str(getattr(selection.marker, "head_set_fingerprint", "")),
        head_ids=str(record.head_ids),
        dim_by_head=str(record.dim_by_head),
        stream_ref=str(identity.stream_ref),
        stream_digest=str(identity.stream_digest),
        mask_ref=str(identity.mask_ref),
        mask_digest=str(identity.mask_digest),
        present=True,
    )
