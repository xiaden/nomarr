"""Alias resolution/validation, structural-change summaries, and catalog reports
(Plan C, Phase 4 — P4-S2 + P4-S4; rewired to the COMPACT durable snapshot in P1-S6(d)).

Aliases
    Alias/collapse evidence is now derived TRANSIENTLY from the current exact /
    search hashes (DD L266): no durable alias graph or alias column exists.  Two configs whose
    per-song search leaves are identical produce one scorer execution and are reported as an
    alias (the lowest ``config_id`` is the representative; the others report to it).  Because
    every compact config is canonical, capture/structural-change reporting still diffs each
    config independently, so equal-exact/differing-search structural reporting is preserved.

Structural-change summaries
    :func:`capture_catalog_structure` snapshots each compact config's per-song structure from
    ``seg_meta`` (observed searchable medoid, ``searchable_count`` member count, ``absorbed_count``
    absorbed-outlier count).  :func:`structural_changes` diffs two snapshots and reports
    presence / medoid / count changes EXPLICITLY — distinct configurations are never silently
    collapsed.

Catalog report (P4-S4)
    :func:`build_catalog_report` reads COMPACT catalog state (``seg_config`` / ``catalog_song`` /
    ``seg_meta``) and produces a listing: canonical configs, transient alias/collapse entries,
    configured + effective thresholds, exact searchable + absorbed-outlier counts, observed
    medoid-index changes, structural changes, ``catalog_fingerprint``.
    Because the compact snapshot carries no per-patch membership rows, ``membership_row_total``
    is recomputed as the sum over ``seg_meta.searchable_count`` (never an invented per-row
    membership count).  ``empty_songs`` lists ``(config_id, song_id)`` pairs whose compact
    ``catalog_song`` row is metadata-only (zero searchable coverage) under the config.

    ``build_catalog_report`` is called with the COMPACT snapshot connection (typically
    ``CatalogHandle.con``), preserving the §C ``catalog_report(con, catalog: CatalogHandle)``
    report shape over a published/opened snapshot.

    It does NOT wire the CLI (Plan E) and does NOT add a view_manifest or any second catalog-
    state table; no per-song failed/empty table is added in Plan C.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from scripts.embedding_research.catalog_identity import (
    CATALOG_SEMANTICS_VERSION,
    catalog_fingerprint,
    collapse_search_representations,
)
from scripts.embedding_research.catalog_storage import (
    CATALOG_METADATA_TABLE,
    CATALOG_SONG_TABLE,
    RUN_PROVENANCE_COLS,
    RUN_PROVENANCE_TABLE,
    SEG_CONFIG_COLS,
    SEG_CONFIG_TABLE,
    SEG_META_COLS,
    SEG_META_TABLE,
    snapshot_leaf_hashes,
)
from scripts.embedding_research.helpers.thresholds import canonical_float

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CatalogReport",
    "ConfigSnapshot",
    "SegmentSnapshot",
    "SongSnapshot",
    "StructuralChanges",
    "build_catalog_report",
    "capture_catalog_structure",
    "catalog_report",
    "structural_changes",
]


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
    """Snapshot one config's per-song structure from COMPACT ``seg_meta`` rows.

    Medoid maps to ``search_medoid_source_patch_idx`` (``None`` -> ``-1`` sentinel so the
    int-typed :class:`SegmentSnapshot` stays total); member count maps to ``searchable_count``;
    absorbed-outlier count maps to ``absorbed_count``.  No per-patch membership rows are
    invented: ``membership_rows`` is recomputed as ``searchable_count`` (the number of
    searchable members reconstructed from the compact structural metadata).
    """
    meta = con.execute(
        f"SELECT {', '.join(SEG_META_COLS)} FROM {SEG_META_TABLE} WHERE config_id = ? ORDER BY song_id, seg_id",
        [config_id],
    ).fetchall()
    by_song: dict[str, list[SegmentSnapshot]] = {}
    for row in meta:
        m = dict(zip(SEG_META_COLS, row, strict=True))
        song = str(m["song_id"])
        seg_id = int(m["seg_id"])
        medoid = m["search_medoid_source_patch_idx"]
        searchable_count = int(m["searchable_count"])
        by_song.setdefault(song, []).append(
            SegmentSnapshot(
                seg_id=seg_id,
                medoid_source_patch_idx=int(medoid) if medoid is not None else -1,
                member_count=searchable_count,
                absorbed_outlier_count=int(m["absorbed_count"]),
                membership_rows=searchable_count,
            )
        )
    songs = tuple(
        SongSnapshot(song_id=song, segments=tuple(sorted(seg_list, key=lambda s: s.seg_id)))
        for song, seg_list in sorted(by_song.items())
    )
    return ConfigSnapshot(config_id=config_id, songs=songs)


def capture_catalog_structure(con) -> Mapping[int, ConfigSnapshot]:
    """Snapshot the exact per-song structure of every COMPACT config row present.

    Reads the compact ``seg_config`` (all rows are canonical — there is no
    ``alias_of_config_id``) and the compact ``seg_meta`` structural data.
    """
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
    # P1-S13 handle-form linkage + snapshot-representation evidence (empty on the plain
    # :func:`build_catalog_report` output, populated by the §C ``catalog_report(con, catalog)``
    # form).  The handle report surfaces exact/search snapshot hashes, never a whole-catalog
    # search-view identity (DD L258/L266 — ``search_representation_hash`` semantics and the
    # ``search_view_hash`` removal owned by Plan D P1-S2).
    catalog_id: str = ""
    catalog_root: str = ""
    exact_hash: str = ""
    search_hash: str = ""

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
    """Return the latest (or given) ``catalog`` row from the COMPACT run_provenance table.

    The compact snapshot's ``run_provenance`` (``catalog_storage.RUN_PROVENANCE_COLS``) is
    reserved for the catalog build, but the producer never writes a row into it — build
    provenance lives on the ``catalog_metadata`` singleton and, once published, in the
    ``catalog.manifest.json`` capsule.  The report surfaces the owning run only when a row
    exists; empty snapshots yield ``{}``.
    """
    col_csv = ", ".join(RUN_PROVENANCE_COLS)
    if run_id is not None:
        rows = con.execute(
            f"SELECT {col_csv} FROM {RUN_PROVENANCE_TABLE} WHERE run_id = ? ORDER BY started_at_ms",
            [run_id],
        ).fetchall()
    else:
        rows = con.execute(f"SELECT {col_csv} FROM {RUN_PROVENANCE_TABLE} ORDER BY started_at_ms").fetchall()
    catalog_rows = [dict(zip(RUN_PROVENANCE_COLS, r, strict=True)) for r in rows if str(r[1]) == "catalog"]
    return catalog_rows[-1] if catalog_rows else {}


def _read_all_compact_configs(con) -> dict[int, dict]:
    """Every COMPACT ``seg_config`` row as a dict keyed by ``config_id`` (all canonical)."""
    rows = con.execute(f"SELECT {', '.join(SEG_CONFIG_COLS)} FROM {SEG_CONFIG_TABLE} ORDER BY config_id").fetchall()
    return {int(r[0]): dict(zip(SEG_CONFIG_COLS, r, strict=True)) for r in rows}


def _derive_transient_collapse(con, configs: dict[int, dict]) -> tuple[tuple[int, ...], dict[int, int]]:
    """Derive alias/collapse evidence TRANSIENTLY from the current search leaves (DD L266).

    Delegates to the single source of truth :func:`collapse_search_representations` (shared
    with the Plan D analysis path) so report and analyze collapse identically: configs whose
    per-song search leaves are identical collapse to one scorer execution, the lowest
    ``config_id`` is the representative (canonical) and every other member reports to it as a
    transient alias.  No durable alias graph or ``alias_of_config_id`` is read or written.
    """
    valid = set(configs)
    classes = [c for c in collapse_search_representations(con) if any(m in valid for m in c.config_ids)]
    canonical_ids: list[int] = []
    alias_targets: dict[int, int] = {}
    for cls in classes:
        canonical_ids.append(cls.canonical_config_id)
        for alias_id in cls.alias_ids:
            if alias_id in valid:
                alias_targets[alias_id] = cls.canonical_config_id
    return tuple(sorted(canonical_ids)), alias_targets


def build_catalog_report(
    con,
    *,
    schema_version: int,
    run_id: str | None = None,
    baseline_structure: Mapping[int, ConfigSnapshot] | None = None,
) -> CatalogReport:
    """Generate the catalog report (P4-S4) over the COMPACT durable snapshot.

    *con* is the compact snapshot connection (``CatalogHandle.con`` — the §C
    ``catalog_report(con, catalog: CatalogHandle)`` target).  Reads compact ``seg_config`` /
    ``catalog_song`` / ``seg_meta``; alias/collapse evidence is derived transiently from the
    current search leaves (never a durable alias graph).  Uses *baseline_structure* (a prior
    :func:`capture_catalog_structure` snapshot) to compute observed medoid-index and structural
    changes; when none is supplied the report exposes the current ``config_snapshots`` and no
    baseline diff.
    """
    fingerprint = catalog_fingerprint(con, schema_version=schema_version)

    configs = _read_all_compact_configs(con)
    canonical_config_ids, alias_targets = _derive_transient_collapse(con, configs)
    alias_entries = tuple((int(alias_id), int(canonical)) for alias_id, canonical in sorted(alias_targets.items()))
    canonical_set = set(canonical_config_ids)
    canonical_configs = tuple(configs[cid] for cid in canonical_config_ids)
    alias_configs = tuple(configs[cid] for cid in sorted(configs) if cid not in canonical_set)

    # Per-config content from compact seg_meta: segment count, exact searchable membership
    # (recomputed as the sum of ``searchable_count`` — no per-patch membership rows are
    # invented), and absorbed-outlier total.  Empty songs are the config's metadata-only
    # (zero-searchable) cataloged songs.
    content: list[dict] = []
    empty_songs: list[tuple[int, str]] = []
    for config_id in sorted(configs):
        backbone = str(configs[config_id]["backbone"])
        seg_rows = int(
            con.execute(f"SELECT count(*) FROM {SEG_META_TABLE} WHERE config_id = ?", [config_id]).fetchone()[0]
        )
        (searchable_total, absorbed_total) = con.execute(
            f"SELECT coalesce(sum(searchable_count), 0), coalesce(sum(absorbed_count), 0) "
            f"FROM {SEG_META_TABLE} WHERE config_id = ?",
            [config_id],
        ).fetchone()
        metadata_songs = [
            str(r[0])
            for r in con.execute(
                f"SELECT song_id FROM {CATALOG_SONG_TABLE} "
                "WHERE config_id = ? AND status = 'metadata_only' ORDER BY song_id",
                [config_id],
            ).fetchall()
        ]
        content.append(
            {
                "config_id": config_id,
                "backbone": backbone,
                "segments": seg_rows,
                "membership_rows": int(searchable_total),
                "absorbed_outliers": int(absorbed_total),
            }
        )
        empty_songs.extend((config_id, song_id) for song_id in metadata_songs)

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
        canonical_config_ids=canonical_config_ids,
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


def _catalog_schema_version(con) -> int:
    """The snapshot's recorded ``catalog_metadata.schema_version`` (fallback = semantics version)."""
    try:
        row = con.execute(f"SELECT schema_version FROM {CATALOG_METADATA_TABLE} ORDER BY created_at_ms").fetchone()
    except Exception:  # pragma: no cover - defensive (schema missing)
        return CATALOG_SEMANTICS_VERSION
    return int(row[0]) if row is not None else CATALOG_SEMANTICS_VERSION


def catalog_report(con, catalog) -> CatalogReport:
    """The §C handle-form catalog report: ``catalog_report(con, catalog) -> CatalogReport``.

    *con* is the compact snapshot connection (``catalog.con``) and *catalog* is the
    ``CatalogHandle`` whose ``catalog_id`` / ``root`` the report links.  Reads the compact
    ``seg_config`` / ``catalog_song`` / ``seg_meta`` and produces the structural-change,
    outlier/silence (``absorbed_count`` + metadata-only ``empty_songs``), observed-medoid
    (``config_snapshots``), searchable-weight (``membership_rows``), exact/search snapshot-hash,
    and transient alias/collapse evidence.  It surfaces the published catalog's exact/search
    representation hashes and its durable id/root, and surfaces NO whole-catalog search-view
    identity: the report hash axis is ``exact_hash`` / ``search_hash``.
    """
    schema_version = _catalog_schema_version(con)
    base = build_catalog_report(con, schema_version=schema_version, baseline_structure=None)
    exact_hash, search_hash = snapshot_leaf_hashes(con)
    catalog_root = getattr(catalog, "root", None)
    return replace(
        base,
        catalog_id=str(getattr(catalog, "catalog_id", "")),
        catalog_root=str(catalog_root) if catalog_root is not None else "",
        exact_hash=exact_hash,
        search_hash=search_hash,
    )


def report_to_text(report: CatalogReport) -> str:
    """Render a human-readable listing (used by tests/docs; the CLI phase is Plan E)."""
    lines: list[str] = ["catalog-report", f"catalog_fingerprint={report.catalog_fingerprint}"]
    if report.exact_hash:
        lines.append(f"exact_hash={report.exact_hash}")
        lines.append(f"search_hash={report.search_hash}")
        lines.append(f"catalog_id={report.catalog_id}")
    lines.append(
        f"canonical configs ({len(report.canonical_config_ids)}): "
        + ", ".join(str(cid) for cid in report.canonical_config_ids),
    )
    lines.extend(
        f"  config {cfg['config_id']}: backbone={cfg['backbone']} bin_mode={cfg['bin_mode']} "
        f"semantics={cfg['threshold_semantics']} "
        f"configured={canonical_float(float(cfg['threshold_configured']))} "
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
