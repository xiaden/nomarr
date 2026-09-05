"""Shared pytest fixtures for embedding research tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb
import pytest

from scripts.embedding_research.db._schema import ensure_schema

if TYPE_CHECKING:
    from pathlib import Path


class CompactCatalogHarness:
    """Result of the shared :func:`build_compact_catalog` fixture contract.

    A built-and-opened compact catalog snapshot with BOTH connections a reader suite
    needs, respecting DuckDB's single-writer rule (exactly one live handle per snapshot
    per process unless all handles are ``read_only``).

    Attributes
    ----------
    handle:
        The :class:`~scripts.embedding_research.catalog_storage.CatalogHandle` returned by
        ``catalog_storage.open_snapshot_file(snapshot_path)``.  Its ``handle.con`` is the
        connection for COMPACT catalog reads (``seg_config`` / ``catalog_song`` /
        ``seg_meta`` / ``catalog_metadata``) via the P1-S6(a) ``compact_*`` read helpers.
    report:
        The :class:`~scripts.embedding_research.catalog.CatalogBuildReport` returned by
        ``build_segmentation_catalog`` (``verify=True``; ``report.verify_ok`` is True).
    research_con:
        The research DuckDB connection on which streams were published/reconciled; retain
        it for ``run_provenance`` / ``analyze_metrics`` and other research-DB writes.
    output_root:
        The filesystem root the stream artifacts and the snapshot were published under.
    snapshot_path:
        Absolute path to the opened ``catalog.duckdb`` compact snapshot file.
    stream_store:
        The :class:`~scripts.embedding_research.streams.StreamStore` used to publish +
        reconcile the streams (its ``output_root`` equals ``output_root``).
    resolver:
        ``make_current_stream_resolver(stream_store)`` — the exact store-backed current-
        stream seam the P1-S5 producer consumed.
    mask_store:
        The read-only per-song silence-mask provider used to build this catalog
        (``.load(song_id) -> uint8[P] | None``).  ``mask_store.load`` returns the exact mask
        passed in via *masks* (``None`` => no silent patches).  P1-S10's head-analysis
        runner accepts the same duck so mask-injected tests exercise silence exclusion
        consistently between the catalog build and the head reader.
    """

    def __init__(
        self,
        handle: Any,
        report: Any,
        research_con: Any,
        output_root: Path,
        snapshot_path: Path,
        stream_store: Any,
        resolver: Any,
        mask_store: Any = None,
    ) -> None:
        self.handle = handle
        self.report = report
        self.research_con = research_con
        self.output_root = output_root
        self.snapshot_path = snapshot_path
        self.stream_store = stream_store
        self.resolver = resolver
        self.mask_store = mask_store

    def close(self) -> None:
        """Close the snapshot handle (releases its DuckDB connection)."""
        self.handle.close()

    @property
    def con(self):
        """The compact snapshot connection for catalog reads (``handle.con``)."""
        return self.handle.con

    def mask(self, song_id: str):
        """Read-only per-song silence mask used for *song_id* (``None`` => no silence).

        Returns exactly what ``mask_store.load(song_id)`` returns — the ``uint8[P]`` mask
        passed in via *masks* at build time, or ``None`` when the song has no silent
        patches.  Intended so mask-injected tests can feed ``harness.mask_store`` to the
        head-analysis runner and observe the same silence exclusion the catalog build used.
        """
        if self.mask_store is None:
            return None
        return self.mask_store.load(song_id)


class _ResearchMaskStore:
    """mask_store duck for the fixture: ``.load(song_id) -> uint8[P] | None``.

    The research layer has NO committed masks, so by default every song is fully
    searchable (``load`` returns ``None`` => no silent patches).  Tests may inject explicit
    per-song masks via ``masks`` to drive silence semantics.  A ``None`` value in *masks*
    also means "no silence".
    """

    def __init__(self, masks: dict[str, Any] | None = None) -> None:
        self._masks = dict(masks or {})

    def load(self, song_id: str):
        if song_id in self._masks:
            return self._masks[song_id]
        return None


class _FixtureMaskStoreDuck:
    """Concrete per-song mask store used by :func:`build_compact_catalog`."""

    def __init__(self, masks: dict[str, Any]) -> None:
        self._store = _ResearchMaskStore(masks)

    def load(self, song_id: str):
        return self._store.load(song_id)


def publish_current_catalog(output_root, run_id: str) -> str:
    """Durably publish the staged compact catalog under ``catalogs/.staging-<run_id>/``.

    Checkpoint-clean-close the staged snapshot, derive its manifest, publish it under
    ``catalogs/<catalog_id>/`` and write ``catalogs/current.json`` LAST (DD L268-287).
    Returns the published ``catalog_id``.
    """
    from pathlib import Path

    from scripts.embedding_research import catalog_storage as _cs

    output_root = Path(output_root)
    staging_dir = output_root / "catalogs" / f".staging-{run_id}"
    derive_con = duckdb.connect(str(staging_dir / _cs.CATALOG_DB_FILE), read_only=True)
    try:
        manifest = _cs.derive_catalog_manifest(derive_con)
    finally:
        derive_con.close()
    pub_handle = _cs.publish_catalog_snapshot(staging_dir, manifest=manifest)
    catalog_id = pub_handle.catalog_id
    pub_handle.close()
    return catalog_id


def build_compact_catalog(
    research_con,
    output_root,
    *,
    streams: dict[tuple[str, str], Any],
    configs: list[Any],
    song_ids: list[str] | None = None,
    masks: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> CompactCatalogHarness:
    """The shared category-(b) / (c) fixture contract (P1-S6(a)).

    Builds ONE real compact catalog snapshot through the exact P1-S5 producer seam and
    opens it once through ``catalog_storage.open_snapshot_file``.  The contract steps:

    (a) publish every ``(song_id, backbone)`` matrix via ``StreamStore.publish`` on
        *research_con* (schema must already include the retained stream registry DDL, e.g.
        the ``con`` fixture), then ``StreamStore.reconcile()`` so the rows are ``ready``;
    (b) run ``catalog.build_segmentation_catalog(
            make_current_stream_resolver(StreamStore(research_con, output_root)),
            mask_store, configs, song_ids, output_root=output_root,
            run_id=run_id, verify=True)``;
    (c) open the published snapshot via ``catalog_storage.open_snapshot_file(...)`` and
        return a :class:`CompactCatalogHarness`.

    Callers should read compact rows through ``handle.con`` (compact ``con``) and keep
    *research_con* for ``run_provenance`` / analysis writes.  DuckDB single-writer rule:
    this fixture holds ONE live handle to the snapshot; tests that open a second handle to
    the same snapshot (e.g. an export/import round-trip copy) should close it before any
    write or open the extra handle ``read_only=True``.
    """
    import uuid
    from pathlib import Path

    import numpy as np

    from scripts.embedding_research import catalog
    from scripts.embedding_research.catalog_storage import open_snapshot_file
    from scripts.embedding_research.streams import StreamStore, make_current_stream_resolver

    output_root = Path(output_root)
    if run_id is None:
        run_id = f"fixture-{uuid.uuid4().hex[:12]}"
    song_ids = list(song_ids) if song_ids is not None else sorted({s for (s, _b) in streams})

    # (a) publish streams via StreamStore + reconcile on the research connection.
    store = StreamStore(research_con, output_root=str(output_root))
    for (song_id, backbone), matrix in streams.items():
        matrix = np.ascontiguousarray(matrix, dtype=np.float32)
        store.publish(song_id, backbone, matrix, run_id=run_id)
    store.reconcile()

    # (b) build the compact snapshot via the P1-S5 producer (mask_store = no committed masks).
    resolver = make_current_stream_resolver(store)
    mask_store = _FixtureMaskStoreDuck(masks)
    report = catalog.build_segmentation_catalog(
        resolver,
        mask_store,
        list(configs),
        song_ids,
        output_root=str(output_root),
        run_id=run_id,
        verify=True,
    )

    # (c) durably publish the staged snapshot (catalogs/<catalog_id>/ + current.json
    #     authoritative) per the DD L268-287 publication protocol, then open the published
    #     catalog once through catalog_storage.open_snapshot_file.
    from scripts.embedding_research import catalog_storage as _cs

    catalog_id = publish_current_catalog(output_root, run_id)
    snapshot_path = output_root / "catalogs" / catalog_id / _cs.CATALOG_DB_FILE
    handle = open_snapshot_file(snapshot_path)
    return CompactCatalogHarness(
        handle=handle,
        report=report,
        research_con=research_con,
        output_root=output_root,
        snapshot_path=snapshot_path,
        stream_store=store,
        resolver=resolver,
        mask_store=mask_store,
    )


@pytest.fixture
def compact_catalog_factory():
    """Factory returning the shared :func:`build_compact_catalog` fixture contract.

    Used by the category-(b) suites (test_catalog_identity / test_catalog_report /
    test_search_views / test_catalog_analysis / test_scale_catalog_analysis) and P1-S10's
    category-(c) migration.  The fixture returns the callable; call it with a research
    ``con`` (usually the ``con`` fixture) plus a ``tmp_path`` output_root:

    .. code-block:: python

        harness = compact_catalog_factory(
            con, tmp_path, streams={("s1", "effnet"): mat}, configs=[cfg], song_ids=["s1"]
        )
        cfg_rows = catalog.compact_configs_by_backbone(harness.con, "effnet")
        seg_rows = catalog.compact_segments_by_config_song(harness.con, cfg_rows[0].config_id, "s1")
        harness.close()

    Documented contract: ``harness.con`` for compact catalog reads; ``harness.research_con``
    for ``run_provenance`` / ``analyze_metrics`` writes; one live handle per snapshot unless
    all read-only.
    """
    return build_compact_catalog


@pytest.fixture
def con():
    """In-memory DuckDB connection with full schema applied."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    yield connection
    connection.close()


def pytest_configure(config: pytest.Config) -> None:
    """Register the pytest markers used by the retained research suite.

    ``sigkill_bookkeeping`` marks tests that simulate an interrupted durable
    publication and assert only the registry/bookkeeping consequences; the
    separately marked opt-in ``blocklayer_durability`` test owns true power-loss
    durability.  The corrective-pass hard cut removed the ``legacy_scaled``
    two-track marker along with the ``std_scaled``/calibration/CTP semantics it
    gated, so no scaled-threshold marker is registered anymore.

    ``scale`` / ``local_filesystem`` tag the DD verification-matrix synthetic
    10,000 x 100 x 10 (~10M compact-row) DuckDB durability/shape guard and other
    local-filesystem-only fixtures: they run in the default suite (no ``-m``
    exclusion) but are explicitly labelled so a downstream scale/local-only gate
    can select or deselect them without inference, audio, or CUDA.
    """
    config.addinivalue_line(
        "markers",
        "sigkill_bookkeeping: simulates an interrupted durable publication (an injected "
        "fault / subprocess kill at a stage of the write-proxy seam) and asserts ONLY the "
        "registry/bookkeeping consequences (leftover staging .tmp, no pending/ready row for "
        "the interrupted artifact, prior ready artifacts unaffected, partial run_provenance). "
        "These are NOT power-loss durability proof (a kill cannot prove fsync reached stable "
        "storage); the separately-marked opt-in blocklayer_durability test owns durability.",
    )
    config.addinivalue_line(
        "markers",
        "blocklayer_durability: OPT-IN power-loss / block-layer replay durability test. NOT "
        "part of the default suite (no block-layer replay infrastructure exists); a skipped "
        "placeholder asserts the label and skip reason. SIGKILL tests are meaningful without it.",
    )
    config.addinivalue_line(
        "markers",
        "scale: synthetic large-scale (~10M compact-row) DuckDB durability/shape fixture. "
        "Runs in the default suite; local-filesystem only (no inference/audio/CUDA).",
    )
    config.addinivalue_line(
        "markers",
        "local_filesystem: exercises a durable filesystem DuckDB snapshot under a tmp_path "
        "output root; never the disposable research DB. Runs in the default suite.",
    )
