"""Strict catalog identity: canonical serialization, song signatures, corpus search hash,
manifest-only catalog fingerprint, and logical export/import verification (Plan C, Phase 4).

Implements DD R9 + U1 + the identity/serialization contract:

* Canonical serialization fixes table / column / NULL / type / numeric encodings and sorts
  rows by stable keys.  Numeric thresholds reuse the Plan A canonical encoders
  (``helpers.thresholds.canonical_float`` etc.) so ``0.1`` and ``1e-1`` (the same double)
  always encode identically and never in scientific-notation form.
* A **per-song signature** is the SHA-256 of a canonical serialization of that song's exact
  catalog content (observed medoids + sorted membership rows incl. absorbed-outlier flags)
  plus that song's verified ``ready`` stream fingerprints.  Any membership / medoid /
  outlier-flag / stream-fingerprint change changes the signature.
* ``search_view_hash`` is the STRICT logical corpus identity (R9): SHA-256 over the context
  (catalog-semantics / canonical-serialization / manifest versions + software versions that
  affect identity), sorted per-song signatures, canonical config rows (``alias_of_config_id
  IS NULL`` — aliases are reported, never multiplied into corpus identity), and all ``ready``
  stream fingerprints.  Membership change, stream re-embed, threshold-semantics change,
  software-version change, and ordering/serialization-version change each change the hash.
* ``catalog_fingerprint`` (R15/U1) is a SEPARATE, MANIFEST-ONLY, non-self-referential
  SHA-256 over a versioned canonical serialization of the COMPLETE logical state
  (``seg_config``, ``seg_membership``, ``seg_meta``, ``stream_registry``,
  ``head_stream_registry``, ``run_provenance``, ``corpus_state`` + ``catalog_metadata`` and
  the schema version) — with NO ``catalog_fingerprint`` column in any table and the value
  deliberately excluded from its own input.  It is never a DuckDB byte hash (WAL/checkpoint
  rewrites can change bytes without changing logical rows); logical identity is the oracle.
* Export/import (or any serialization round-trip) is verified by comparing canonical logical
  state / hashes, never DuckDB physical bytes.

Nothing here wires the CLI (Plan E owns phase boundaries); this is the pure computation
surface a report / build / CLI phase calls.  No PK/UNIQUE, no view_manifest, no second
catalog-state table is introduced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.embedding_research.db.catalog_metadata import (
    CATALOG_METADATA_TABLE,
    catalog_metadata_columns,
    read_catalog_metadata,
)
from scripts.embedding_research.db.provenance import (
    CORPUS_STATE_TABLE,
    RUN_PROVENANCE_TABLE,
    corpus_state_columns,
    run_provenance_columns,
)
from scripts.embedding_research.db.segmentation import (
    SEG_CONFIG_TABLE,
    SEG_MEMBERSHIP_TABLE,
    SEG_META_TABLE,
    seg_config_columns,
    seg_membership_columns,
    seg_meta_columns,
)
from scripts.embedding_research.helpers.thresholds import (
    PTC_STRATEGY_VERSION,
    canonical_float,
)
from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CATALOG_MANIFEST_VERSION",
    "CATALOG_SEMANTICS_VERSION",
    "CATALOG_SERIALIZATION_VERSION",
    "CatalogIdentityContext",
    "catalog_fingerprint",
    "catalog_state_payload",
    "search_view_hash",
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

    Changing any field changes ``search_view_hash`` (and, where the values are included,
    ``catalog_fingerprint``).  ``software_versions`` is an ordered map of
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


#: Identity-affecting seg_config fields (excludes the derived canonical_config_hash and the
#: volatile provenance created_at/run_id so a rerun of the SAME logical configuration does
#: not perturb identity).  alias_of_config_id is handled at the alias layer, not here.
_CONFIG_IDENTITY_FIELDS: tuple[str, ...] = (
    "config_id",
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "semantics",
    "calibration_record",
    "outlier_window",
    "strategy_version",
)


def _fetch_rows(con, table: str, columns: Sequence[str]) -> list[dict]:
    """All rows of *table* as dicts, deterministically ordered by every column."""
    order = ", ".join(columns)
    rows = con.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}").fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _ready_streams(con) -> list[dict]:
    """Every ``status='ready'`` ``stream_registry`` row (the verified corpus streams)."""
    cols = STREAM_REGISTRY_COLUMNS
    rows = con.execute(
        f"SELECT {', '.join(cols)} FROM {STREAM_TABLE} WHERE status = 'ready' ORDER BY {', '.join(cols)}"
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _canonical_stream_line(rec: Mapping[str, object]) -> str:
    """Content identity of one verified stream (fingerprint + shape/provenance/version).

    Excludes the opaque ``artifact_ref`` (a path — never an identity per R3) and the
    volatile status/run_id/timestamps.  The fingerprint covers the immutable payload bytes;
    the shape/provenance/version fields cover the invalidation axes of DD invalidation rules.
    """
    return "|".join(
        f"{key}={_canon_value(rec[key])}"
        for key in (
            "song_id",
            "backbone",
            "patch_count",
            "dim",
            "dtype",
            "format_version",
            "fingerprint_sha256",
            "preprocess_fn",
            "preprocess_version",
            "backbone_model_hash",
            "embed_semantics_version",
        )
    )


# ── Per-song signature ─────────────────────────────────────────────────────────


def song_signature(con, song_id: str) -> str:
    """Strict SHA-256 per-song signature over the song's exact catalog content + streams.

    Pre-image lines: the song identity, its ``ready`` stream identities (fingerprints +
    shape/provenance), and for every ``(config_id, seg_id)`` the observed medoid, the
    structural counts/ranges and the sorted membership rows (with absorbed-outlier flags).
    Lines are globally sorted for deterministic ordering; NULL/type/numeric encodings are
    fixed.  Any membership / medoid / outlier-flag / stream change changes the signature.
    """
    lines: list[str] = [f"song={song_id}"]
    lines.extend(_canonical_stream_line(rec) for rec in _ready_streams(con) if rec["song_id"] == song_id)
    meta_rows = con.execute(
        f"SELECT {', '.join(seg_meta_columns)} FROM {SEG_META_TABLE} WHERE song_id = ? ORDER BY config_id, seg_id",
        [song_id],
    ).fetchall()
    mem_rows = con.execute(
        f"SELECT {', '.join(seg_membership_columns)} FROM {SEG_MEMBERSHIP_TABLE} "
        "WHERE song_id = ? ORDER BY config_id, seg_id, member_patch_idx",
        [song_id],
    ).fetchall()
    for meta in meta_rows:
        m = dict(zip(seg_meta_columns, meta, strict=True))
        lines.append(
            "|".join(
                f"{key}={_canon_value(m[key])}"
                for key in (
                    "config_id",
                    "seg_id",
                    "medoid_source_patch_idx",
                    "member_count",
                    "absorbed_outlier_count",
                    "start_idx",
                    "end_idx",
                )
            )
        )
    for mem in mem_rows:
        r = dict(zip(seg_membership_columns, mem, strict=True))
        lines.append(
            "|".join(
                f"{key}={_canon_value(r[key])}"
                for key in ("config_id", "seg_id", "member_patch_idx", "is_absorbed_outlier")
            )
        )
    body = "\n".join(sorted(lines))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _catalog_song_ids(con) -> list[str]:
    rows = con.execute(f"SELECT DISTINCT song_id FROM {SEG_META_TABLE} ORDER BY song_id").fetchall()
    return [str(row[0]) for row in rows]


# ── Search-view hash (strict corpus identity) ──────────────────────────────────


def _load_context(con, context: CatalogIdentityContext | None) -> CatalogIdentityContext:
    """Use *context* if given; else derive from the singleton ``catalog_metadata`` row (or defaults)."""
    if context is not None:
        return context
    meta = read_catalog_metadata(con)
    if meta is None:
        return CatalogIdentityContext()
    return CatalogIdentityContext(
        catalog_semantics_version=int(meta["catalog_semantics_version"]),
        serialization_version=int(meta["serialization_version"]),
        manifest_version=int(meta["manifest_version"]),
        strategy_version=CATALOG_STRATEGY_VERSION,
    )


def search_view_hash(con, *, context: CatalogIdentityContext | None = None) -> str:
    """Strict logical corpus ``search_view_hash`` (R9).

    Pre-image = context lines (semantics/serialization/manifest/strategy + software versions
    that affect identity) + sorted per-song signatures + canonical config rows (canonical
    only) + every ready stream's canonical identity.  Deterministic ordering everywhere.
    """
    ctx = _load_context(con, context)
    lines: list[str] = ctx.context_lines()
    lines.extend(f"song_signature={song_id}|{song_signature(con, song_id)}" for song_id in _catalog_song_ids(con))
    cfg_rows = _fetch_rows(con, SEG_CONFIG_TABLE, seg_config_columns)
    canonical_config_lines = [
        "|".join(f"{key}={_canon_value(cfg[key])}" for key in _CONFIG_IDENTITY_FIELDS)
        for cfg in cfg_rows
        if cfg["alias_of_config_id"] is None
    ]
    lines.extend(f"config={identity}" for identity in canonical_config_lines)
    lines.extend(_canonical_stream_line(rec) for rec in _ready_streams(con))
    body = "\n".join(sorted(lines))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── Manifest-only catalog fingerprint (complete logical state, non-self-referential) ──

#: The seven logical tables (plus catalog metadata/schema version) the fingerprint covers.
_FINGERPRINT_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SEG_CONFIG_TABLE, seg_config_columns),
    (SEG_MEMBERSHIP_TABLE, seg_membership_columns),
    (SEG_META_TABLE, seg_meta_columns),
    (STREAM_TABLE, STREAM_REGISTRY_COLUMNS),
    (HEAD_STREAM_TABLE, HEAD_STREAM_REGISTRY_COLUMNS),
    (RUN_PROVENANCE_TABLE, run_provenance_columns),
    (CORPUS_STATE_TABLE, corpus_state_columns),
    (CATALOG_METADATA_TABLE, catalog_metadata_columns),
)


def catalog_state_payload(con, *, schema_version: int) -> str:
    """The canonical pre-image of :func:`catalog_fingerprint` (non-self-referential).

    Serializes the COMPLETE logical state: every canonicalized row of the seven logical
    tables plus the ``catalog_metadata`` singleton and the *schema_version* marker.  The
    ``catalog_fingerprint`` value is deliberately absent — it is manifest-only and lives in
    no table column, so it can never be part of its own input.
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

    ``catalog_fingerprint`` is never stored in a DB column (corpus_state/catalog_metadata
    deliberately carry no such column), so the fingerprint cannot feed its own input.  It is
    NOT a DuckDB byte hash: WAL/checkpoint rewrites can change bytes without changing logical
    rows, so logical identity is the oracle (verified via export/import comparison).
    """
    return hashlib.sha256(catalog_state_payload(con, schema_version=schema_version).encode("utf-8")).hexdigest()


# ── Logical export/import verification ─────────────────────────────────────────


def verify_catalog_logical_identity(
    con_a,
    con_b,
    *,
    schema_version: int,
    context: CatalogIdentityContext | None = None,
) -> tuple[str, ...]:
    """Compare the canonical logical identity of two catalogs (e.g. export/import round-trip).

    Compares ``catalog_fingerprint``, ``search_view_hash``, per-song signatures, the set of
    catalog songs, and canonical config hashes.  Returns a tuple of human-readable
    mismatches (empty == the two catalogs are logically identical).  This is the correct
    export/import oracle — never a DuckDB physical-byte comparison.
    """
    errors: list[str] = []
    if catalog_fingerprint(con_a, schema_version=schema_version) != catalog_fingerprint(
        con_b, schema_version=schema_version
    ):
        errors.append("catalog_fingerprint differs across the two logical states")
    if search_view_hash(con_a, context=context) != search_view_hash(con_b, context=context):
        errors.append("search_view_hash differs across the two logical states")
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
    cfg_a = _fetch_rows(con_a, SEG_CONFIG_TABLE, seg_config_columns)
    cfg_b = _fetch_rows(con_b, SEG_CONFIG_TABLE, seg_config_columns)
    if cfg_a != cfg_b:
        errors.append("seg_config row sets differ across the two logical states")
    return tuple(errors)
