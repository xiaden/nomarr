"""P1-S1 spec-first: the tiny deterministic fixture + its hand-computed corpus semantics.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S1.  These tests are GREEN now and own the *fixture construction* the
later steps drive through the real CLI.  They pin, with EXPLICIT SYNTHETIC literals (no value
is derived at runtime from the implementation under test):

1. corpus shape: 8 effnet songs, one committed stream + aligned committed mask + identity group
   per song; config surface 3 thresholds;
2. search-representation collapse: the two alias thresholds (0.9 / 1.0) form ONE alias class over
   every corpus song (identical per-song search leaves, identical search hash, DISTINCT exact
   segmentation hashes) while the distinct threshold (0.2) is a separate class that never unions;
3. the silent RUN is excluded from searchable inputs/medoids (``sil`` mask zeros at 1,2 -> 3 of 5
   patches searchable, medoid source 0);
4. the absorbed outlier is retained structurally but contributes zero searchable mass (``abs``
   absorbed_indices == (2,), absorbed_count 1, 5 searchable);
5. the hard split is an ordinary SEARCHABLE second segment (``hard`` -> weights 1/3 + 2/3 = 1);
6. per-song weights normalise to one wherever the song is searchable;
7. the zero-searchable song (``z0``) keeps catalog metadata (status ``metadata_only``, no
   ``seg_meta`` rows) and is excluded from the baseline population;
8. the observed EffNet global-medoid baseline population is silence-aware (7 songs; ``z0``
   absent) and each song's observed global medoid source index matches the frozen literal.

Later steps (P1-S2+) build on :func:`build_deterministic_fixture` /
:class:`FixtureHarness` for the real CLI dispatch, provenance, verify/reindex, disposable-DB
deletion, and reset/byte-preservation proofs — none of which are implemented here.
"""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.helpers.segmentation import observed_global_medoid
from scripts.embedding_research.tests.fixture_cli_harness import (
    ALIAS_THRESHOLDS,
    ALL_THRESHOLDS,
    BACKBONE,
    BASELINE_MEDOID_SOURCE,
    DISTINCT_THRESHOLDS,
    SEARCHABLE_SONGS,
    SILENCE_MASKS,
    SONGS,
    build_deterministic_fixture,
    head_bytes,
    song_mask,
    stream_matrix,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    """Build the deterministic corpus once (module scope) and yield its harness.

    Uses its own module-scoped research DuckDB connection (the shared ``con`` fixture is
    function-scoped, but committed groups must survive the whole module for later steps).
    """
    research_con = duckdb.connect(":memory:")
    ensure_schema(research_con)
    out = tmp_path_factory.mktemp("det-fixture")
    harness = build_deterministic_fixture(research_con, out)
    try:
        yield harness
    finally:
        harness.close()


def _threshold_of(fixture, config_id: int) -> float:
    for row in fixture.config_rows():
        if row.config_id == config_id:
            return float(row.threshold_effective)
    raise KeyError(config_id)


def _class_threshold_sets(fixture):
    """Map each collapse class to the set of its thresholds."""
    classes = fixture.search_classes()
    out = []
    for cls in classes:
        thresholds = tuple(sorted(_threshold_of(fixture, cid) for cid in cls.config_ids))
        out.append((thresholds, cls))
    return out


# --------------------------------------------------------------------------- #
# 1. Corpus shape + committed-group surface                                    #
# --------------------------------------------------------------------------- #
def test_corpus_shape_and_committed_config_surface(fixture):
    """8 songs, one effnet committed stream+mask group each; 3 thresholds on the catalog."""
    assert fixture.searchable_song_ids() == list(SEARCHABLE_SONGS)
    configs = fixture.config_rows()
    assert len(configs) == len(ALL_THRESHOLDS) == 3
    thresholds = sorted(float(r.threshold_effective) for r in configs)
    assert thresholds == sorted(ALL_THRESHOLDS)
    # one stream + committed mask group per song, all effnet.
    for song in SONGS:
        n = stream_matrix(song).shape[0]
        mask = song_mask(song)
        assert mask.shape == (n,), f"{song} mask/stream length mismatch"
        assert set(mask).issubset({0, 1})
    # every searchable song present in the catalog across every config; z0 is metadata-only.
    for th in ALL_THRESHOLDS:
        songs = {
            r[0]
            for r in fixture.con.execute(
                "SELECT song_id FROM catalog_song WHERE config_id=?", (fixture.config_row(th).config_id,)
            ).fetchall()
        }
        assert songs == set(SONGS)


# --------------------------------------------------------------------------- #
# 2. Search-representation alias class + distinct class                        #
# --------------------------------------------------------------------------- #
def test_alias_and_distinct_search_classes(fixture):
    """0.9/1.0 collapse to one alias class; 0.2 is a distinct class that never unions."""
    by_th = dict(_class_threshold_sets(fixture))
    # exactly two classes whose threshold memberships are the alias pair and the distinct one.
    assert set(map(frozenset, by_th)) == {frozenset(ALIAS_THRESHOLDS), frozenset(DISTINCT_THRESHOLDS)}
    alias_cls = by_th[tuple(sorted(ALIAS_THRESHOLDS))]
    distinct_cls = by_th[tuple(sorted(DISTINCT_THRESHOLDS))]
    # alias class: two configs, one canonical representative (0.9 or 1.0 — hash-order chosen) + alias.
    assert len(alias_cls.config_ids) == 2 and len(alias_cls.alias_ids) == 1
    canon_th = _threshold_of(fixture, alias_cls.canonical_config_id)
    assert canon_th in set(ALIAS_THRESHOLDS)
    assert _threshold_of(fixture, alias_cls.alias_ids[0]) in set(ALIAS_THRESHOLDS) - {canon_th}
    # distinct class is its own canonical with no alias.
    assert len(distinct_cls.config_ids) == 1 and not distinct_cls.alias_ids
    assert distinct_cls.canonical_config_id == distinct_cls.config_ids[0]


def test_alias_pair_identical_search_leaf_distinct_exact_hash(fixture):
    """0.9/1.0 produce the same search leaf but different exact segmentation hash."""
    from scripts.embedding_research.catalog_identity import (
        exact_segmentation_hash,
        search_representation_hash,
    )

    cid_low = fixture.config_row(ALIAS_THRESHOLDS[0]).config_id
    cid_high = fixture.config_row(ALIAS_THRESHOLDS[1]).config_id
    assert search_representation_hash(fixture.con, cid_low) == search_representation_hash(fixture.con, cid_high)
    assert exact_segmentation_hash(fixture.con, cid_low) != exact_segmentation_hash(fixture.con, cid_high)


def test_alias_pair_identical_structure_over_every_song(fixture):
    """Every corpus song segments identically under 0.9 and 1.0 (source of the collapse)."""
    lo, hi = ALIAS_THRESHOLDS
    for song in SONGS:
        shape_lo = [
            (s.start_idx, s.end_idx, tuple(s.absorbed_indices), s.searchable_count) for s in fixture.segments(lo, song)
        ]
        shape_hi = [
            (s.start_idx, s.end_idx, tuple(s.absorbed_indices), s.searchable_count) for s in fixture.segments(hi, song)
        ]
        assert shape_lo == shape_hi, f"{song} segments differ between alias thresholds"


def test_distinct_class_never_collapses_with_alias(fixture):
    """0.2's search hash differs from the alias class (a genuinely distinct search class)."""
    from scripts.embedding_research.catalog_identity import search_representation_hash

    alias_cid = fixture.config_row(ALIAS_THRESHOLDS[0]).config_id
    distinct_cid = fixture.config_row(DISTINCT_THRESHOLDS[0]).config_id
    assert search_representation_hash(fixture.con, distinct_cid) != search_representation_hash(fixture.con, alias_cid)


# --------------------------------------------------------------------------- #
# 3. Silent RUN excluded from searchable inputs / medoid                       #
# --------------------------------------------------------------------------- #
def test_silent_run_excluded_from_searchable_inputs(fixture):
    """``sil`` keeps its structural range but the silent run contributes zero searchable mass."""
    th = ALIAS_THRESHOLDS[0]
    segs = fixture.segments(th, "sil")
    assert len(segs) == 1
    seg = segs[0]
    # mask zeros the run at indices 1,2 of a 5-patch stream -> only 0,3,4 searchable.
    assert SILENCE_MASKS["sil"].tolist() == [1, 0, 0, 1, 1]
    assert seg.searchable_count == 3  # 5 structural patches minus the silent run of 2
    assert seg.search_medoid_source_patch_idx == 0  # silent indices never become a medoid
    assert seg.searchable_weight == 1.0  # single searchable segment -> full song weight


# --------------------------------------------------------------------------- #
# 4. Absorbed outlier retained structurally, zero searchable mass              #
# --------------------------------------------------------------------------- #
def test_absorbed_outlier_excluded_from_searchable_mass(fixture):
    """``abs`` keeps the far excursion as a structural absorbed exception with no searchable mass."""
    th = ALIAS_THRESHOLDS[0]
    segs = fixture.segments(th, "abs")
    assert len(segs) == 1
    seg = segs[0]
    assert tuple(seg.absorbed_indices) == (2,)
    assert seg.absorbed_count == 1
    assert seg.start_idx == 0 and seg.end_idx == 6
    # 6 structural patches minus the single absorbed outlier -> 5 searchable (never the outlier).
    assert seg.searchable_count == 5
    assert seg.searchable_weight == 1.0
    # The absorbed source index is never the searchable medoid.
    assert seg.search_medoid_source_patch_idx != 2


# --------------------------------------------------------------------------- #
# 5. Hard split is an ordinary SEARCHABLE segment                              #
# --------------------------------------------------------------------------- #
def test_hard_split_is_searchable_with_normalized_weights(fixture):
    """``hard``'s far excursion exceeds OUTLIER_WINDOW and becomes a searchable second segment."""
    th = ALIAS_THRESHOLDS[0]
    segs = fixture.segments(th, "hard")
    assert len(segs) == 2
    seg0, seg1 = segs
    assert (seg0.start_idx, seg0.end_idx) == (0, 2)
    assert seg0.searchable_count == 2
    assert seg0.search_medoid_source_patch_idx == 0
    # The 4-far-patch excursion is searchable (NOT absorbed): it is its own segment.
    assert (seg1.start_idx, seg1.end_idx) == (2, 6)
    assert seg1.searchable_count == 4
    assert seg1.search_medoid_source_patch_idx == 2
    assert not seg1.absorbed_indices
    # weights 2/6 and 4/6 -> explicit literals that sum to one.
    assert seg0.searchable_weight == pytest.approx(1.0 / 3.0)
    assert seg1.searchable_weight == pytest.approx(2.0 / 3.0)


# --------------------------------------------------------------------------- #
# 6. Weights normalise to one per song                                         #
# --------------------------------------------------------------------------- #
def test_searchable_weights_normalize_to_one(fixture):
    """For every song/config pair with a searchable medoid, the segment weights sum to one."""
    for th in ALL_THRESHOLDS:
        for song in SEARCHABLE_SONGS:
            segs = fixture.segments(th, song)
            assert segs, f"{song}@{th} should be searchable"
            total = sum(float(s.searchable_weight) for s in segs)
            assert total == pytest.approx(1.0), f"{song}@{th} weights do not sum to one"


# --------------------------------------------------------------------------- #
# 7. Zero-searchable song retains metadata, excluded from search/baseline      #
# --------------------------------------------------------------------------- #
def test_zero_searchable_song_metadata_retained_and_excluded(fixture):
    """``z0`` stays in the catalog (metadata_only) but has no searchable segments / baseline slot."""
    for th in ALL_THRESHOLDS:
        cid = fixture.config_row(th).config_id
        row = fixture.con.execute(
            "SELECT status, total_searchable_count FROM catalog_song WHERE config_id=? AND song_id='z0'",
            [int(cid)],
        ).fetchone()
        assert row == ("metadata_only", 0), f"z0 not metadata_only under threshold {th}"
        assert fixture.segments(th, "z0") == [], "z0 must have no structural searchable segment rows"
    assert "z0" not in SEARCHABLE_SONGS


# --------------------------------------------------------------------------- #
# 8. Observed EffNet global-medoid baseline population (silence-aware)         #
# --------------------------------------------------------------------------- #
def test_observed_global_medoid_baseline_population():
    """The baseline population is the 7 searchable songs; per-song medoids match the frozen literals."""
    # silence-aware population = whole-song mask==1 source indices.
    for song in SONGS:
        mask = song_mask(song)
        population = [i for i in range(len(mask)) if mask[i] == 1]
        med = observed_global_medoid(stream_matrix(song), population)
        expected = BASELINE_MEDOID_SOURCE[song]
        if song == "z0":
            assert population == [] and expected is None
            assert med.source_index is None  # zero-searchable contributes no baseline medoid
        else:
            assert population, f"{song} should be searchable"
            assert med.source_index == expected, f"{song} baseline medoid source mismatch"
    # exactly the searchable songs populate the baseline; z0 is absent.
    assert {s for s in SONGS if BASELINE_MEDOID_SOURCE[s] is not None} == set(SEARCHABLE_SONGS)


# --------------------------------------------------------------------------- #
# Structural accessors + injected head bytes for later steps                   #
# --------------------------------------------------------------------------- #
def test_injected_head_bytes_are_deterministic_and_explicit(fixture):
    """Each song carries fixed, distinct injected head inference bytes (never a real model)."""
    from scripts.embedding_research.tests.fixture_cli_harness import DIM, HEAD_COUNT

    seen: set[str] = set()
    for song in SONGS:
        hb = head_bytes(song)
        assert hb.shape == (HEAD_COUNT, DIM)
        digest = hb.tobytes()
        assert digest not in seen, "head bytes must be distinct per song"
        seen.add(digest)
    # head_bytes is the pure injected source; the harness exposes the same constant surface.
    assert fixture.searchable_song_ids() == list(SEARCHABLE_SONGS)
    assert BACKBONE == "effnet"
