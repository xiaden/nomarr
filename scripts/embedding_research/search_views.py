"""Disposable catalog-first search views (Plan D, P1-S2 — no ``search_view_hash``).

Implements DD R8-R10 + the shared ledger ``SearchViewRecord`` contract over the COMPACT
durable catalog (P1-S2 rewrite of the P1-S1..P1-S2 surface, deleting the old keyset/
``search_view_hash`` identity model):

* :class:`SearchViewRecord` — the disposable result of one materialization.  ``row_addresses``
  are ordered ascending ``(config_id, song_id, seg_id, source_patch_idx)`` with
  ``source_patch_idx == seg_meta.search_medoid_source_patch_idx`` (observed medoid source
  indices only; a null-medoid segment contributes NO row and a zero-searchable song is absent).
  ``vectors`` are the exact gathered float32 rows (also written to disk), ``weights`` are the
  per-row normalized searchable weights (each row's ``seg_meta.searchable_weight``; they sum to
  1 per song).  ``keyset_hash``/``content_hash`` are the disposable keyset/content identity —
  there is NO ``search_view_hash`` member and no whole-catalog search-view identity.
* :func:`materialize_search_view(catalog, stream_store, *, song_ids, backbone, run_id,
  working_memory)` — gathers ONLY observed source medoids through ``StreamStore.batch_gather``,
  writes a disposable view payload under the stream store's ``views/`` area, and ALWAYS
  regenerates (gather + write — file existence never authorizes reuse).  It makes NO
  audio/model/ONNX/CUDA calls and is finite-only (fail-closed on non-finite gathered rows).
  Provenance recording is NOT this function's job (it has no research connection); the
  analyze caller records the view on the research connection via :func:`record_search_view`.
* :func:`record_search_view` — records one canonical ``keyset_hash|content_hash|view_ref`` line
  into the existing ``run_provenance.view_refs`` column (``phase='analyze'``,
  ``retained=False``), deduped by keyset identity, preserving retained-run references.

Deliberate omissions: no ``view_manifest``/second registry table, no ``CREATE INDEX``, no
ANN/DuckDB VSS, no copied threshold-vector caches, no ``search_view_hash``/corpus-hash identity
(the catalog's per-song ``search_leaf``/structural rows are the durable identity surface; a view
is disposable and regenerated for every run).  This is the **exact CPU** path and the only ANN
surface here is a documented **interface seam** — there is no ANN / DuckDB VSS persistence and no
live v1 index.  Timestamps are INTEGER milliseconds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research.catalog import (
    CompactSegRecord,
    compact_configs_by_backbone,
    compact_segments_by_config_song,
)
from scripts.embedding_research.db import provenance as _prov
from scripts.embedding_research.streams.records import now_ms

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from scripts.embedding_research.streams.store import StreamStore

__all__ = [
    "SCORING_SEMANTICS_VERSION",
    "VIEW_DIR_NAME",
    "VIEW_PHASE",
    "MedoidAddress",
    "SearchViewError",
    "SearchViewRecord",
    "SearchViewValidationError",
    "materialize_search_view",
    "record_search_view",
]

#: Provenance ``phase`` label an analysis run that produces search-view records.
VIEW_PHASE = "analyze"
#: Sub-directory (under the stream store's output root) holding disposable views.  Kept
#: distinct from the archival ``cache/`` flat/binned directories (R14 classification seam for
#: the later ``cleanup --scope views`` pass).
VIEW_DIR_NAME = "views"

#: Scoring-input semantics contract version (was ``cache_identity.SCORING_SEMANTICS_VERSION``;
#: defined locally because the E-owned ``cache_identity`` module (scheduled for deletion) is no
#: longer imported since P1-S2).
SCORING_SEMANTICS_VERSION = 1

#: view_refs line / row-key separator.
_VIEWREF_SEP = "|"
#: File names inside each disposable view directory.
_VECTORS_FILENAME = "vectors.npy"
_KEYS_FILENAME = "keys.json"


# ── Exceptions ────────────────────────────────────────────────────────────────


class SearchViewError(ValueError):
    """Base error for the disposable search-view materialization path.

    Subclasses :class:`ValueError` so the finite-only fail-closed guarantee surfaces as a
    ``ValueError``/``FloatingPointError`` family to callers (non-finite gathered data must not
    persist a disposable view).
    """


class SearchViewValidationError(SearchViewError):
    """A materialization input violates an application identity or validation rule."""


# ── Record ────────────────────────────────────────────────────────────────────


#: A single gathered row address: ``(config_id, song_id, seg_id, medoid_source_patch_idx)``.
MedoidAddress = tuple[int, str, int, int]


@dataclass(frozen=True)
class SearchViewRecord:
    """Result of :func:`materialize_search_view`: a disposable catalog-first view.

    ``row_addresses`` are ordered ascending ``(config_id, song_id, seg_id, source_patch_idx)``
    with ``source_patch_idx`` equal to the compact ``seg_meta.search_medoid_source_patch_idx``.
    ``vectors`` (``float32``) and ``weights`` (``float64``) are the gathered medoid rows and
    their per-row normalized searchable weights; both are finite.  ``keyset_hash`` is the
    sha256 of the canonical disposable keyset (backbone / run / configs / songs / matrix
    shape/dtype / scoring-semantics version); ``content_hash`` is the sha256 over that keyset,
    the ordered row addresses, weights, and gathered vector bytes.  ``view_ref`` is the
    root-relative ``views/<keyset_hash>`` payload reference.  There is deliberately NO
    ``search_view_hash`` member and no whole-catalog search-view identity.
    """

    backbone: str
    run_id: str
    song_ids: tuple[str, ...]
    config_ids: tuple[int, ...]
    row_addresses: tuple[MedoidAddress, ...]
    vectors: np.ndarray
    weights: np.ndarray
    keyset_hash: str
    content_hash: str
    view_ref: str
    created_at: int = 0

    @property
    def matrix_shape(self) -> tuple[int, int]:
        return (int(self.vectors.shape[0]), int(self.vectors.shape[1]))

    @property
    def n_rows(self) -> int:
        return len(self.row_addresses)


# ── Canonical serialization helpers ───────────────────────────────────────────


def _canonical_json(payload: object) -> bytes:
    """Deterministic compact JSON (sorted keys, no spaces) — the project's canonical encoder."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ── Catalog / gather helpers ──────────────────────────────────────────────────


def _catalog_con(catalog):
    """Resolve the compact-catalog connection from *catalog* (a CatalogHandle or a con)."""
    con = getattr(catalog, "con", None)
    return catalog if con is None else con


def _resolve_config_ids(catalog, backbone: str) -> tuple[int, ...]:
    """Every canonical compact ``seg_config`` row for *backbone*, sorted by ``config_id``.

    The materialization gathers the FULL backbone config surface present in the catalog (there
    is no corpus-level ``config_ids`` pin and no ``alias_of_config_id`` in the compact model).
    """
    con = _catalog_con(catalog)
    return tuple(sorted(int(c.config_id) for c in compact_configs_by_backbone(con, backbone)))


def _collect_rows(catalog, config_ids: Sequence[int], song_ids: Sequence[str]) -> tuple[MedoidAddress, ...]:
    """All observed medoid row addresses across *config_ids* and *song_ids*.

    Order is ``(config_id, song_id, seg_id)`` ascending.  Medoids come only from the compact
    ``seg_meta.search_medoid_source_patch_idx`` (never ranges / threshold caches / paths).  A
    null-medoid segment contributes no row; a song absent under the backbone contributes nothing.
    """
    con = _catalog_con(catalog)
    rows = [
        (int(config_id), song_id, int(meta.seg_id), int(meta.search_medoid_source_patch_idx))
        for config_id in config_ids
        for song_id in song_ids
        for meta in compact_segments_by_config_song(con, int(config_id), song_id)
        if meta.search_medoid_source_patch_idx is not None
    ]
    return tuple(sorted(rows))


def _gather_vectors(stream_store, backbone: str, rows: Sequence[MedoidAddress]) -> np.ndarray:
    """Gather the observed medoid float32 rows through ``StreamStore.batch_gather``.

    One ``batch_gather`` call per song (index order aligned to the sorted row list) so the
    returned matrix row ``i`` corresponds exactly to ``rows[i]``.  Duplicate source indices
    across configs are permitted (the same observed patch may be the medoid of two configs'
    segments); each gathered row is exact.
    """
    by_song: dict[str, list[tuple[int, int]]] = {}
    for i, (_cfg, song, _segid, medoid_idx) in enumerate(rows):
        by_song.setdefault(song, []).append((i, int(medoid_idx)))
    matrix = np.empty((len(rows), 0), dtype=np.float32)
    for song in sorted(by_song):  # deterministic gather order (order is immaterial to content)
        positions = [pos for pos, _ in by_song[song]]
        indices = [idx for _, idx in by_song[song]]
        gathered = stream_store.batch_gather(song, backbone, indices)  # float32[N,D]
        if matrix.shape[1] == 0:
            matrix = np.empty((len(rows), gathered.shape[1]), dtype=np.float32)
        for pos, vec in zip(positions, gathered, strict=True):
            matrix[pos] = vec
    return matrix


def _row_weights(catalog, rows: Sequence[MedoidAddress]) -> np.ndarray:
    """Per-row normalized searchable weights aligned to *rows*.

    Each row's weight is the compact ``seg_meta.searchable_weight`` of its segment (the
    segment's ``searchable_count`` normalized over the song, so weights sum to 1 per song).
    Finite-only: a row whose segment carries no finite positive weight is a validation error
    (the catalog must always carry the normalized weight for a segment with an observed medoid).

    ``rows`` are ordered ascending by ``(config_id, song_id, seg_id, ...)``, so all rows of one
    ``(config_id, song_id)`` are contiguous; the compact ``seg_meta`` rows are fetched ONCE per
    distinct ``(config_id, song_id)`` pair (matched by ``seg_id`` via an in-memory scan over the
    cached pair rows) instead of issuing one per-row query — same values, output order preserved
    bit-for-bit.
    """
    con = _catalog_con(catalog)
    weights: list[float] = []
    seg_cache: dict[tuple[int, str], tuple[CompactSegRecord, ...]] = {}
    for config_id, song, seg_id, _src in rows:
        cid = int(config_id)
        key = (cid, song)
        meta = seg_cache.get(key)
        if meta is None:
            meta = compact_segments_by_config_song(con, cid, song)
            seg_cache[key] = meta
        w = None
        for m in meta:
            if int(m.seg_id) == int(seg_id):
                w = m.searchable_weight
                break
        if w is None or not float(w) > 0.0 or not np.isfinite(float(w)):
            raise SearchViewError(
                f"segment {seg_id} (config {config_id}, song {song!r}) has no finite positive "
                f"searchable_weight — cannot build a searchable-count candidate weight"
            )
        weights.append(float(w))
    return np.asarray(weights, dtype=np.float64)


def _content_hash(
    keyset_hash: str,
    rows: Sequence[MedoidAddress],
    weights: np.ndarray,
    vectors: np.ndarray,
) -> str:
    """sha256 of the canonical gathered payload (keyset + rows + weights + float32 bytes)."""
    parts: list[bytes] = [keyset_hash.encode("utf-8"), b"\n"]
    parts.append("\n".join(_VIEWREF_SEP.join(str(part) for part in addr) for addr in rows).encode("utf-8"))
    parts.append(b"\nWEIGHTS\n")
    parts.append(np.ascontiguousarray(weights, dtype="<f8").tobytes())
    parts.append(b"\nEND_VECTORS\n")
    parts.append(np.ascontiguousarray(vectors, dtype="<f4").tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _write_payload(view_dir: Path, record: SearchViewRecord) -> None:
    """Write the disposable view payload (keys + weights + float32 vectors) under *view_dir*."""
    view_dir.mkdir(parents=True, exist_ok=True)
    np.save(view_dir / _VECTORS_FILENAME, record.vectors, allow_pickle=False)
    meta = {
        "keyset": {
            "backbone": record.backbone,
            "run_id": record.run_id,
            "config_ids": [int(c) for c in record.config_ids],
            "song_ids": [str(s) for s in record.song_ids],
            "matrix_shape": list(record.matrix_shape),
            "dtype": record.vectors.dtype.name,
            "scoring_semantics_version": int(SCORING_SEMANTICS_VERSION),
        },
        "keyset_hash": record.keyset_hash,
        "content_hash": record.content_hash,
        "rows": [[int(c), s, int(seg), int(m)] for (c, s, seg, m) in record.row_addresses],
        "weights": [float(w) for w in record.weights],
    }
    (view_dir / _KEYS_FILENAME).write_bytes(_canonical_json(meta))


# ── Public materialization ────────────────────────────────────────────────────


def materialize_search_view(
    catalog,
    stream_store: StreamStore,
    *,
    song_ids: Sequence[str],
    backbone: str,
    run_id: str,
    working_memory: int,
) -> SearchViewRecord:
    """Gather + store one disposable catalog-first search view; return a :class:`SearchViewRecord`.

    * ``catalog`` — the COMPACT catalog snapshot (the ``CatalogHandle`` from
      ``catalog_storage.open_snapshot_file``, or its ``con``) holding ``seg_config`` /
      ``seg_meta`` / ``catalog_song``.  Config-surface / medoid / weight reads go through this
      connection.
    * ``stream_store`` — the ``StreamStore`` bound to the frozen streams (its ``output_root``
      hosts the disposable ``views/`` area).  Medoids are gathered through ``batch_gather`` ONLY
      by catalog ``search_medoid_source_patch_idx``.
    * ``song_ids`` — the in-scope song set for the view (sorted canonicalized).  Rows are
      gathered only for songs that have catalog rows under *backbone*; a song with no observed
      medoid contributes nothing.
    * ``backbone`` — the single backbone the view gathers (a view is single-backbone).
    * ``run_id`` — the analysis run anchoring this view (part of the keyset identity).
    * ``working_memory`` — an explicit bounded-memory budget (bytes) accepted and validated here
      (the scorer turns it into query/candidate chunk budgets).  A build hint, not an identity
      dimension.

    The view file is ALWAYS regenerated (gathered + rewritten) — the existence of a previous
    view file never authorizes reuse or a skip.  This function makes NO audio/model/ONNX/CUDA
    calls and fails closed if a gathered row or weight is non-finite.  It does NOT record
    provenance (no research connection); the analyze caller records the returned view on the
    research connection via :func:`record_search_view`.  Returns the :class:`SearchViewRecord`.
    """
    if isinstance(working_memory, bool) or not isinstance(working_memory, int) or working_memory <= 0:
        raise SearchViewValidationError("working_memory must be a positive integer byte budget")
    if not isinstance(backbone, str) or not backbone.strip():
        raise SearchViewValidationError("backbone must be non-empty text")
    if not isinstance(run_id, str) or not run_id.strip():
        raise SearchViewValidationError("run_id must be non-empty text")
    songs = tuple(sorted(song_ids))
    for song in songs:
        if not isinstance(song, str) or not song.strip():
            raise SearchViewValidationError("song_ids must contain only non-empty text")

    config_ids = _resolve_config_ids(catalog, backbone)
    rows = _collect_rows(catalog, config_ids, songs)
    if not rows:
        raise SearchViewError(
            f"no observed medoid rows to gather for backbone={backbone!r} configs={config_ids} "
            f"songs={songs} — nothing to materialize"
        )
    vectors = _gather_vectors(stream_store, backbone, rows)
    if vectors.shape[0] != len(rows):
        raise SearchViewError("gathered row count does not match collected medoid addresses")
    if not np.all(np.isfinite(vectors)):
        raise SearchViewError("gathered medoid vectors contain non-finite values — failing closed")
    weights = _row_weights(catalog, rows)

    keyset_payload = {
        "backbone": backbone,
        "run_id": run_id,
        "config_ids": [int(c) for c in config_ids],
        "song_ids": [str(s) for s in songs],
        "matrix_shape": [int(vectors.shape[0]), int(vectors.shape[1])],
        "dtype": vectors.dtype.name,
        "scoring_semantics_version": int(SCORING_SEMANTICS_VERSION),
    }
    keyset_hash = hashlib.sha256(_canonical_json(keyset_payload)).hexdigest()
    content_hash = _content_hash(keyset_hash, rows, weights, vectors)
    ref = str(PurePosixPath(VIEW_DIR_NAME) / keyset_hash)
    record = SearchViewRecord(
        backbone=backbone,
        run_id=run_id,
        song_ids=songs,
        config_ids=config_ids,
        row_addresses=rows,
        vectors=vectors,
        weights=weights,
        keyset_hash=keyset_hash,
        content_hash=content_hash,
        view_ref=ref,
        created_at=now_ms(),
    )
    write_root = stream_store.output_root / PurePosixPath(ref)
    _write_payload(write_root, record)
    return record


# ── Provenance recording ──────────────────────────────────────────────────────


def _viewref_line(record: SearchViewRecord) -> str:
    return _VIEWREF_SEP.join((record.keyset_hash, record.content_hash, record.view_ref))


def _merge_viewref_lines(existing: str, records: Sequence[SearchViewRecord]) -> str:
    """Append canonical view-ref lines for *records*, preserving *existing* and dedup by keyset."""
    present: set[str] = set()
    out: list[str] = []
    for ln in existing.splitlines() if existing else ():
        if not ln:
            continue
        present.add(ln.split(_VIEWREF_SEP, 1)[0])
        out.append(ln)
    for record in records:
        if record.keyset_hash in present:
            continue
        out.append(_viewref_line(record))
        present.add(record.keyset_hash)
    return "\n".join(out)


def record_search_view(research_con, record: SearchViewRecord, *, run_id: str | None = None) -> None:
    """Record the view's keyset/content hashes + root-relative ref in ``run_provenance.view_refs``.

    Extends Plan B's existing ``run_provenance`` table usage on the RESEARCH connection (never
    a new table, never the compact snapshot's read-only ``run_provenance``).  Anchored to
    *run_id* (defaulting to the record's own run), it appends one canonical line
    ``keyset_hash|content_hash|view_ref`` to that run's ``phase='analyze'`` row ``view_refs``
    text, deduplicated by keyset identity and preserving any existing references.  Rows of every
    OTHER run — including ``retained`` runs whose refs protect views from view GC — are left
    untouched.  If no ``phase='analyze'`` row exists for the run yet, creates one with
    ``retained=False`` so later view cleanup may reclaim it.  Timestamps are integer milliseconds.
    """
    anchor = run_id if run_id is not None else record.run_id
    if not isinstance(anchor, str) or not anchor.strip():
        raise SearchViewValidationError("run_id must be non-empty text")
    columns = _prov.run_provenance_columns
    col_csv = ", ".join(columns)
    now = now_ms()
    existing = research_con.execute(
        f"SELECT {col_csv} FROM {_prov.RUN_PROVENANCE_TABLE} WHERE run_id = ? AND phase = ?",
        [anchor, VIEW_PHASE],
    ).fetchall()
    if not existing:
        _prov.write_run_provenance(
            research_con,
            run_id=anchor,
            phase=VIEW_PHASE,
            status="complete",
            started_at=now,
            finished_at=now,
            song_count=len(record.song_ids),
            view_refs=_viewref_line(record),
        )
        return
    existing_lines: list[str] = []
    for row in existing:
        current = dict(zip(columns, row, strict=True))
        existing_lines.extend(str(current["view_refs"] or "").splitlines())
    merged = _merge_viewref_lines("\n".join(existing_lines), [record])
    research_con.execute(
        f"UPDATE {_prov.RUN_PROVENANCE_TABLE} SET view_refs = ? WHERE run_id = ? AND phase = ?",
        [merged, anchor, VIEW_PHASE],
    )
