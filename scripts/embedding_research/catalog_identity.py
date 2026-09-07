"""Strict catalog identity: canonical serialization, per-song signatures,
manifest-only catalog fingerprint, and logical export/import verification (Plan C, P1-S6(b)).

Implements DD R9 + U1 + the identity/serialization contract over the COMPACT durable
snapshot tables (``seg_config`` / ``catalog_song`` / ``seg_meta`` / ``catalog_metadata``
via the ``catalog_storage`` column tuples):

* Canonical serialization fixes table / column / NULL / type / numeric encodings and sorts
  rows by stable keys.  Numeric thresholds reuse the Plan A canonical encoders
  (``helpers.thresholds.canonical_float`` etc.) so ``0.1`` and ``1e-1`` (the same double)
  always encode identically and never in scientific-notation form.
* A **per-song signature** is the SHA-256 of a canonical serialization of that song's
  compact catalog content — every ``catalog_song`` leaf for the song (which carries the
  frozen ``stream_digest``/``mask_digest``, structural totals, ``exact_leaf``/
  ``search_leaf`` and encoder/params ids) plus every ``seg_meta`` structural row
  (``start_idx``/``end_idx`` EXCLUSIVE report ranges, canonical sparse ``absorbed_indices``,
  ``absorbed_count``, ``searchable_count``, observed ``search_medoid_source_patch_idx``,
  normalized ``searchable_weight`` and ``structural_identity``).  Any structural/count/
  absorbed/medoid/weight/stream-digest change changes the signature.
* ``search_view_hash`` was the STRICT logical corpus identity retained on compact data until
  Plan D.  Plan D P1-S2 REMOVED it (DD L266): search views are disposable and regenerated per
  run, so corpus-state holds no durable search-view hash.  The strict-identity role is fully
  covered by ``catalog_fingerprint`` (a versioned canonical serialization of the COMPACT
  logical state) plus ``song_signature`` per-song structural leaves.
* ``catalog_fingerprint`` (R15/U1) is a SEPARATE, MANIFEST-ONLY, non-self-referential
  SHA-256 over a versioned canonical serialization of the COMPACT logical state
  (``seg_config``, ``catalog_song``, ``seg_meta``, ``catalog_metadata`` + the schema
  version) — with NO ``catalog_fingerprint`` column in any table and the value
  deliberately excluded from its own input.  It is never a DuckDB byte hash (WAL/checkpoint
  rewrites can change bytes without changing logical rows); logical identity is the oracle.
* Export/import (or any serialization round-trip) is verified by comparing canonical logical
  state / hashes over copied + reopened snapshot files, never DuckDB physical bytes.

Distinct exact-vs-search preimages: the compact producer already persists two DISTINCT
leaves per ``catalog_song`` row — ``exact_leaf`` (structural identity: boundaries, absorbed
indices, silence/searchability counts, structural fields, encoder version) and ``search_leaf``
(frozen stream identity, ordered searchable medoid source indices, normalized searchable
weights, scoring-input semantics) — per DD L240-266.  This module reads those leaves as part
of the per-song ``catalog_song`` content and re-derives its identity from the live compact
rows (so a post-build row mutation is detected).  No legacy research ``seg_membership`` /
``stream_registry`` / ``corpus_state`` table is read or written here.

Nothing here wires the CLI (Plan E owns phase boundaries); this is the pure computation
surface a report / build / CLI phase calls.  No PK/UNIQUE, no view_manifest, no second
catalog-state table is introduced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.embedding_research.catalog_storage import (
    CATALOG_METADATA_COLS,
    CATALOG_METADATA_TABLE,
    CATALOG_SONG_COLS,
    CATALOG_SONG_TABLE,
    SEG_CONFIG_COLS,
    SEG_CONFIG_TABLE,
    SEG_META_COLS,
    SEG_META_TABLE,
)
from scripts.embedding_research.helpers.thresholds import (
    PTC_STRATEGY_VERSION,
    canonical_float,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CATALOG_MANIFEST_VERSION",
    "CATALOG_SEMANTICS_VERSION",
    "CATALOG_SERIALIZATION_VERSION",
    "EVALUATION_CORPUS_SEMANTICS_VERSION",
    "CatalogIdentityContext",
    "EvaluationCorpusIdentity",
    "SearchRepresentationClass",
    "catalog_fingerprint",
    "catalog_state_payload",
    "collapse_search_representations",
    "exact_segmentation_hash",
    "resolve_evaluation_corpus",
    "search_representation_hash",
    "song_ids_digest",
    "song_signature",
    "verify_catalog_logical_identity",
]

#: Default catalog-semantics contract version (bump when segmentation / membership semantics
#: change in a way that alters logical identity).
CATALOG_SEMANTICS_VERSION: int = 1
#: Default canonical-serialization ordering/encoding contract version (bump when the ordering
#: or encoding rules change — every identity hash then changes: the "ordering-contract" axis).
CATALOG_SERIALIZATION_VERSION: int = 1
#: Default manifest format version that feeds identity hashes.
CATALOG_MANIFEST_VERSION: int = 1
#: Default segmentation algorithm/strategy version that affects identity.
CATALOG_STRATEGY_VERSION: int = PTC_STRATEGY_VERSION


@dataclass(frozen=True)
class CatalogIdentityContext:
    """Version/software context that feeds every identity hash.

    Changing any field changes ``catalog_fingerprint``.  ``software_versions`` is an ordered map of
    ``name -> version`` for software/algorithm versions that affect identity (e.g.
    application / segmentation / serialization versions); it is canonicalized sorted by name.
    """

    catalog_semantics_version: int = CATALOG_SEMANTICS_VERSION
    serialization_version: int = CATALOG_SERIALIZATION_VERSION
    manifest_version: int = CATALOG_MANIFEST_VERSION
    strategy_version: int = CATALOG_STRATEGY_VERSION
    software_versions: Mapping[str, str] = ()

    def __post_init__(self) -> None:
        for name in (
            "catalog_semantics_version",
            "serialization_version",
            "manifest_version",
            "strategy_version",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer; got {type(value).__name__}")
        object.__setattr__(self, "software_versions", dict(self.software_versions))
        for key, version in self.software_versions.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("software_versions keys must be non-empty text")
            if not isinstance(version, str):
                raise TypeError(f"software_versions[{key!r}] must be a text version; got {type(version).__name__}")

    def context_lines(self) -> list[str]:
        """Canonical, order-fixed serialization lines of this context (sorted for stability)."""
        lines = [
            f"catalog_semantics_version={int(self.catalog_semantics_version)}",
            f"serialization_version={int(self.serialization_version)}",
            f"manifest_version={int(self.manifest_version)}",
            f"strategy_version={int(self.strategy_version)}",
        ]
        lines.extend(f"software:{name}={self.software_versions[name]}" for name in sorted(self.software_versions))
        return lines


# ── Canonical value / row encoders ──────────────────────────────────────────────


def _canon_value(value: object) -> str:
    """Canonical encoding of one stored scalar (NULL / bool / int / float / text).

    Floats use the Plan A canonical encoder (shortest round-trip repr, exponent-free).  An
    absent scalar — SQL ``NULL`` OR an empty text value — canonicalizes to the single token
    ``null``: DuckDB ``EXPORT DATABASE``/``IMPORT DATABASE`` interchanges ``''`` and ``NULL``
    on nullable text columns, so treating both as absent keeps logical identity unchanged
    across a serialization / schema export-import round-trip (the DD's logical oracle, never
    a DuckDB byte hash).  Everything else is deterministic text.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        return canonical_float(value)
    if isinstance(value, str):
        return "null" if value == "" else value
    return str(value)


def _row_line(columns: Sequence[str], row: Sequence[object]) -> str:
    """Canonical single-row text in fixed column order: ``col=value|col=value``."""
    return "|".join(f"{col}={_canon_value(value)}" for col, value in zip(columns, row, strict=True))


def _fetch_rows(con, table: str, columns: Sequence[str]) -> list[dict]:
    """All rows of *table* as dicts, deterministically ordered by every column."""
    order = ", ".join(columns)
    rows = con.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}").fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


# ── Per-song signature ─────────────────────────────────────────────────────────

#: Identity-affecting ``seg_meta`` columns for a per-song signature (structural content +
#: searchable-membership evidence + observed medoid + normalized weight).  ``provenance``
#: (a run tag) is deliberately EXCLUDED so an identical logical song rebuilds the same
#: signature regardless of run id.
_SEG_SIGNATURE_COLS: tuple[str, ...] = (
    "config_id",
    "seg_id",
    "start_idx",
    "end_idx",
    "absorbed_indices",
    "absorbed_count",
    "searchable_count",
    "search_medoid_source_patch_idx",
    "searchable_weight",
    "structural_identity",
)


def song_signature(con, song_id: str) -> str:
    """Strict SHA-256 per-song signature over the song's compact catalog content.

    Pre-image lines: the song identity, every ``catalog_song`` leaf row for the song (its
    frozen stream/mask digests, patch/total-searchable counts, exact/search leaves, encoder
    version and status) and every ``seg_meta`` structural row for the song.  Lines are
    globally sorted for deterministic ordering; NULL/type/numeric encodings are fixed.  Any
    structural / count / absorbed / medoid / weight / stream-digest change changes the
    signature.
    """
    lines: list[str] = [f"song={song_id}"]
    leaf_rows = con.execute(
        f"SELECT {', '.join(CATALOG_SONG_COLS)} FROM {CATALOG_SONG_TABLE} WHERE song_id = ? ORDER BY config_id",
        [song_id],
    ).fetchall()
    lines.extend(_row_line(CATALOG_SONG_COLS, row) for row in leaf_rows)
    seg_rows = con.execute(
        f"SELECT {', '.join(_SEG_SIGNATURE_COLS)} FROM {SEG_META_TABLE} WHERE song_id = ? ORDER BY config_id, seg_id",
        [song_id],
    ).fetchall()
    lines.extend(_row_line(_SEG_SIGNATURE_COLS, row) for row in seg_rows)
    body = "\n".join(sorted(lines))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _catalog_song_ids(con) -> list[str]:
    rows = con.execute(f"SELECT DISTINCT song_id FROM {CATALOG_SONG_TABLE} ORDER BY song_id").fetchall()
    return [str(row[0]) for row in rows]


# ── Manifest-only catalog fingerprint (complete logical state, non-self-referential) ──

#: The four compact logical tables (plus the schema version) the fingerprint covers.  The
#: fingerprint serializes the COMPACT snapshot (``seg_config`` / ``catalog_song`` /
#: ``seg_meta`` / ``catalog_metadata``), never the old research-only fingerprint tables
#: referencing ``seg_membership`` / ``stream_registry`` / ``corpus_state``.  Volatile
#: ``run_provenance`` is intentionally not part of the logical-state fingerprint.
_FINGERPRINT_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SEG_CONFIG_TABLE, SEG_CONFIG_COLS),
    (CATALOG_SONG_TABLE, CATALOG_SONG_COLS),
    (SEG_META_TABLE, SEG_META_COLS),
    (CATALOG_METADATA_TABLE, CATALOG_METADATA_COLS),
)


def catalog_state_payload(con, *, schema_version: int) -> str:
    """The canonical pre-image of :func:`catalog_fingerprint` (non-self-referential).

    Serializes the COMPACT logical state: every canonicalized row of ``seg_config`` /
    ``catalog_song`` / ``seg_meta`` / ``catalog_metadata`` plus the *schema_version* marker.
    The ``catalog_fingerprint`` value is deliberately absent — it is manifest-only and lives
    in no table column, so it can never be part of its own input.
    """
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise TypeError("schema_version must be an integer")
    sections: list[str] = [f"catalog_fingerprint_schema_version={int(schema_version)}"]
    for table, columns in _FINGERPRINT_TABLES:
        rows = _fetch_rows(con, table, columns)
        if rows:
            header = f"table={table} rows={len(rows)}"
            body = "\n".join(_row_line(columns, tuple(row[col] for col in columns)) for row in rows)
            sections.append(f"{header}\n{body}")
    return "\n".join(sections)


def catalog_fingerprint(con, *, schema_version: int) -> str:
    """Manifest-only, non-self-referential SHA-256 over the complete logical state.

    ``catalog_fingerprint`` is never stored in a DB column (catalog_metadata/corpus_state
    deliberately carry no such column), so the fingerprint cannot feed its own input.  It is
    NOT a DuckDB byte hash: WAL/checkpoint rewrites can change bytes without changing logical
    rows, so logical identity is the oracle (verified via export/import comparison).
    """
    return hashlib.sha256(catalog_state_payload(con, schema_version=schema_version).encode("utf-8")).hexdigest()


# ── Config-level equivalence hashes + collapse (Plan D P1-S3) ────────────────
# DD L246-266: the compact producer stores per-(config, song) ``exact_leaf`` and
# ``search_leaf`` on ``catalog_song`` but does NOT persist config-level hashes.  Analysis
# planning recomputes, from CURRENT catalog rows on every run, the per-config
# ``search_representation_hash`` and ``exact_segmentation_hash`` and collapses equal search
# representations into :class:`SearchRepresentationClass` instances so equal scoring inputs
# execute the scorer once.  There is deliberately NO durable alias graph / alias column /
# alias file — equivalence classes are a pure read recomputed each call.
#
# * ``search_representation_hash`` (DD L263) aggregates the config's sorted per-song
#   ``search_leaf`` values plus an encoder_version and scoring-input semantics.  It
#   intentionally EXCLUDES the canonical config fields (``threshold_effective`` etc.) so two
#   distinct direct thresholds that segment the SAME frozen streams into identical searchable
#   medoid sets produce equal hashes and collapse.
# * ``exact_segmentation_hash`` (DD L258) aggregates the config's sorted per-song
#   ``exact_leaf`` values plus an encoder_version and the canonical config fields (including
#   ``threshold_effective``), so two search-collapsed configs still carry DISTINCT exact
#   hashes and remain structurally distinguishable in report/change surfaces.

#: Canonical ``seg_config`` fields entering ``exact_segmentation_hash`` (exact identity).
#: ``config_id`` (an application identity) and ``run_id`` (a provenance tag) are excluded so
#: an identical logical config rebuilds the same exact hash regardless of its row id / run.
_CONFIG_EXACT_FIELDS: tuple[str, ...] = (
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "threshold_semantics",
    "outlier_window",
    "strategy_version",
)

#: The compact ``catalog_song`` leaf columns feeding the two config-level hashes.
_EXACT_LEAF_COL = "exact_leaf"
_SEARCH_LEAF_COL = "search_leaf"


@dataclass(frozen=True)
class SearchRepresentationClass:
    """Deterministic equivalence class of compact configs keyed by ``search_representation_hash``.

    Two configs whose actual scoring inputs match (identical per-song ordered searchable
    medoid source indices + normalized weights, i.e. identical ``search_leaf`` sets under the
    same scoring-input semantics) share a ``search_representation_hash`` and collapse into ONE
    class so the scorer runs once for all of them.  ``canonical_config_id`` is the lowest
    member ``config_id`` (a deterministic canonical-selection rule); every other member is a
    sorted report alias reporting to it.  ``config_ids`` lists every member ascending
    (canonical first).  No durable alias graph is written or read.
    """

    search_representation_hash: str
    canonical_config_id: int
    config_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.config_ids, tuple) or not self.config_ids:
            raise TypeError("config_ids must be a non-empty tuple of member config ids")
        member_ids = tuple(sorted({int(c) for c in self.config_ids}))
        object.__setattr__(self, "config_ids", member_ids)
        if self.canonical_config_id != member_ids[0]:
            raise ValueError(
                "canonical_config_id must be the lowest member config_id; "
                f"got {self.canonical_config_id}, members {member_ids}"
            )

    @property
    def alias_ids(self) -> tuple[int, ...]:
        """Every non-canonical member config id, ascending (the report aliases)."""
        return tuple(c for c in self.config_ids if c != self.canonical_config_id)

    @property
    def n_configs(self) -> int:
        return len(self.config_ids)


#: Resolve a CatalogHandle / snapshot connection the way the rest of the tree does.
def _identity_con(catalog):
    con = getattr(catalog, "con", None)
    return catalog if con is None else con


def _config_row(con, config_id: int) -> dict:
    """One ``seg_config`` row as a dict, raising a clear error when absent."""
    row = con.execute(
        f"SELECT {', '.join(SEG_CONFIG_COLS)} FROM {SEG_CONFIG_TABLE} WHERE config_id = ?",
        [int(config_id)],
    ).fetchone()
    if row is None:
        raise ValueError(f"no compact seg_config row for config_id={int(config_id)}")
    return dict(zip(SEG_CONFIG_COLS, row, strict=True))


def _config_identity_encoder_version(con, config_id: int) -> str:
    """The config's recorded per-song ``encoder_version`` (constant across its songs).

    Returns ``""`` for a config with no ``catalog_song`` rows (nothing stored to read); the
    DD's encoder_version is a serialization guard, not an additional search feature, and two
    configs within one catalog always share it.
    """
    rows = con.execute(
        f"SELECT DISTINCT encoder_version FROM {CATALOG_SONG_TABLE} WHERE config_id = ?",
        [int(config_id)],
    ).fetchall()
    if not rows:
        return ""
    versions = {str(r[0]) for r in rows}
    if len(versions) > 1:
        raise ValueError(f"config_id={int(config_id)} has inconsistent per-song encoder_versions: {sorted(versions)}")
    return versions.pop()


def _config_leaf_values(con, config_id: int, leaf_column: str) -> tuple[tuple[str, str], ...]:
    """The config's per-song leaf values under *leaf_column*, bound to their song in FIXED song order.

    Reads the CURRENT compact ``catalog_song`` rows every call (recomputed from stored
    hashes; no durable alias graph/column/file is consulted).  Each ``(song_id, leaf)``
    pair keeps the leaf bound to the song that produced it; pairs are serialized in fixed
    ascending ``song_id`` order so a config's preimage is independent of physical row order
    yet sensitive to which SONGS (and song identities) the config covers — a cross-corpus /
    song-set difference changes the config hash instead of being sorted away.
    """
    if leaf_column not in (_EXACT_LEAF_COL, _SEARCH_LEAF_COL):
        raise ValueError(f"leaf_column must be {_EXACT_LEAF_COL!r} or {_SEARCH_LEAF_COL!r}")
    rows = con.execute(
        f"SELECT song_id, {leaf_column} FROM {CATALOG_SONG_TABLE} WHERE config_id = ?",
        [int(config_id)],
    ).fetchall()
    return tuple(sorted((str(song), str(leaf)) for song, leaf in rows))


def _canon_config_fields(con, config_id: int) -> str:
    """Deterministic canonical serialization of the config's exact identity fields."""
    row = _config_row(con, config_id)
    return _row_line(_CONFIG_EXACT_FIELDS, tuple(row[c] for c in _CONFIG_EXACT_FIELDS))


def search_representation_hash(catalog, config_id: int) -> str:
    """DD L263 per-config search-representation hash over the CURRENT catalog rows.

    ``SHA256(encoder_version || scoring-input semantics || per-song search leaves in fixed
    song order)``.  Each search leaf is bound to the ``song_id`` that produced it and already
    encodes the frozen stream + committed-mask digests, mask/scoring semantics, and ordered
    medoid source indices + normalized weights.  The config's canonical fields (threshold
    etc.) are deliberately EXCLUDED, so two direct thresholds that produce identical ordered
    searchable medoid+weight inputs collapse — but a cross-corpus song-set/identity difference
    or a change in the actual scoring input bytes/order/weights does NOT.  ``catalog`` is a
    compact CatalogHandle / snapshot connection (duck-typed via ``con``).
    """
    con = _identity_con(catalog)
    cfg = _config_row(con, config_id)
    semantics = str(cfg["threshold_semantics"])
    encoder = _config_identity_encoder_version(con, config_id)
    leaf_pairs = _config_leaf_values(con, config_id, _SEARCH_LEAF_COL)
    pre = "\n".join(
        [
            "search_representation_hash",
            f"encoder_version={encoder}",
            f"scoring_input_semantics={semantics}",
            f"n_songs={len(leaf_pairs)}",
            *(f"song={song}\n{leaf}" for song, leaf in leaf_pairs),
        ]
    )
    return hashlib.sha256(pre.encode("utf-8")).hexdigest()


def exact_segmentation_hash(catalog, config_id: int) -> str:
    """DD L258 per-config exact-segmentation hash over the CURRENT catalog rows.

    ``SHA256(encoder_version || canonical config fields || per-song exact leaves in fixed
    song order)``.  Unlike the search hash, it INCLUDES the canonical config fields
    (``threshold_effective`` etc.) and each exact leaf carries the full canonical structural
    evidence + stream/mask digests, so two search-collapsed configs with distinct thresholds
    still carry DISTINCT exact hashes and remain structurally distinguishable.  ``catalog`` is
    a compact CatalogHandle / snapshot connection (duck-typed via ``con``).
    """
    con = _identity_con(catalog)
    encoder = _config_identity_encoder_version(con, config_id)
    fields = _canon_config_fields(con, config_id)
    leaf_pairs = _config_leaf_values(con, config_id, _EXACT_LEAF_COL)
    pre = "\n".join(
        [
            "exact_segmentation_hash",
            f"encoder_version={encoder}",
            fields,
            f"n_songs={len(leaf_pairs)}",
            *(f"song={song}\n{leaf}" for song, leaf in leaf_pairs),
        ]
    )
    return hashlib.sha256(pre.encode("utf-8")).hexdigest()


def collapse_search_representations(catalog) -> tuple[SearchRepresentationClass, ...]:
    """Recompute the search-representation equivalence classes of *catalog* (DD L266).

    Structural differences do NOT prevent collapse when the actual scoring inputs match: each
    compact ``seg_config`` is hashed by :func:`search_representation_hash` (aggregating its
    CURRENT per-song ``search_leaf`` values + encoder_version + scoring-input semantics) and
    equal hashes form one :class:`SearchRepresentationClass`.  The class canonical config is
    the lowest member ``config_id``; members/aliases are sorted ascending.  Classes are sorted
    by canonical config id.  Recomputed from stored hashes EVERY call — there is no durable
    alias graph, alias column, or alias file.  ``catalog`` is a compact CatalogHandle / snapshot
    connection (duck-typed via ``con``).
    """
    con = _identity_con(catalog)
    rows = con.execute(f"SELECT config_id FROM {SEG_CONFIG_TABLE} ORDER BY config_id").fetchall()
    buckets: dict[str, list[int]] = {}
    for (config_id,) in rows:
        cid = int(config_id)
        buckets.setdefault(search_representation_hash(con, cid), []).append(cid)
    classes = [
        SearchRepresentationClass(
            search_representation_hash=rep_hash,
            canonical_config_id=min(members),
            config_ids=tuple(sorted(members)),
        )
        for rep_hash, members in buckets.items()
    ]
    classes.sort(key=lambda c: c.canonical_config_id)
    return tuple(classes)


# ── Evaluation-corpus identity (execution-reporting-repair Plan A, P1) ──────────
# One explicit, deterministic evaluation-corpus identity per backbone, resolved ONCE at the
# analyze/catalog boundary and threaded through every canonical segmented class pass AND the
# observed whole-song medoid baseline path.  No later/current catalog is consulted when the
# identity is derived; the eligible population is frozen in the identity at resolve time.
#
# Eligibility is exactly a catalog-requested song with a valid committed stream+mask AND at
# least one non-silent whole-song patch.  Silent-only (zero-searchable) and uncommitted songs
# are EXCLUDED with evidence (``missing_song_ids`` / ``missing_count`` / ``missing_digest``),
# never silently pooled as all-searchable.  A per-representation loss after PTC absorption is
# surfaced separately per representation (see ``common.catalog_analysis``), never by mutating
# this frozen whole-song identity.

#: Version of the evaluation-corpus identity semantics.  Bump when the eligibility rule or the
#: canonical tagged serialization changes such that an equal population yields a different hash.
EVALUATION_CORPUS_SEMANTICS_VERSION: int = 1
#: Minimum eligible songs a backbone needs before a leave-one-out evaluation (segmented pass or
#: observed baseline) is meaningful.  A sub-2 eligible corpus is ``eligible == False`` so the
#: analyze scope records a failed/incomplete outcome rather than a fabricated singleton success.
_MIN_ANALYZABLE_EVALUATION_SONGS: int = 2


@dataclass(frozen=True)
class EvaluationCorpusIdentity:
    """The backbone's single resolved evaluation-corpus identity (frozen, deterministic).

    ``song_ids`` is the canonical sorted set of ELIGIBLE catalog-requested songs (valid
    committed stream+mask AND >= 1 non-silent whole-song patch); ``count`` / ``corpus_hash``
    are the deterministic population summary over exactly that set.  ``eligible`` is whether
    the corpus is analyzable via leave-one-out (>= :data:`_MIN_ANALYZABLE_EVALUATION_SONGS`
    eligible songs); ``comparable`` is the whole-song view (== ``eligible``: a whole-song
    medoid representation never loses an eligible song — per-representation losses after PTC
    absorption are surfaced separately and set the *representation* non-comparable, not this
    shared identity).  ``missing_song_ids`` / ``missing_count`` / ``missing_digest`` carry the
    excluded-requested-song evidence (requested songs that did not meet eligibility).

    This identity is the population every segmented class and the whole-song baseline must
    reuse EXACTLY — it is never re-derived from a later catalog or a disposable view keyset.
    """

    backbone: str
    song_ids: tuple[str, ...]
    corpus_hash: str
    count: int
    eligible: bool
    comparable: bool
    missing_song_ids: tuple[str, ...]
    missing_count: int
    missing_digest: str | None
    semantics_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.backbone, str) or not self.backbone:
            raise TypeError("backbone must be non-empty text")
        if isinstance(self.semantics_version, bool) or not isinstance(self.semantics_version, int):
            raise TypeError("semantics_version must be an integer")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if isinstance(self.missing_count, bool) or not isinstance(self.missing_count, int):
            raise TypeError("missing_count must be an integer")
        if not isinstance(self.song_ids, tuple) or any(not isinstance(s, str) for s in self.song_ids):
            raise TypeError("song_ids must be a tuple of song-id strings")
        if not isinstance(self.missing_song_ids, tuple) or any(not isinstance(s, str) for s in self.missing_song_ids):
            raise TypeError("missing_song_ids must be a tuple of song-id strings")
        # Canonical population: canonical sorted song ids, never empty when eligible.
        object.__setattr__(self, "song_ids", tuple(sorted(set(self.song_ids))))
        object.__setattr__(self, "missing_song_ids", tuple(sorted(set(self.missing_song_ids))))
        if self.count != len(self.song_ids):
            raise ValueError(f"count={self.count} must equal the resolved eligible song count {len(self.song_ids)}")
        if self.missing_count != len(self.missing_song_ids):
            raise ValueError(
                f"missing_count={self.missing_count} must equal the excluded song count {len(self.missing_song_ids)}"
            )
        # A comparable population must be eligible and may not double-count a song as both eligible
        # and missing (a resolved song is either eligible or excluded, never both).
        overlap = set(self.song_ids) & set(self.missing_song_ids)
        if overlap:
            raise ValueError(f"song ids cannot be both eligible and excluded: {sorted(overlap)}")
        if self.comparable and not self.eligible:
            raise ValueError("an ineligible corpus cannot be comparable")
        if not self.eligible and self.song_ids and len(self.song_ids) >= _MIN_ANALYZABLE_EVALUATION_SONGS:
            raise ValueError("a >=2-song corpus must be eligible")
        # ``missing_song_ids`` is EXCLUDED-requested evidence and may legitimately coexist with a
        # comparable eligible population (e.g. 4 eligible + 1 silent requested song).  Per-
        # representation losses (an eligible song lacking a searchable medoid in one class) are NOT
        # recorded on this shared whole-song identity — the analyzer surfaces them as the
        # representation's own non-comparable result.


def _evaluation_corpus_payload(backbone: str, song_ids: Sequence[str], semantics_version: int) -> str:
    """Deterministic tagged pre-image for an evaluation-corpus identity hash."""
    return "\n".join(
        [
            "evaluation_corpus",
            f"semantics_version={int(semantics_version)}",
            f"backbone={backbone}",
            f"song_count={len(song_ids)}",
            "song_ids=" + ",".join(sorted(song_ids)),
        ]
    )


def song_ids_digest(song_ids: Sequence[str]) -> str:
    """Deterministic SHA-256 over a sorted song-id set (the missing-evidence digest)."""
    body = "\n".join(f"song={s}" for s in sorted(set(song_ids)))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def resolve_evaluation_corpus(catalog, stream_store, requested_song_ids, *, backbone: str) -> EvaluationCorpusIdentity:
    """Resolve the backbone's single explicit evaluation-corpus identity (fail-closed eligibility).

    A requested song is ELIGIBLE exactly when its committed observation group is valid
    (``stream_store.load_committed_observation`` succeeds) AND it has at least one non-silent
    whole-song patch (committed ``mask`` row ``== 1``; patches beyond a shorter committed mask
    count as searchable per the whole-song source-index rule).  Every other requested song is
    EXCLUDED with evidence into ``missing_song_ids`` — never silently pooled all-searchable.

    ``catalog`` (a compact CatalogHandle / its snapshot connection) FAILS CLOSED with a
    ``ValueError`` when the backbone has no segmented config surface, so an identity is never
    resolved for a backbone the current catalog does not actually segment.  ``requested_song_ids``
    are the catalog-requested population selected once at the analyze/catalog boundary; the
    eligible subset is frozen in the returned identity (no later catalog / disposable view keyset
    is ever consulted to re-derive it).
    """
    con = _identity_con(catalog)
    if not _backbone_has_config_surface(con, backbone):
        raise ValueError(
            f"catalog has no seg_config rows for backbone {backbone!r}; cannot resolve an evaluation corpus"
        )

    import numpy as _np

    from scripts.embedding_research.streams import StreamStoreError

    requested = tuple(sorted({str(s) for s in requested_song_ids}))
    eligible: list[str] = []
    missing: list[str] = []
    for song in requested:
        try:
            observation = stream_store.load_committed_observation(song, backbone)
        except StreamStoreError:
            # No valid committed observation group -> the song is not searchable in this corpus
            # (uncommitted / corrupt / absent) -> excluded with evidence.
            missing.append(song)
            continue
        stream = _np.asarray(observation.stream, dtype=_np.float32)
        mask = _np.asarray(observation.mask, dtype=_np.uint8)
        patch_count = int(stream.shape[0])
        # Whole-song non-silent source indices (a mask shorter than the stream leaves trailing
        # patches searchable); a fully-silent (zero-searchable) song is excluded with evidence.
        non_silent = _np.ones(patch_count, dtype=bool)
        length = min(int(mask.shape[0]), patch_count)
        if length:
            non_silent[:length] = _np.asarray(mask[:length] == 1, dtype=bool)
        if not bool(_np.any(non_silent)):
            missing.append(song)
            continue
        eligible.append(song)

    song_ids = tuple(sorted(eligible))
    missing_song_ids = tuple(sorted(missing))
    semantics_version = EVALUATION_CORPUS_SEMANTICS_VERSION
    eligible_flag = len(song_ids) >= _MIN_ANALYZABLE_EVALUATION_SONGS
    return EvaluationCorpusIdentity(
        backbone=backbone,
        song_ids=song_ids,
        corpus_hash=hashlib.sha256(
            _evaluation_corpus_payload(backbone, song_ids, semantics_version).encode("utf-8")
        ).hexdigest(),
        count=len(song_ids),
        eligible=eligible_flag,
        comparable=eligible_flag,
        missing_song_ids=missing_song_ids,
        missing_count=len(missing_song_ids),
        missing_digest=song_ids_digest(missing_song_ids) if missing_song_ids else None,
        semantics_version=semantics_version,
    )


def _backbone_has_config_surface(con, backbone: str) -> bool:
    """True when *con* is queryable and the backbone has at least one compact ``seg_config`` row."""
    try:
        row = con.execute(f"SELECT count(*) FROM {SEG_CONFIG_TABLE} WHERE backbone = ?", [backbone]).fetchone()
    except Exception:
        return False
    return bool(row and row[0])


# ── Logical export/import verification ─────────────────────────────────────────


def verify_catalog_logical_identity(
    con_a,
    con_b,
    *,
    schema_version: int,
) -> tuple[str, ...]:
    """Compare the canonical logical identity of two catalogs (e.g. export/import round-trip).

    Compares ``catalog_fingerprint``, per-song signatures, the set of
    catalog songs, and canonical config rows.  Returns a tuple of human-readable mismatches
    (empty == the two catalogs are logically identical).  This is the correct export/import
    oracle — never a DuckDB physical-byte comparison.
    """
    errors: list[str] = []
    if catalog_fingerprint(con_a, schema_version=schema_version) != catalog_fingerprint(
        con_b, schema_version=schema_version
    ):
        errors.append("catalog_fingerprint differs across the two logical states")
    songs_a = set(_catalog_song_ids(con_a))
    songs_b = set(_catalog_song_ids(con_b))
    if songs_a != songs_b:
        errors.append(
            f"cataloged song sets differ (only_a={sorted(songs_a - songs_b)}, only_b={sorted(songs_b - songs_a)})"
        )
    else:
        errors.extend(
            f"song_signature for {song!r} differs across the two logical states"
            for song in sorted(songs_a)
            if song_signature(con_a, song) != song_signature(con_b, song)
        )
    cfg_a = _fetch_rows(con_a, SEG_CONFIG_TABLE, SEG_CONFIG_COLS)
    cfg_b = _fetch_rows(con_b, SEG_CONFIG_TABLE, SEG_CONFIG_COLS)
    if cfg_a != cfg_b:
        errors.append("seg_config row sets differ across the two logical states")
    return tuple(errors)
