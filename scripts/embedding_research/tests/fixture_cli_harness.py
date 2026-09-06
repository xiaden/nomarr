"""Deterministic fixture harness for the frozen-observation corrective-pass CLI run.

Part D (``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-
fixture-verification``) P1-S1.  This module builds the tiny, fully-synthetic, fully
hand-computable corpus that later steps drive through *every* active CLI phase
(ingest/embed/infer-heads/catalog/catalog-report/analyze/head-analysis/report) and the
durability/recovery passes.  Everything here is injected/deterministic: there are no real
audio files, no real model/ONNX/CUDA/audio decoding, and no empirical retrieval claim.

The corpus is built on the exact shared committed-group fixture contract in
:mod:`scripts.embedding_research.tests.conftest` (:func:`build_compact_catalog`), so every
``(song_id, backbone)`` stream is published as a *complete committed observation group*
(immutable stream + aligned committed uint8 silence mask + commit/identity metadata) and the
compact catalog is durably published under ``catalogs/<catalog_id>/`` + ``catalogs/current.json``
exactly as the production reader seams require.

Corpus (all ``effnet`` backbone; 2-D unit vectors so every outcome is hand-computable):

* ``s1``..``s4`` — four independent 6-patch ``[3 on axis][3 at Euclid 0.5]`` streams.  They make
  the two-threshold search-alias pair (0.9 / 1.0) collapse to one class (each is a single
  structural segment under both) while 0.2 splits each into two searchable segments (a second,
  distinct search class that never unions with the alias class).
* ``sil`` — five identical patches with a committed silent RUN (mask ``0`` at indices 1,2), so
  the structural range keeps the song but the silent run contributes zero searchable mass.
* ``abs`` — one genuine absorbed excursion (a single far outlier that returns to the running
  centroid within ``OUTLIER_WINDOW``); retained structurally as a sparse absorbed exception but
  contributing zero searchable mass.
* ``hard`` — a hard split: a run of far patches exceeding ``OUTLIER_WINDOW`` that never returns,
  so the far excursion becomes an ordinary *searchable* second structural segment (weights 1/3,
  2/3 -> sum to one).
* ``z0`` — a zero-searchable song (fully silent committed mask): metadata retained in the
  catalog but excluded from searchable inputs/medoids/head pooling and from the observed
  EffNet baseline population.

The observed global-medoid baseline population (silence-aware) is ``s1``..``s4`` + ``sil`` +
``abs`` + ``hard`` (7 songs); ``z0`` contributes nothing.  Per-song observed global medoid
source indices (whole-song ``mask == 1`` population, maximal-mean-cosine / smallest-source-index
tie) are frozen here as explicit literals:

* ``s1``..``s4`` -> source 0; ``sil`` -> source 0 (all rows identical -> smallest index wins);
  ``abs`` -> source 0; ``hard`` -> source 2 (the far ``D`` cluster is self-similar).

Structural accessors on :class:`FixtureHarness` let later steps (P1-S2 call-counting sentinels +
real CLI dispatch, P1-S3 output/provenance proofs, P1-S4 verify/reindex/corruption-recovery,
P1-S5 disposable-DB deletion + reindex + rerun, P1-S6 reset --scope analysis + byte
preservation) drive the fixture without re-deriving its corpus.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

# All corpus streams are effnet (the observed global-medoid baseline is ``global_pool:effnet:medoid``).
BACKBONE = "effnet"
SONGS = ("s1", "s2", "s3", "s4", "sil", "abs", "hard", "z0")
# The observed global-medoid baseline population: every searchable (>=1 non-silent patch) song.
# ``z0`` is zero-searchable and is deliberately absent.
SEARCHABLE_SONGS = ("s1", "s2", "s3", "s4", "sil", "abs", "hard")
BASELINE_STRATEGY_KEY = "global_pool:effnet:medoid"

# Config surface: two thresholds that collapse to ONE alias search class (identical per-song
# search leaves over every corpus song) plus one DISTINCT threshold that never unions with it.
ALIAS_THRESHOLDS = (0.9, 1.0)
DISTINCT_THRESHOLDS = (0.2,)
ALL_THRESHOLDS = (*ALIAS_THRESHOLDS, *DISTINCT_THRESHOLDS)

# Frozen (golden) observed global-medoid source index per baseline song over its whole-song
# ``mask == 1`` population.  Hand-computed, explicit literals (never derived at runtime).
BASELINE_MEDOID_SOURCE: dict[str, int | None] = {
    "s1": 0,
    "s2": 0,
    "s3": 0,
    "s4": 0,
    "sil": 0,
    "abs": 0,
    "hard": 2,
    "z0": None,
}

# Synthetic per-song head inference bytes injected for the infer-heads phase (never a real
# model).  Fixed shape ``(HEAD_COUNT, DIM)``, deterministic, distinct per song.
HEAD_COUNT = 3
DIM = 2


# --------------------------------------------------------------------------- #
# Deterministic vector builders (2-D unit vectors; every distance hand-computable)
# --------------------------------------------------------------------------- #
def _unit(theta: float) -> np.ndarray:
    return np.array([math.cos(theta), math.sin(theta)], dtype=np.float32)


_AXIS = (0.0, math.pi / 2.0, math.pi, -math.pi / 2.0)


def _axis_hat(i: int) -> np.ndarray:
    return _unit(_AXIS[i % 4])


def _euclidean_offset(base: np.ndarray, toward_axis: int, dist: float) -> np.ndarray:
    """A unit vector ``dist`` (Euclidean) from *base*, rotated toward *toward_axis*."""
    theta = math.acos(1.0 - dist * dist / 2.0)
    return (base * math.cos(theta) + _axis_hat(toward_axis) * math.sin(theta)).astype(np.float32)


def _pair_stream(axis: int, dist: float) -> np.ndarray:
    """Six rows: three on *axis*, three ``dist`` away -> one segment for thresholds > ``dist``."""
    base = _axis_hat(axis)
    other = _euclidean_offset(base, axis + 1, dist)
    return np.stack([base, base, base, other, other, other])


# A single far excursion used as the absorbed-outlier point (Euclid 1.2 from axis 0).
_B_FAR = _unit(2.0 * math.asin(0.6))
# The hard-split far point (Euclid 1.4 from axis 0).
_D_FAR = _unit(2.0 * math.asin(0.7))
_A = _unit(0.0)

# Silence masks keyed by song id (missing key => all-searchable, matching the committed-group
# default in conftest.build_compact_catalog).
SILENCE_MASKS: dict[str, np.ndarray] = {
    "sil": np.array([1, 0, 0, 1, 1], dtype=np.uint8),  # silent RUN at indices 1,2
    "z0": np.zeros(3, dtype=np.uint8),  # fully silent -> zero-searchable
}


def stream_matrix(song_id: str) -> np.ndarray:
    """The deterministic committed embedding stream for *song_id* (never real embeddings)."""
    if song_id in ("s1", "s2", "s3", "s4"):
        return _pair_stream(int(song_id[1]) - 1, 0.5)
    if song_id == "sil":
        return np.stack([_A, _A, _A, _A, _A])
    if song_id == "abs":
        return np.stack([_A, _A, _B_FAR, _A, _A, _A])
    if song_id == "hard":
        return np.stack([_A, _A, _D_FAR, _D_FAR, _D_FAR, _D_FAR])
    if song_id == "z0":
        return np.stack([_A, _A, _A])
    raise KeyError(song_id)


def head_bytes(song_id: str) -> np.ndarray:
    """Injected deterministic per-song head inference bytes (fixed ``(HEAD_COUNT, DIM)``)."""
    seed = sum(ord(c) for c in song_id) + 1
    rows = []
    for h in range(HEAD_COUNT):
        theta = math.pi * (h + 1) * seed / 17.0
        rows.append(_unit(theta))
    return np.stack(rows).astype(np.float32)


def song_mask(song_id: str) -> np.ndarray:
    """The committed whole-song uint8 mask for *song_id* (all-ones when no silence)."""
    if song_id in SILENCE_MASKS:
        return SILENCE_MASKS[song_id].copy()
    return np.ones(stream_matrix(song_id).shape[0], dtype=np.uint8)


# Synthetic deterministic audio metadata (path/artist/album/title/genre) registered on the
# research DB so later run.py-driven phases can resolve songs without any real audio file.
SONG_METADATA: dict[str, dict[str, str]] = {
    song: {
        "path": f"/fixture/audio/{song}.mp3",
        "artist": "DeterministicArtist",
        "album": f"DeterministicAlbum-{song}",
        "title": f"DeterministicTitle-{song}",
        "genre": "synthetic-fixture",
    }
    for song in SONGS
}


@dataclass
class FixtureHarness:
    """Built deterministic corpus + durable compact catalog with explicit structural accessors.

    Wraps the :class:`CompactCatalogHarness` returned by the shared committed-group build, and
    adds corpus-aware accessors later steps drive.  ``con`` / ``research_con`` follow the
    DuckDB single-writer rule of the wrapped harness (one live snapshot handle).
    """

    catalog_harness: Any
    output_root: Path = field(repr=False)

    # -- passthrough to the wrapped committed-group harness ------------------ #
    @property
    def con(self):
        """The compact snapshot connection for catalog reads."""
        return self.catalog_harness.con

    @property
    def research_con(self):
        """The research DuckDB connection (committed streams/provenance live here)."""
        return self.catalog_harness.research_con

    @property
    def snapshot_path(self) -> Path:
        return self.catalog_harness.snapshot_path

    @property
    def stream_store(self):
        return self.catalog_harness.stream_store

    @property
    def mask_store(self):
        return self.catalog_harness.mask_store

    def close(self) -> None:
        self.catalog_harness.close()

    # -- corpus-aware accessors ---------------------------------------------- #
    def config_rows(self):
        """All ``seg_config`` records for the effnet backbone (one per threshold)."""
        from scripts.embedding_research import catalog as _cat

        return list(_cat.compact_configs_by_backbone(self.con, BACKBONE))

    def config_row(self, threshold: float):
        """The ``seg_config`` record whose effective threshold equals *threshold*."""
        for row in self.config_rows():
            if float(row.threshold_effective) == float(threshold):
                return row
        raise KeyError(threshold)

    def segments(self, threshold: float, song_id: str):
        """Structural segment records for *song_id* under *threshold* (duck SegMetaRecords)."""
        from scripts.embedding_research import catalog as _cat

        cid = self.config_row(threshold).config_id
        return list(_cat.compact_segments_by_config_song(self.con, cid, song_id))

    def search_classes(self):
        """The transient search-representation collapse classes for the catalog."""
        from scripts.embedding_research.catalog_identity import collapse_search_representations

        return collapse_search_representations(self.con)

    def searchable_song_ids(self) -> list[str]:
        """Songs with at least one searchable (non-silent) patch across every config."""
        return list(SEARCHABLE_SONGS)


def _register_song_metadata(research_con, song_id: str) -> None:
    meta = SONG_METADATA[song_id]
    research_con.execute(
        "INSERT OR REPLACE INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
        (
            song_id,
            meta["path"],
            meta["artist"],
            meta["album"],
            meta["title"],
            meta["genre"],
        ),
    )


def build_deterministic_fixture(
    research_con: Any,
    output_root: Any,
    *,
    run_id: str | None = None,
) -> FixtureHarness:
    """Construct the tiny deterministic corpus and return a :class:`FixtureHarness`.

    Publishes every ``(song, BACKBONE)`` stream as a complete committed observation group
    (with its committed silence mask), registers the synthetic audio metadata, and builds +
    durably publishes the compact catalog over the config surface ``{0.9, 1.0, 0.2}``.

    The committed groups and durable ``catalogs/current.json`` are exactly the artifact state
    later steps replay (reindex, verify, reset) and reuse (catalog reuse must avoid segmentation
    recomputation), so no real corpus/model/audio run is involved anywhere.
    """
    from scripts.embedding_research import catalog as _cat
    from scripts.embedding_research.tests.conftest import build_compact_catalog as _build

    # Register synthetic audio metadata (real audio never exists; metadata is fixture-injected).
    for song in SONGS:
        _register_song_metadata(research_con, song)

    streams = {(song, BACKBONE): stream_matrix(song) for song in SONGS}
    masks = {song: song_mask(song) for song in SILENCE_MASKS}
    configs = [
        _cat.SegConfigInput(
            backbone=BACKBONE,
            bin_mode="temporal_global",
            threshold_configured=th,
            threshold_effective=th,
        )
        for th in ALL_THRESHOLDS
    ]
    harness = _build(
        research_con,
        output_root,
        streams=streams,
        configs=configs,
        song_ids=list(SONGS),
        masks=masks,
        run_id=run_id,
    )
    return FixtureHarness(catalog_harness=harness, output_root=output_root)
