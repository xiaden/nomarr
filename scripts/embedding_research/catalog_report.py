"""Alias resolution/validation, structural-change summaries, and catalog reports
(Plan C, Phase 4 — P4-S2 + P4-S4).

Aliases
    Threshold-collapse aliases are preserved as ``seg_config.alias_of_config_id`` pointing an
    alias row at its canonical config row.  A config is canonical when ``alias_of_config_id``
    is NULL; otherwise it is an alias.  Both alias and canonical own their ``seg_config`` row;
    the alias's ``threshold_configured`` may differ but it must *collapse to the canonical
    meaning*: its effective segmentation meaning ``(backbone, bin_mode, semantics,
    threshold_effective, outlier_window, strategy_version)`` must equal the canonical's.
    Aliasing never permits two meanings for one canonical, so :func:`validate_alias_graph`
    rejects:

    * self-aliasing (``alias_of_config_id == config_id``);
    * a missing alias target;
    * an alias whose target is itself an alias (alias-of-alias) — targets must be canonical,
      which also forbids chains/cycles and "an alias that is itself an alias target";
    * a meaning conflict — an alias whose effective meaning differs from its canonical's
      (two meanings under one canonical).

    :func:`resolve_alias_id` reduces any alias id to its canonical id (identity collapses to
    one canonical meaning); canonical ids resolve to themselves.

Structural-change summaries
    :func:`capture_catalog_structure` snapshots each config's exact per-song membership
    structure (segments with observed medoid, member/outlier counts, membership-row count).
    :func:`structural_changes` diffs two snapshots (e.g. two runs) and reports membership /
    medoid / count / presence changes EXPLICITLY — distinct configurations are never silently
    collapsed.

Catalog report (P4-S4)
    :func:`build_catalog_report` reads catalog state + run provenance and produces a listing:
    canonical configs, aliases, configured + effective thresholds, empty songs (eligible songs
    lacking catalog coverage), exact membership + absorbed-outlier counts, observed medoid-index
    changes, structural changes, ``search_view_hash`` and ``catalog_fingerprint``.  Because this
    report is read from catalog state + run provenance (a DB-derived read), it surfaces only
    empty songs.

    Per-config partial/empty/failed run status is NOT derivable from a post-build DB read (per-
    (config, song) write failures are transient and not persisted per-song), so ``CatalogReport``
    cannot distinguish a failed song from one never covered.  The per-config ``empty`` /
    ``partial`` / ``failed`` status that a build run actually recorded is visible only on the
    build's own return value: each per-config ``ConfigBuildOutcome`` inside
    :class:`CatalogBuildReport`.configs carries ``status`` and ``failed_songs`` (failed songs are
    per-config outcome fields, never a single ``CatalogBuildReport`` attribute).  The ``run``
    provenance row records the run-level ``status``; the per-config ``structural_change_summary``
    ("/config_id:status:songs=n/m"-style) is stored there for the CLI, but ``report_to_text``
    renders only the run ``status`` line, not that per-config summary.

    It does NOT wire the CLI (Plan E) and does NOT add a view_manifest or any second catalog-
    state table; no per-song failed/empty table is added in Plan C.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from scripts.embedding_research.catalog_identity import (
    catalog_fingerprint,
    search_view_hash,
)
from scripts.embedding_research.db.provenance import (
    read_run_provenance,
)
from scripts.embedding_research.db.segmentation import (
    SEG_CONFIG_TABLE,
    SEG_MEMBERSHIP_TABLE,
    SEG_META_TABLE,
    seg_config_columns,
    seg_meta_columns,
)
from scripts.embedding_research.helpers.thresholds import canonical_float
from scripts.embedding_research.streams.records import STREAM_TABLE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "AliasError",
    "AliasIndex",
    "AliasMeaningConflictError",
    "AliasSelfError",
    "AliasTargetMissingError",
    "AliasTargetNotCanonicalError",
    "CatalogReport",
    "ConfigSnapshot",
    "SegmentSnapshot",
    "SongSnapshot",
    "StructuralChanges",
    "build_alias_index",
    "build_catalog_report",
    "capture_catalog_structure",
    "resolve_alias_id",
    "structural_changes",
    "validate_alias_graph",
]


# ── Alias exceptions ───────────────────────────────────────────────────────────


class AliasError(RuntimeError):
    """Base error for segmentation-config alias validation."""


class AliasSelfError(AliasError):
    """A config aliases itself."""


class AliasTargetMissingError(AliasError):
    """An alias points at a nonexistent config id."""


class AliasTargetNotCanonicalError(AliasError):
    """An alias target is itself an alias (alias-of-alias / chain / cycle)."""


class AliasMeaningConflictError(AliasError):
    """An alias's effective meaning differs from its canonical's (two meanings, one canonical)."""


# ── Alias resolution ───────────────────────────────────────────────────────────

#: The fields that define the EFFECTIVE segmentation meaning a config row applies.
_MEANING_FIELDS: tuple[str, ...] = (
    "backbone",
    "bin_mode",
    "semantics",
    "threshold_effective",
    "outlier_window",
    "strategy_version",
)


def _effective_meaning(cfg: Mapping[str, object]) -> str:
    """Canonical, order-fixed encoding of a config's effective segmentation meaning.

    Compares floats via their canonical text (0.1 == 1e-1) so equivalent doubles compare
    equal regardless of the stored literal.  ``threshold_configured`` is deliberately NOT in
    the meaning — the alias's configured value may differ as long as it collapses to the
    canonical effective meaning.
    """
    parts: list[str] = []
    for key in _MEANING_FIELDS:
        value = cfg[key]
        if key == "threshold_effective":
            parts.append(f"{key}={canonical_float(float(value))}")
        else:
            parts.append(f"{key}={value}")
    return "|".join(parts)


@dataclass(frozen=True)
class AliasIndex:
    """Validated alias→canonical mapping over a config set.

    ``canonical_config_ids`` lists canonical config ids ascending; ``alias_targets`` maps each
    alias config id to its canonical config id (ascending by alias id).
    """

    canonical_config_ids: tuple[int, ...]
    alias_targets: dict[int, int]

    @property
    def alias_config_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self.alias_targets))


def build_alias_index(configs: Iterable[Mapping[str, object]]) -> AliasIndex:
    """Build a validated alias index from ``seg_config`` row dicts.

    Raises the appropriate :class:`AliasError` subclass on the first invalid alias (self,
    missing target, non-canonical target / chain, or meaning conflict).  A config with no
    ``alias_of_config_id`` is canonical and resolves to itself.
    """
    by_id: dict[int, dict] = {}
    for cfg in configs:
        by_id[int(cfg["config_id"])] = dict(cfg)
    canonical: list[int] = []
    alias_targets: dict[int, int] = {}
    for config_id in sorted(by_id):
        cfg = by_id[config_id]
        target_raw = cfg.get("alias_of_config_id")
        if target_raw is None:
            canonical.append(config_id)
            continue
        target = int(target_raw)
        if target == config_id:
            raise AliasSelfError(f"config {config_id} cannot alias itself")
        if target not in by_id:
            raise AliasTargetMissingError(f"config {config_id} aliases missing config {target}")
        tgt = by_id[target]
        if tgt.get("alias_of_config_id") is not None:
            raise AliasTargetNotCanonicalError(
                f"config {config_id} aliases config {target} which is itself an alias "
                f"(alias targets must be canonical; chains/cycles are rejected)"
            )
        if _effective_meaning(cfg) != _effective_meaning(tgt):
            raise AliasMeaningConflictError(
                f"config {config_id} aliases canonical config {target} but its effective "
                f"meaning {_effective_meaning(cfg)!r} differs from the canonical's "
                f"{_effective_meaning(tgt)!r} — two meanings under one canonical"
            )
        alias_targets[config_id] = target
    return AliasIndex(canonical_config_ids=tuple(canonical), alias_targets=alias_targets)


def validate_alias_graph(con) -> AliasIndex:
    """Load every ``seg_config`` row and validate the alias graph; return the index."""
    rows = con.execute(
        f"SELECT {', '.join(seg_config_columns)} FROM {SEG_CONFIG_TABLE} ORDER BY {', '.join(seg_config_columns)}"
    ).fetchall()
    configs = [dict(zip(seg_config_columns, row, strict=True)) for row in rows]
    return build_alias_index(configs)


def resolve_alias_id(config_id: int, index: AliasIndex) -> int:
    """Reduce *config_id* to its canonical id (identity collapses to one canonical meaning)."""
    canonical = index.alias_targets.get(config_id, config_id)
    if canonical not in index.canonical_config_ids:
        raise AliasError(f"config {config_id} does not resolve to a canonical config in the given index")
    return canonical


# ── Structural snapshots and diffs ─────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentSnapshot:
    seg_id: int
    medoid_source_patch_idx: int
    member_count: int
    absorbed_outlier_count: int
    membership_rows: int


@dataclass(frozen=True)
class SongSnapshot:
    song_id: str
    segments: tuple[SegmentSnapshot, ...]


@dataclass(frozen=True)
class ConfigSnapshot:
    config_id: int
    songs: tuple[SongSnapshot, ...]


def _read_config_snapshot(con, config_id: int) -> ConfigSnapshot:
    meta = con.execute(
        f"SELECT {', '.join(seg_meta_columns)} FROM {SEG_META_TABLE} WHERE config_id = ? ORDER BY song_id, seg_id",
        [config_id],
    ).fetchall()
    count_rows = con.execute(
        f"SELECT song_id, seg_id, count(*) FROM {SEG_MEMBERSHIP_TABLE} "
        "WHERE config_id = ? GROUP BY song_id, seg_id ORDER BY song_id, seg_id",
        [config_id],
    ).fetchall()
    membership_counts = {(str(s), int(sg)): int(n) for s, sg, n in count_rows}
    by_song: dict[str, list[SegmentSnapshot]] = {}
    for row in meta:
        m = dict(zip(seg_meta_columns, row, strict=True))
        song = str(m["song_id"])
        seg_id = int(m["seg_id"])
        by_song.setdefault(song, []).append(
            SegmentSnapshot(
                seg_id=seg_id,
                medoid_source_patch_idx=int(m["medoid_source_patch_idx"]),
                member_count=int(m["member_count"]),
                absorbed_outlier_count=int(m["absorbed_outlier_count"]),
                membership_rows=membership_counts.get((song, seg_id), 0),
            )
        )
    songs = tuple(
        SongSnapshot(song_id=song, segments=tuple(sorted(seg_list, key=lambda s: s.seg_id)))
        for song, seg_list in sorted(by_song.items())
    )
    return ConfigSnapshot(config_id=config_id, songs=songs)


def capture_catalog_structure(con) -> Mapping[int, ConfigSnapshot]:
    """Snapshot the exact membership structure of every canonical config id present."""
    rows = con.execute(f"SELECT config_id FROM {SEG_CONFIG_TABLE} ORDER BY config_id").fetchall()
    snapshots: dict[int, ConfigSnapshot] = {}
    for (config_id,) in rows:
        snapshots[int(config_id)] = _read_config_snapshot(con, int(config_id))
    return snapshots


@dataclass(frozen=True)
class StructuralChanges:
    """Explicit structural changes between a previous and a current catalog structure.

    Never silently collapses distinct configurations: every added/removed/changed config is
    reported, and within changed configs every song/segment presence, membership-count,
    absorbed-outlier-count, membership-row, and observed-medoid change is listed.
    """

    prev: Mapping[int, ConfigSnapshot]
    curr: Mapping[int, ConfigSnapshot]
    added_config_ids: tuple[int, ...]
    removed_config_ids: tuple[int, ...]
    changed_config_ids: tuple[int, ...]
    changes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return not self.changes


def structural_changes(
    prev: Mapping[int, ConfigSnapshot],
    curr: Mapping[int, ConfigSnapshot],
) -> StructuralChanges:
    """Diff two structural snapshots, emitting an explicit change line per difference."""
    changes: list[str] = []
    added: list[int] = []
    removed: list[int] = []
    changed: list[int] = []

    for config_id in sorted(set(curr) - set(prev)):
        added.append(config_id)
        changes.append(f"config added: {config_id} ({len(curr[config_id].songs)} songs)")
    for config_id in sorted(set(prev) - set(curr)):
        removed.append(config_id)
        changes.append(f"config removed: {config_id} ({len(prev[config_id].songs)} songs)")
    for config_id in sorted(set(prev) & set(curr)):
        a = {song.song_id: song for song in prev[config_id].songs}
        b = {song.song_id: song for song in curr[config_id].songs}
        new_songs = sorted(set(b) - set(a))
        changes.extend(
            f"config {config_id} song {song_id!r}: added ({len(b[song_id].segments)} segments)" for song_id in new_songs
        )
        gone_songs = sorted(set(a) - set(b))
        changes.extend(
            f"config {config_id} song {song_id!r}: removed ({len(a[song_id].segments)} segments)"
            for song_id in gone_songs
        )
        for song_id in sorted(set(a) & set(b)):
            a_segs = {s.seg_id: s for s in a[song_id].segments}
            b_segs = {s.seg_id: s for s in b[song_id].segments}
            new_segs = sorted(set(b_segs) - set(a_segs))
            changes.extend(
                f"config {config_id} song {song_id!r}: segment {seg_id} added "
                f"(medoid={b_segs[seg_id].medoid_source_patch_idx})"
                for seg_id in new_segs
            )
            gone_segs = sorted(set(a_segs) - set(b_segs))
            changes.extend(f"config {config_id} song {song_id!r}: segment {seg_id} removed" for seg_id in gone_segs)
            for seg_id in sorted(set(a_segs) & set(b_segs)):
                before = a_segs[seg_id]
                after = b_segs[seg_id]
                if before.medoid_source_patch_idx != after.medoid_source_patch_idx:
                    changes.append(
                        f"config {config_id} song {song_id!r}: segment {seg_id} "
                        f"medoid_source_patch_idx {before.medoid_source_patch_idx} -> "
                        f"{after.medoid_source_patch_idx}"
                    )
                if before.member_count != after.member_count:
                    changes.append(
                        f"config {config_id} song {song_id!r}: segment {seg_id} "
                        f"member_count {before.member_count} -> {after.member_count}"
                    )
                if before.absorbed_outlier_count != after.absorbed_outlier_count:
                    changes.append(
                        f"config {config_id} song {song_id!r}: segment {seg_id} "
                        f"absorbed_outlier_count {before.absorbed_outlier_count} -> "
                        f"{after.absorbed_outlier_count}"
                    )
                if before.membership_rows != after.membership_rows:
                    changes.append(
                        f"config {config_id} song {song_id!r}: segment {seg_id} "
                        f"membership_rows {before.membership_rows} -> {after.membership_rows}"
                    )
        if prev[config_id] != curr[config_id]:
            changed.append(config_id)
    return StructuralChanges(
        prev=prev,
        curr=curr,
        added_config_ids=tuple(added),
        removed_config_ids=tuple(removed),
        changed_config_ids=tuple(changed),
        changes=tuple(changes),
    )


# ── Catalog report ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CatalogReport:
    """A read-only catalog report (P4-S4) over catalog state + run provenance.

    ``empty_songs`` lists ``(config_id, song_id)`` pairs where the config's backbone has a
    ready stream for the song but the config produced zero membership rows for it.  ``run``
    records the latest (or requested) catalog run provenance.  ``structural_changes`` holds
    the diff against a caller-supplied baseline structure when provided (observed-medoid
    changes are emitted as ordinary ``changes`` lines, never a separate field); otherwise
    the current per-config structure is exposed via ``config_snapshots``.
    """

    catalog_fingerprint: str
    search_view_hash: str
    canonical_config_ids: tuple[int, ...]
    alias_entries: tuple[tuple[int, int], ...]  # (alias_config_id, canonical_config_id)
    canonical_configs: tuple[dict, ...]
    alias_configs: tuple[dict, ...]
    config_content: tuple[dict, ...]
    empty_songs: tuple[tuple[int, str], ...]
    run: dict
    config_snapshots: Mapping[int, ConfigSnapshot]
    structural_changes: StructuralChanges | None
    changes: tuple[str, ...]

    @property
    def alias_count(self) -> int:
        return len(self.alias_entries)

    @property
    def membership_row_total(self) -> int:
        return sum(int(c["membership_rows"]) for c in self.config_content)

    @property
    def absorbed_outlier_total(self) -> int:
        return sum(int(c["absorbed_outliers"]) for c in self.config_content)


def _latest_catalog_run(con, run_id: str | None) -> dict:
    if run_id is not None:
        rows = read_run_provenance(con, run_id=run_id)
        matches = [r for r in rows if r["phase"] == "catalog"]
        return matches[0] if matches else {}
    rows = read_run_provenance(con)
    for r in sorted(rows, key=lambda r: str(r.get("started_at") or 0)):
        if r.get("phase") == "catalog":
            latest = r
    return latest if "latest" in locals() else {}


def build_catalog_report(
    con,
    *,
    schema_version: int,
    run_id: str | None = None,
    baseline_structure: Mapping[int, ConfigSnapshot] | None = None,
) -> CatalogReport:
    """Generate the catalog report (P4-S4).

    Reads the current catalog state and (latest or given) catalog run provenance and emits a
    listing with every required field.  Uses *baseline_structure* (a prior
    :func:`capture_catalog_structure` snapshot) to compute observed medoid-index and
    structural changes; when none is supplied the report exposes the current
    ``config_snapshots`` and no baseline diff.
    """
    fingerprint = catalog_fingerprint(con, schema_version=schema_version)
    search_hash = search_view_hash(con)

    configs = {
        int(cfg["config_id"]): dict(cfg)
        for cfg in (
            dict(zip(seg_config_columns, row, strict=True))
            for row in con.execute(
                f"SELECT {', '.join(seg_config_columns)} FROM {SEG_CONFIG_TABLE} "
                f"ORDER BY {', '.join(seg_config_columns)}"
            ).fetchall()
        )
    }
    try:
        index = build_alias_index(configs.values())
    except AliasError as exc:  # pragma: no cover - surfaced defensively
        # Record the alias-graph corruption before degrading to an all-canonical index so
        # the exception text is not silently lost.
        _log.warning("alias graph corrupt; report degrades to an all-canonical index: %s", exc)
        index = AliasIndex(
            canonical_config_ids=tuple(sorted(configs)),
            alias_targets={},
        )

    canonical_configs = tuple(configs[cid] for cid in index.canonical_config_ids)
    alias_configs = tuple(configs[cid] for cid in index.alias_config_ids)
    alias_entries = tuple(
        (int(alias_id), int(canonical)) for alias_id, canonical in sorted(index.alias_targets.items())
    )

    # Per-config content: segments, membership / outlier counts, empty songs.
    content: list[dict] = []
    empty_songs: list[tuple[int, str]] = []
    for cfg in canonical_configs:
        config_id = int(cfg["config_id"])
        backbone = str(cfg["backbone"])
        seg_rows = con.execute(f"SELECT count(*) FROM {SEG_META_TABLE} WHERE config_id = ?", [config_id]).fetchone()[0]
        mem_rows = con.execute(
            f"SELECT count(*) FROM {SEG_MEMBERSHIP_TABLE} WHERE config_id = ?", [config_id]
        ).fetchone()[0]
        outlier_rows = con.execute(
            f"SELECT count(*) FROM {SEG_MEMBERSHIP_TABLE} WHERE config_id = ? AND is_absorbed_outlier = true",
            [config_id],
        ).fetchone()[0]
        content.append(
            {
                "config_id": config_id,
                "backbone": backbone,
                "segments": int(seg_rows),
                "membership_rows": int(mem_rows),
                "absorbed_outliers": int(outlier_rows),
            }
        )
        covered = {
            str(r[0])
            for r in con.execute(
                f"SELECT DISTINCT song_id FROM {SEG_META_TABLE} WHERE config_id = ?",
                [config_id],
            ).fetchall()
        }
        ready = {
            str(r[0])
            for r in con.execute(
                f"SELECT DISTINCT song_id FROM {STREAM_TABLE} WHERE backbone = ? AND status = 'ready'",
                [backbone],
            ).fetchall()
        }
        empty_songs.extend((config_id, song_id) for song_id in sorted(ready - covered))

    snapshots = capture_catalog_structure(con)
    if baseline_structure is not None:
        diff = structural_changes(baseline_structure, snapshots)
        changes: tuple[str, ...] = diff.changes
    else:
        diff = None
        changes = ()

    run = _latest_catalog_run(con, run_id)
    return CatalogReport(
        catalog_fingerprint=fingerprint,
        search_view_hash=search_hash,
        canonical_config_ids=tuple(index.canonical_config_ids),
        alias_entries=alias_entries,
        canonical_configs=canonical_configs,
        alias_configs=alias_configs,
        config_content=tuple(content),
        empty_songs=tuple(empty_songs),
        run=run,
        config_snapshots=snapshots,
        structural_changes=diff,
        changes=changes,
    )


def report_to_text(report: CatalogReport) -> str:
    """Render a human-readable listing (used by tests/docs; the CLI phase is Plan E)."""
    lines: list[str] = [
        "catalog-report",
        f"catalog_fingerprint={report.catalog_fingerprint}",
        f"search_view_hash={report.search_view_hash}",
        f"canonical configs ({len(report.canonical_config_ids)}): "
        + ", ".join(str(cid) for cid in report.canonical_config_ids),
    ]
    lines.extend(
        f"  config {cfg['config_id']}: backbone={cfg['backbone']} bin_mode={cfg['bin_mode']} "
        f"semantics={cfg['semantics']} configured={canonical_float(float(cfg['threshold_configured']))} "
        f"effective={canonical_float(float(cfg['threshold_effective']))}"
        for cfg in report.canonical_configs
    )
    lines.append(f"aliases ({len(report.alias_entries)}):")
    for alias_id, canonical in report.alias_entries:
        lines.append(f"  alias {alias_id} -> canonical {canonical}")
    lines.append(f"membership_rows_total={report.membership_row_total}")
    lines.append(f"absorbed_outliers_total={report.absorbed_outlier_total}")
    lines.append(
        f"empty_songs ({len(report.empty_songs)}): "
        + ", ".join(f"config {cid} song {sid!r}" for cid, sid in report.empty_songs)
    )
    if report.run:
        lines.append(
            f"run: {report.run.get('run_id')} phase={report.run.get('phase')} status={report.run.get('status')}"
        )
    if report.changes:
        lines.append("structural changes:")
        lines.extend(f"  {change}" for change in report.changes)
    return "\n".join(lines)
