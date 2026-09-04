"""Disposable keyset-addressed search views (Plan D, Phase 1 — identity + materialization).

Implements DD R10 + the shared ledger ``SearchViewRecord`` contract (Plan A P2-S4, Plan D
implementer) and this plan's P1-S1..P1-S4:

* :class:`SearchViewKey` — the immutable, canonical, finite keyset.  Its identity inputs are
  exactly the DD's disposable-view dimensions: corpus ``search_view_hash`` (reused verbatim
  from :mod:`catalog_identity` — never reimplemented), ``run_id``, the sorted ``config_ids``,
  sorted ``song_ids``, the ``query_keyset`` (song-level and segment-level medoid addressing),
  the exact ``scoring_software_versions = (application_version, numpy_version,
  sklearn_version_or_null)``, the matrix ``shape``/``dtype``, and ``scoring_semantics_version``.
  ``backbone`` is an ADDITIONAL hashed key dimension beyond that DD minimal list (the documented,
  QA-conformed P1-S1 extension) — it is an explicit member of the canonical payload that is hashed,
  so a reader reconstructing the keyset must include it.
  Deterministic canonical serialization → ``keyset_hash`` (sha256).
* :class:`materialize_search_view(...)` — gathers medoid vectors ONLY by
  ``(song_id, backbone, medoid_source_patch_idx)`` through ``StreamStore.batch_gather``.
  Medoid addresses come exclusively from ``seg_meta.medoid_source_patch_idx`` rows of the
  catalog (never reconstructed from ranges, never a copied threshold-vector cache, never
  path-derived).  The gathered payload (keys + float32 vectors) is written to a disposable,
  keyset-addressed directory under the stream store's output root — a ``views/`` area
  distinct from the archival ``cache/`` flat/binned dirs, and clearly the target of a later
  ``cleanup --scope views`` pass (Plan E).
* :func:`record_search_view` — records a canonical root-relative view reference plus its
  keyset/content hashes into the EXISTING ``run_provenance.view_refs`` text column (the same
  table Plan B created / Plan C used — never a new table).  Views are regenerated for every
  analysis run; the mere existence of a view file never authorizes reuse.  Retained-run
  references are preserved untouched.
* :func:`validate_search_view_keyset` — exact logical-identity validation.  It recomputes the
  keyset a fresh materialization would produce today and rejects reuse when the corpus
  ``search_view_hash``, config set, stream fingerprints (via the corpus hash), or scoring
  software versions differ from what the view records.

Deliberate omissions (DD is explicit these are intentional): no ``view_manifest`` table, no
second catalog-state registry, no new DuckDB ``CREATE INDEX``, no ``PRIMARY KEY``/``UNIQUE``,
no ANN / DuckDB VSS persistence.  v1 is exact CPU gathering; the ANN boundary is only an
interface seam.  Nothing here wires the CLI (Plan E owns ``run.py`` phase dispatch) and
``analyze_metrics`` is NOT migrated (that is Plan E).  Timestamps are INTEGER milliseconds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research import cache_identity
from scripts.embedding_research.catalog import (
    configs_by_backbone,
    segments_by_config_song,
)
from scripts.embedding_research.catalog_identity import search_view_hash
from scripts.embedding_research.db import provenance as _prov
from scripts.embedding_research.db import segmentation as _seg
from scripts.embedding_research.streams.records import now_ms

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from scripts.embedding_research.streams.store import StreamStore

__all__ = [
    "APPLICATION_VERSION",
    "VIEW_DIR_NAME",
    "VIEW_PHASE",
    "AnalysisCorpus",
    "QueryKeyset",
    "SearchViewError",
    "SearchViewKey",
    "SearchViewRecord",
    "SearchViewValidationError",
    "StaleSearchViewError",
    "keyset_hash",
    "materialize_search_view",
    "record_search_view",
    "scoring_software_versions",
    "validate_search_view_keyset",
]

#: Provenance ``phase`` label an analysis run that produces search views records.
VIEW_PHASE = "analyze"
#: Sub-directory (under the stream store's output root) holding disposable views.  Kept
#: distinct from the archival ``cache/`` flat/binned directories on purpose (R14 classification
#: seam for the later ``cleanup --scope views`` pass).
VIEW_DIR_NAME = "views"

#: Application (research-app) version that feeds the scoring-software identity triple.  Bump
#: together with :data:`cache_identity.SCORING_SEMANTICS_VERSION` when the research
#: application's behaviour affecting scoring changes.  The full triple recorded per view is
#: ``(APPLICATION_VERSION, numpy_version, sklearn_version_or_null)``.
APPLICATION_VERSION = "1"

#: Row-key canonical separator inside ``view_refs`` / on-disk key serialization.
_ROW_SEP = "|"
#: view_refs line separator.
_VIEWREF_SEP = "|"

#: File names inside each disposable view directory.
_VECTORS_FILENAME = "vectors.npy"
_KEYS_FILENAME = "keys.json"


# ── Exceptions ────────────────────────────────────────────────────────────────


class SearchViewError(RuntimeError):
    """Base error for the disposable search-view materialization path."""


class SearchViewValidationError(SearchViewError):
    """A materialization/keyset input violates an application identity or validation rule."""


class StaleSearchViewError(SearchViewError):
    """A recorded view's keyset no longer matches a fresh materialization of the same corpus.

    Raised by :func:`validate_search_view_keyset` when the current corpus ``search_view_hash``,
    config set, stream fingerprints (via the corpus hash), or scoring software versions differ
    from what the view recorded — the exact logical-identity gate that governs reuse (a view is
    NEVER reusable on the mere existence of its file).
    """


# ── Corpus / query-role descriptors ───────────────────────────────────────────


@dataclass(frozen=True)
class AnalysisCorpus:
    """The in-scope corpus description for one disposable search view (single backbone).

    A view is single-backbone (DD keeps EffNet and MusicNN experiments separate; a gathered
    float32 matrix has ONE dimension ``D``), so ``backbone`` plus the sorted ``song_ids`` pin
    the corpus.  ``config_ids`` is the config surface to gather: empty means "every canonical
    (non-aliased) ``seg_config`` present in the catalog for ``backbone``"; otherwise the given
    sorted config ids are verified to belong to ``backbone``.
    """

    backbone: str
    song_ids: tuple[str, ...]
    config_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise SearchViewValidationError("backbone must be non-empty text")
        object.__setattr__(self, "song_ids", tuple(sorted(self.song_ids)))
        for song in self.song_ids:
            if not isinstance(song, str) or not song.strip():
                raise SearchViewValidationError("song_ids must contain only non-empty text")
        cfg = tuple(sorted(int(c) for c in self.config_ids))
        for config_id in cfg:
            if isinstance(config_id, bool):
                raise SearchViewValidationError("config_ids must be integers, not bools")
        object.__setattr__(self, "config_ids", cfg)


@dataclass(frozen=True)
class QueryKeyset:
    """Which gathered rows act as queries (vs candidates) for one disposable view.

    Supports both addressing modes the downstream phases (2 and 3) consume:

    * **song-level** — ``query_song_ids``: every segment row belonging to those songs is a
      query row (medoid-to-medoid by song);
    * **segment-level** — ``query_segments``: explicit ``(config_id, song_id, seg_id)`` rows
      are query rows.

    Either (or neither — a candidate-only gather) may be set; both are canonicalized sorted.
    The role spec feeds the keyset hash, so a different query split is a different view.
    """

    query_song_ids: tuple[str, ...] = ()
    query_segments: tuple[tuple[int, str, int], ...] = ()

    def __post_init__(self) -> None:
        songs = tuple(sorted(self.query_song_ids))
        for s in songs:
            if not isinstance(s, str) or not s.strip():
                raise SearchViewValidationError("query_song_ids must be non-empty text")
        object.__setattr__(self, "query_song_ids", songs)
        segs = tuple(sorted(self.query_segments))
        for entry in segs:
            if len(entry) != 3:
                raise SearchViewValidationError("query_segments entries must be (config_id, song_id, seg_id)")
            cfg, song, seg = entry
            if isinstance(cfg, bool) or isinstance(seg, bool):
                raise SearchViewValidationError("query_segment config/seg ids must be ints, not bools")
            if not isinstance(song, str) or not song.strip():
                raise SearchViewValidationError("query_segment song_id must be non-empty text")
        object.__setattr__(self, "query_segments", segs)

    def canonical(self) -> list[str]:
        """Deterministic role lines that feed the keyset hash (sorted, order-fixed)."""
        lines = [f"query_song={song}" for song in self.query_song_ids]
        lines.extend(f"query_seg={cfg}{_ROW_SEP}{song}{_ROW_SEP}{seg}" for (cfg, song, seg) in self.query_segments)
        return sorted(lines)


# ── Software-version detection ─────────────────────────────────────────────────


def scoring_software_versions() -> tuple[str, str, str | None]:
    """Exact scoring software-version triple ``(application, numpy, sklearn_or_null)``.

    Reads the installed numpy / scikit-learn versions at call time so a dependency bump
    changes the recorded identity and invalidates stale views.  scikit-learn may be absent on
    a CPU-only research install → recorded as ``None``.
    """
    import numpy as _np

    sklearn_version: str | None = None
    try:  # pragma: no cover - environment dependent
        import sklearn as _sklearn  # type: ignore[import-not-found]

        sklearn_version = getattr(_sklearn, "__version__", None)
    except Exception:  # pragma: no cover - sklearn optional
        sklearn_version = None
    return (APPLICATION_VERSION, str(_np.__version__), sklearn_version)


# ── Canonical serialization helpers ───────────────────────────────────────────


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    """Deterministic compact JSON (sorted keys, no spaces) — the project's canonical encoder."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ── Keyset / record dataclasses ───────────────────────────────────────────────


@dataclass(frozen=True)
class SearchViewKey:
    """The canonical keyset identity of one disposable search view.

    Every identity dimension of DD R10 is present: corpus ``search_view_hash`` (from
    :func:`catalog_identity.search_view_hash`, reused verbatim), ``run_id``, sorted
    ``config_ids``, sorted ``song_ids``, the ``query_keyset``, the exact scoring software
    triple, the gathered matrix ``shape``/``dtype``, and ``scoring_semantics_version``.
    ``backbone`` is also a hashed key dimension (the documented, QA-conformed P1-S1 extension
    beyond the DD minimal list — the matrix is single-backbone and backbone is an explicit member
    of ``canonical_payload`` that is hashed).  ``keyset_hash`` is the sha256 of the canonical
    serialization.
    """

    backbone: str
    search_view_hash: str
    run_id: str
    config_ids: tuple[int, ...]
    song_ids: tuple[str, ...]
    query_keyset: QueryKeyset
    scoring_software_versions: tuple[str, str, str | None]
    matrix_shape: tuple[int, ...]
    dtype: str
    scoring_semantics_version: int = cache_identity.SCORING_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise SearchViewValidationError("backbone must be non-empty text")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise SearchViewValidationError("run_id must be non-empty text")
        if not isinstance(self.search_view_hash, str) or len(self.search_view_hash) != 64:
            raise SearchViewValidationError("search_view_hash must be a 64-hex sha256 string")
        if not isinstance(self.scoring_semantics_version, int) or isinstance(self.scoring_semantics_version, bool):
            raise SearchViewValidationError("scoring_semantics_version must be an integer")
        if len(self.scoring_software_versions) != 3:
            raise SearchViewValidationError("scoring_software_versions must be a 3-tuple")
        if not isinstance(self.scoring_software_versions[0], str):
            raise SearchViewValidationError("application_version must be text")
        if not isinstance(self.scoring_software_versions[1], str):
            raise SearchViewValidationError("numpy_version must be text")
        if self.scoring_software_versions[2] is not None and not isinstance(self.scoring_software_versions[2], str):
            raise SearchViewValidationError("sklearn_version must be text or None")

    def canonical_payload(self) -> dict:
        """Order-fixed canonical payload dict (deterministic JSON serialization)."""
        query_lines = self.query_keyset.canonical()
        return {
            "backbone": self.backbone,
            "search_view_hash": self.search_view_hash,
            "run_id": self.run_id,
            "config_ids": [int(c) for c in self.config_ids],
            "song_ids": [str(s) for s in self.song_ids],
            "query_keyset": query_lines,
            "scoring_software_versions": [str(v) if v is not None else None for v in self.scoring_software_versions],
            "matrix_shape": [int(dim) for dim in self.matrix_shape],
            "dtype": self.dtype,
            "scoring_semantics_version": int(self.scoring_semantics_version),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.canonical_payload())

    @property
    def keyset_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def keyset_hash(key: SearchViewKey) -> str:
    """sha256 keyset identity of a :class:`SearchViewKey`."""
    return key.keyset_hash


#: A single gathered row address: ``(config_id, song_id, seg_id, medoid_source_patch_idx)``.
MedoidAddress = tuple[int, str, int, int]


@dataclass(frozen=True)
class SearchViewRecord:
    """Result of :func:`materialize_search_view`: a disposable keyset-addressed view.

    Holds the keyset (:class:`SearchViewKey`) + the derived ``keyset_hash``, the sha256
    ``content_hash`` of the full gathered payload (keys + float32 vectors), the root-relative
    ``view_ref`` (a ``views/...`` directory reference), the ordered gathered ``row_addresses``
    (one per vector row, giving song IDs + medoid row addresses per the ledger contract), and
    build timing.  The vectors themselves live on disk at ``view_ref`` (never on the record —
    Phase 2's scorer loads them); this record is the in-memory metadata/hash anchor.
    """

    key: SearchViewKey
    keyset_hash: str
    content_hash: str
    view_ref: str
    row_addresses: tuple[MedoidAddress, ...]
    created_at: int = 0

    @property
    def backbone(self) -> str:
        return self.key.backbone

    @property
    def run_id(self) -> str:
        return self.key.run_id

    @property
    def song_ids(self) -> tuple[str, ...]:
        return self.key.song_ids

    @property
    def matrix_shape(self) -> tuple[int, ...]:
        return self.key.matrix_shape


# ── Catalog / gather helpers ──────────────────────────────────────────────────


def _resolve_config_ids(catalog, corpus: AnalysisCorpus) -> tuple[int, ...]:
    """The sorted config surface for *corpus* (explicit, or every canonical config of backbone)."""
    if corpus.config_ids:
        ids = list(corpus.config_ids)
        for config_id in ids:
            cfg_row = catalog.execute(
                f"SELECT backbone FROM {_seg.SEG_CONFIG_TABLE} WHERE config_id = ? LIMIT 1",
                [int(config_id)],
            ).fetchone()
            if cfg_row is None:
                raise SearchViewValidationError(f"config_id={config_id} (requested by corpus) has no seg_config row")
            if str(cfg_row[0]) != corpus.backbone:
                raise SearchViewValidationError(
                    f"config_id={config_id} belongs to backbone {cfg_row[0]!r}, not corpus "
                    f"backbone {corpus.backbone!r} — a view is single-backbone"
                )
        return tuple(sorted({int(c) for c in ids}))
    configs = configs_by_backbone(catalog, corpus.backbone)
    canonical = sorted(c.config_id for c in configs if c.alias_of_config_id is None)
    return tuple(canonical)


def _collect_rows(catalog, corpus: AnalysisCorpus, config_ids: Sequence[int]) -> tuple[MedoidAddress, ...]:
    """All observed medoid row addresses for *corpus* across *config_ids*, canonical order.

    Order is ``(config_id, song_id, seg_id)`` ascending.  A song with no ``seg_meta`` row under
    a config (e.g. no ready stream for the backbone) contributes nothing.  Medoids come only
    from ``seg_meta.medoid_source_patch_idx`` — never from ranges, threshold caches, or paths.
    """
    rows = [
        (int(config_id), song_id, int(meta.seg_id), int(meta.medoid_source_patch_idx))
        for config_id in config_ids
        for song_id in corpus.song_ids
        for meta in segments_by_config_song(catalog, int(config_id), song_id)
    ]
    return tuple(sorted(rows))


def _gather_vectors(stream_store, backbone: str, rows: Sequence[MedoidAddress]) -> np.ndarray:
    """Gather the observed medoid float32 rows through ``StreamStore.batch_gather``.

    One ``batch_gather`` call per song (index order aligned to the sorted row list) so the
    returned matrix row ``i`` corresponds exactly to ``rows[i]``.  Only ``ready`` streams may
    be gathered (enforced inside ``batch_gather``).  Duplicate source indices across configs are
    permitted (the same observed patch may be the medoid of two different configs' segments);
    each gathered row is exact.
    """
    by_song: dict[str, list[tuple[int, int]]] = {}
    for i, (_cfg, song, _segid, medoid_idx) in enumerate(rows):
        by_song.setdefault(song, []).append((i, int(medoid_idx)))
    matrix = np.empty((len(rows), 0), dtype=np.float32)
    placed = 0
    for song in sorted(by_song):  # deterministic gather order (order is immaterial to content)
        positions = [pos for pos, _ in by_song[song]]
        indices = [idx for _, idx in by_song[song]]
        gathered = stream_store.batch_gather(song, backbone, indices)  # float32[N,D]
        if placed == 0:
            matrix = np.empty((len(rows), gathered.shape[1]), dtype=np.float32)
        for pos, vec in zip(positions, gathered, strict=True):
            matrix[pos] = vec
        placed += len(positions)
    return matrix


def _content_hash(
    key: SearchViewKey,
    row_addresses: Sequence[MedoidAddress],
    vectors: np.ndarray,
) -> str:
    """sha256 of the canonical gathered payload (keyset + row addresses + float32 bytes).

    Deterministic across identical content regardless of the on-disk byte layout of the view
    file, so the content hash is the payload's semantic fingerprint — validated independently
    of file existence.  Vectors are canonicalized to little-endian float32 raw bytes.
    """
    parts: list[bytes] = [key.canonical_bytes(), b"\n"]
    parts.append("\n".join(_ROW_SEP.join(str(part) for part in addr) for addr in row_addresses).encode("utf-8"))
    parts.append(b"\nEND_VECTORS\n")
    parts.append(np.ascontiguousarray(vectors, dtype="<f4").tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _write_payload(view_dir: Path, key: SearchViewKey, rows: Sequence[MedoidAddress], vectors: np.ndarray) -> None:
    """Write the disposable view payload (keys + float32 vectors) under *view_dir*."""
    view_dir.mkdir(parents=True, exist_ok=True)
    np.save(view_dir / _VECTORS_FILENAME, vectors, allow_pickle=False)
    meta = {
        "keyset": key.canonical_payload(),
        "keyset_hash": key.keyset_hash,
        "rows": [[int(c), s, int(seg), int(m)] for (c, s, seg, m) in rows],
    }
    (view_dir / _KEYS_FILENAME).write_bytes(_canonical_json(meta))


# ── Provenance recording ──────────────────────────────────────────────────────


def _viewref_line(record: SearchViewRecord) -> str:
    return _VIEWREF_SEP.join((record.keyset_hash, record.content_hash, record.view_ref))


def record_search_view(catalog, record: SearchViewRecord, *, run_id: str | None = None) -> None:
    """Record the view's keyset/content hashes + root-relative ref in ``run_provenance.view_refs``.

    Extends Plan B's existing ``run_provenance`` table usage (never a new table).  Anchored to
    ``run_id`` (defaulting to the record's own run), it appends one canonical line
    ``keyset_hash|content_hash|view_ref`` to that run's ``phase='analyze'`` row ``view_refs``
    text, deduplicated by keyset hash and preserving any existing references on the row.  Rows
    of every OTHER run — including ``retained`` runs whose refs protect views from view GC —
    are left untouched.  If no ``phase='analyze'`` row exists for the run yet, creates one
    (mirroring Plan C's ``_record_catalog_run`` pattern) with ``retained=False`` so later view
    cleanup may reclaim it.  Timestamps are integer milliseconds.
    """
    anchor = run_id if run_id is not None else record.run_id
    if not isinstance(anchor, str) or not anchor.strip():
        raise SearchViewValidationError("run_id must be non-empty text")
    columns = _prov.run_provenance_columns
    col_csv = ", ".join(columns)
    now = now_ms()
    existing = catalog.execute(
        f"SELECT {col_csv} FROM {_prov.RUN_PROVENANCE_TABLE} WHERE run_id = ? AND phase = ?",
        [anchor, VIEW_PHASE],
    ).fetchall()
    if not existing:
        _prov.write_run_provenance(
            catalog,
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
    catalog.execute(
        f"UPDATE {_prov.RUN_PROVENANCE_TABLE} SET view_refs = ? WHERE run_id = ? AND phase = ?",
        [merged, anchor, VIEW_PHASE],
    )


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


# ── Public materialization + validation ───────────────────────────────────────


def _materialize_view(
    stream_store,
    catalog,
    corpus: AnalysisCorpus,
    *,
    run_id: str,
    query_keyset: QueryKeyset,
    software_versions: tuple[str, str, str | None] | None,
) -> SearchViewRecord:
    """Pure (no provenance side effect) gather + hash + write.  Used by the public entry point."""
    config_ids = _resolve_config_ids(catalog, corpus)
    rows = _collect_rows(catalog, corpus, config_ids)
    if not rows:
        raise SearchViewError(
            f"no observed medoid rows to gather for corpus backbone={corpus.backbone!r} "
            f"configs={config_ids} songs={corpus.song_ids} — nothing to materialize"
        )
    vectors = _gather_vectors(stream_store, corpus.backbone, rows)
    if vectors.shape[0] != len(rows):
        raise SearchViewError("gathered row count does not match collected medoid addresses")
    matrix_shape = (int(vectors.shape[0]), int(vectors.shape[1]))
    versions = software_versions if software_versions is not None else scoring_software_versions()
    corpus_hash = search_view_hash(catalog)
    key = SearchViewKey(
        backbone=corpus.backbone,
        search_view_hash=corpus_hash,
        run_id=run_id,
        config_ids=config_ids,
        song_ids=corpus.song_ids,
        query_keyset=query_keyset,
        scoring_software_versions=versions,
        matrix_shape=matrix_shape,
        dtype=vectors.dtype.name,
        scoring_semantics_version=cache_identity.SCORING_SEMANTICS_VERSION,
    )
    content = _content_hash(key, rows, vectors)
    ref = str(PurePosixPath(VIEW_DIR_NAME) / key.keyset_hash)
    write_root = stream_store.output_root / PurePosixPath(ref)
    _write_payload(write_root, key, rows, vectors)
    return SearchViewRecord(
        key=key,
        keyset_hash=key.keyset_hash,
        content_hash=content,
        view_ref=ref,
        row_addresses=rows,
        created_at=now_ms(),
    )


def materialize_search_view(
    stream_store: StreamStore,
    catalog,
    corpus: AnalysisCorpus,
    run_id: str,
    *,
    query_keyset: QueryKeyset | None = None,
    working_memory: int,
    record_provenance: bool = True,
    software_versions: tuple[str, str, str | None] | None = None,
) -> SearchViewRecord:
    """Gather + store one disposable search view for *corpus* and record it for *run_id*.

    * ``stream_store`` — the ``StreamStore`` bound to the frozen streams (its ``output_root``
      hosts the disposable ``views/`` area).  Medoids are gathered through ``batch_gather``
      ONLY by catalog ``medoid_source_patch_idx``.
    * ``catalog`` — the DuckDB connection (``research.duckdb``) holding ``seg_config`` /
      ``seg_meta`` / ``seg_membership`` + the stream registry.
    * ``corpus`` — single-backbone :class:`AnalysisCorpus` (sorted song ids + config surface).
    * ``run_id`` — the analysis run anchoring this view's provenance.
    * ``query_keyset`` — song-level and/or segment-level query role spec (part of identity).
    * ``working_memory`` — explicit bounded-memory budget (bytes) accepted and validated here;
      Phase 2's scorer turns it into query/candidate chunk budgets.  It is a build hint, not a
      keyset identity dimension.
    * ``software_versions`` — optional override of the recorded scoring software triple
      (defaults to the runtime-detected versions); enables deterministic/forced-version tests.
    * ``record_provenance`` — when True (default) the materialized view is recorded into
      ``run_provenance.view_refs``.

    The view file is ALWAYS regenerated (gathered + rewritten) — the existence of a previous
    view file never authorizes reuse or a skip.  Returns the :class:`SearchViewRecord`.
    """
    if isinstance(working_memory, bool) or not isinstance(working_memory, int) or working_memory <= 0:
        raise SearchViewValidationError("working_memory must be a positive integer byte budget")
    if query_keyset is None:
        query_keyset = QueryKeyset()
    record = _materialize_view(
        stream_store,
        catalog,
        corpus,
        run_id=run_id,
        query_keyset=query_keyset,
        software_versions=software_versions,
    )
    if record_provenance:
        record_search_view(catalog, record, run_id=run_id)
    return record


def validate_search_view_keyset(catalog, record: SearchViewRecord) -> None:
    """Exact logical-identity validation of a recorded view against today's catalog state.

    Recomputes the keyset a fresh materialization of the same corpus would produce and rejects
    reuse — raising :class:`StaleSearchViewError` — when ANY of these differ from the view's
    recorded keyset: the corpus ``search_view_hash`` (covers stale corpus/stream fingerprints),
    the config set, or the scoring software versions.  A view is never valid on the existence
    of its file alone; logical identity governs reuse (S3/S4).  Raises nothing when fresh.
    """
    corpus = AnalysisCorpus(
        backbone=record.backbone,
        song_ids=record.song_ids,
        config_ids=record.key.config_ids,
    )
    config_ids = _resolve_config_ids(catalog, corpus)
    _collect_rows(catalog, corpus, config_ids)
    # Reconstruct matrix shape from the recorded key (vectors live on disk; a stale stream is
    # caught through the corpus search_view_hash without re-gathering).
    matrix_shape = tuple(int(dim) for dim in record.key.matrix_shape)
    fresh_key = SearchViewKey(
        backbone=record.backbone,
        search_view_hash=search_view_hash(catalog),
        run_id=record.run_id,
        config_ids=config_ids,
        song_ids=corpus.song_ids,
        query_keyset=record.key.query_keyset,
        scoring_software_versions=scoring_software_versions(),
        matrix_shape=matrix_shape,
        dtype=record.key.dtype,
        scoring_semantics_version=cache_identity.SCORING_SEMANTICS_VERSION,
    )
    if fresh_key.keyset_hash == record.keyset_hash:
        return
    old_payload = record.key.canonical_payload()
    new_payload = fresh_key.canonical_payload()
    changed = [
        name for name in sorted(set(old_payload) | set(new_payload)) if old_payload.get(name) != new_payload.get(name)
    ]
    raise StaleSearchViewError(
        f"search-view keyset is stale: recorded keyset_hash={record.keyset_hash[:12]}… differs "
        f"from a fresh materialization ({fresh_key.keyset_hash[:12]}…).  Changed dimensions: "
        f"{changed or 'unknown'}.  Logical identity governs reuse — the view must be regenerated."
    )
