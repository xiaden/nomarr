"""Persistence-backed lifecycle tests for tag-curation *natural* identity.

System under test: the natural facade (``db.library.*``) and the curation
service (``TaggingService``) against a **real migrated PostgreSQL**. These
tests prove that public tag identity is the complete ``(namespace, name,
value)`` TagRef (never the storage primary key), that relinking is atomic and
duplicate-safe, that concurrent curation is safe or deterministically rejected,
and that identity stays stable across fresh sessions, pagination and rename —
per the ``CONTRACTS.md`` "Lifecycle contract".

These are persistence/integration tests (marker ``requires_database``); they
run in the ``database-tests`` CI tier. Locally they run against a bootstrapped
PostgreSQL 17 via ``NOMARR_TEST_DB_URL`` (see ``conftest.py``).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

from nomarr.helpers.constants.file_states import (
    STATE_NOT_HYDRATED,
    STATE_PROCESSED,
    STATE_TAGS_CURRENT,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.helpers.tag_handle_codec import decode_tag_handle, encode_tag_handle
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database
from nomarr.services.domain.tagging_svc import TaggingService
from nomarr.services.domain.tagging_svc.config import TaggingServiceConfig

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [pytest.mark.integration, pytest.mark.requires_database]

GENRE = TagRef(name="genre", value="rock", namespace="default")
JAZZ = TagRef(name="genre", value="jazz", namespace="default")
BLUES = TagRef(name="genre", value="blues", namespace="default")


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _svc(db: Database) -> TaggingService:
    """Build a curation service bound to a real Database.

    The curation methods under test only touch ``self.db``; the service's own
    ``bts``/``config_service`` collaborators are irrelevant here and are stubbed
    with mocks exactly as the existing curation unit tests do.
    """
    return TaggingService(
        database=db,
        cfg=TaggingServiceConfig(models_dir="models", namespace="nom", version_tag_key="nom:version"),
        bts=MagicMock(),
        config_service=MagicMock(),
    )


def _seed(db: Database, root: str = "/repo/curation", n: int = 3) -> tuple[Library, list[Any], list[int]]:
    """Seed a library with ``n`` songs carrying baseline write states.

    Returns ``(library, song_identities, song_ids)``.
    """
    name = f"cur_{root.strip('/').replace('/', '_')}"
    lib = db.library.create_library(Library(name=name, root_path=root))
    lib_ident = LibraryIdentity(name=lib.name, root_path=lib.root_path)
    now = now_ms().value
    identities: list[Any] = []
    paths: list[str] = []
    for i in range(n):
        path = f"{root}/track{i}.flac"
        scan = SongScanUpdate(normalized_path=path, file_size=1000 + i, modified_time=now, duration_seconds=180.0)
        identities.append(db.library.add_song_to_library(SongUpsertInput(library=lib_ident, path=path, scan=scan)))
        paths.append(path)
    song_ids: list[int] = []
    for p in paths:
        song = db.library.get_song_by_normalized_path(p, lib)
        assert song is not None, p
        song_ids.append(song.song_id)
    for sid in song_ids:
        db.app.set_song_state([sid], STATE_WRITTEN)
        db.app.set_song_state([sid], STATE_TAGS_CURRENT)
        db.app.set_song_state([sid], STATE_PROCESSED)
        db.app.set_song_state([sid], STATE_NOT_HYDRATED)
    return lib, identities, song_ids


def _tag(db: Database, song_identity: Any, pairs: list[tuple[str, object]]) -> None:
    """Assign ``default``-namespace tags (name, value) to one song."""
    db.library.replace_song_tags(
        song_identity,
        [SongTagAssignment(name=name, value=value) for name, value in pairs],
    )


def _songs_with(db: Database, identity: TagRef) -> set[int]:
    return {s.song_id for s in db.library.find_songs_with_tag(identity, limit=None)}


def _storage_engine(url: str) -> Any:
    """Raw read engine so assertions can observe storage rows directly."""
    return create_engine(url)


def _tag_row(engine: Any, identity: TagRef) -> tuple[int, str, object, str] | None:
    with engine.connect() as c:
        row = c.execute(
            text("SELECT id, name, value, namespace FROM tags WHERE name=:n AND value=:v AND namespace=:ns"),
            {"n": identity.name, "v": str(identity.value), "ns": identity.namespace},
        ).fetchone()
    if row is None:
        return None
    return (int(row[0]), row[1], row[2], row[3])


def _tag_row_required(engine: Any, identity: TagRef) -> tuple[int, str, object, str]:
    row = _tag_row(engine, identity)
    assert row is not None, f"expected a tag row for {identity}"
    return row


def _edges_of_tag(engine: Any, tag_id: int) -> list[int]:
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT song_id FROM song_tags WHERE tag_id=:t ORDER BY song_id"), {"t": tag_id}
        ).fetchall()
    return [int(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# P1-S1 — natural (namespace, name, value) identity drives every curation op
# ---------------------------------------------------------------------------


def test_lookup_and_song_resolution_use_complete_natural_identity(curation_db: Database) -> None:
    """get_tag / find_songs_with_tag address songs by complete natural identity."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock"), ("genre", "jazz")])
    _tag(curation_db, identities[1], [("genre", "rock")])

    assert _songs_with(curation_db, GENRE) == {song_ids[0], song_ids[1]}
    assert _songs_with(curation_db, JAZZ) == {song_ids[0]}

    got = curation_db.library.get_tag(GENRE)
    assert got is not None
    assert got.name == "genre" and got.value == "rock" and got.namespace == "default"

    # A tag in a different namespace (same name/value) is a different identity.
    other_ns = TagRef(name="genre", value="rock", namespace="nom")
    assert curation_db.library.get_tag(other_ns) is None
    assert _songs_with(curation_db, other_ns) == set()


def test_storage_pk_120_is_not_selectable_by_natural_value_120(curation_db: Database, curation_db_url: str) -> None:
    """Natural value '120' never selects a row by its storage PK being 120.

    R4 proof: a distinct tag whose *storage* primary key is 120 is not
    addressable by a natural probe for value '120' unless its
    ``(name, value, namespace)`` actually equals that.
    """
    _lib, identities, song_ids = _seed(curation_db)
    # A tag whose natural value is literally the string '120' (assigned to song0).
    _tag(curation_db, identities[0], [("genre", "120")])
    # A second tag with an unrelated natural value, but NO edges yet.
    curation_db.library.ensure_tag(TagRef(name="pitch", value="eleven", namespace="default"))

    engine = _storage_engine(curation_db_url)
    try:
        # Force the second tag's STORAGE PK to 120 to set up the coincidence.
        pitch_row = _tag_row(engine, TagRef(name="pitch", value="eleven", namespace="default"))
        assert pitch_row is not None
        with engine.begin() as c:
            c.execute(text("UPDATE tags SET id=120 WHERE id=:old"), {"old": pitch_row[0]})
        assert _tag_row_required(engine, TagRef(name="pitch", value="eleven", namespace="default"))[0] == 120

        # Natural lookup for value '120' under 'genre' finds the value-'120' tag,
        # never the PK-120 'pitch' row.
        value_120 = curation_db.library.get_tag(TagRef(name="genre", value="120", namespace="default"))
        assert value_120 is not None
        assert (value_120.name, value_120.value) == ("genre", "120")

        # The PK-120 row (name 'pitch', value 'eleven') is NOT found by a natural
        # '120' probe on its own name — even though its storage id is 120.
        assert curation_db.library.get_tag(TagRef(name="pitch", value="120", namespace="default")) is None
        # ... while its real natural value does resolve, by natural key only.
        assert curation_db.library.get_tag(TagRef(name="pitch", value="eleven", namespace="default")) is not None

        # Only the songs actually tagged with natural value '120' are returned.
        assert _songs_with(curation_db, TagRef(name="genre", value="120", namespace="default")) == {song_ids[0]}
        assert _songs_with(curation_db, TagRef(name="pitch", value="120", namespace="default")) == set()
    finally:
        engine.dispose()


def test_merge_uses_natural_identity_sources_removed(curation_db: Database) -> None:
    """merge_tags addresses canonical + sources by complete TagRef and drains sources."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock"), ("genre", "jazz")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    _tag(curation_db, identities[2], [("genre", "blues")])  # canonical already exists with song2

    res = _svc(curation_db).merge_tags([GENRE, JAZZ], BLUES)
    assert res["total_moved"] == 2  # rock song0+song1 -> blues
    assert res["sources_removed"] == 2  # rock and jazz both drained
    assert _songs_with(curation_db, BLUES) == {song_ids[0], song_ids[1], song_ids[2]}
    assert _songs_with(curation_db, GENRE) == set()
    assert _songs_with(curation_db, JAZZ) == set()


def test_split_moves_only_selected_songs_by_natural_identity(curation_db: Database) -> None:
    """split_tag restricts the move to the given songs, keyed off a natural source."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    _tag(curation_db, identities[2], [("genre", "rock")])

    res = _svc(curation_db).split_tag(GENRE, [str(song_ids[1])], "prog")
    assert res["moved"] == 1
    assert res["new_tag_created"] is True
    assert _songs_with(curation_db, GENRE) == {song_ids[0], song_ids[2]}
    assert _songs_with(curation_db, TagRef(name="genre", value="prog", namespace="default")) == {song_ids[1]}


# ---------------------------------------------------------------------------
# P1-S2 — collisions, duplicate-safe relinking, orphan cleanup, atomicity
# ---------------------------------------------------------------------------


def test_duplicate_safe_relink_no_duplicate_edges(curation_db: Database, curation_db_url: str) -> None:
    """Renaming a source that already shares a song with the target deletes the
    collision before re-pointing the rest; no song ends with two edges to one tag."""
    _lib, identities, song_ids = _seed(curation_db)
    # song0 has both rock and blues; song1 only rock; song2 only blues.
    _tag(curation_db, identities[0], [("genre", "rock"), ("genre", "blues")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    _tag(curation_db, identities[2], [("genre", "blues")])
    engine = _storage_engine(curation_db_url)
    try:
        res = _svc(curation_db).rename_tag(GENRE, "blues")
        # song0 rock edge collides with its existing blues edge -> skipped; song1 moved.
        assert res["moved"] == 1
        assert _songs_with(curation_db, BLUES) == {song_ids[0], song_ids[1], song_ids[2]}
        assert _songs_with(curation_db, GENRE) == set()

        blues_id = _tag_row_required(engine, BLUES)[0]
        edges = _edges_of_tag(engine, blues_id)
        assert edges == sorted({song_ids[0], song_ids[1], song_ids[2]})
        assert len(edges) == len(set(edges))  # no duplicate edges
        rock_row = _tag_row(engine, GENRE)
        if rock_row is not None:
            assert _edges_of_tag(engine, rock_row[0]) == []
    finally:
        engine.dispose()


def test_orphan_cleanup_removes_fully_moved_source(curation_db: Database) -> None:
    """After a full-move rename the source has no edges and is orphan-cleaned."""
    _lib, identities, _song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    svc = _svc(curation_db)
    res = svc.rename_tag(GENRE, "alternative")
    assert res["moved"] == 2
    assert _songs_with(curation_db, GENRE) == set()

    # The orphaned source row is gone after cleanup, so get_tag(old) -> None.
    assert curation_db.library.count_orphaned_tags() >= 1
    curation_db.library.admin_cleanup_orphaned_tags()
    assert curation_db.library.get_tag(GENRE) is None
    assert curation_db.library.count_orphaned_tags() == 0


def test_missing_source_target_raise_deterministic_errors_no_mutation(
    curation_db: Database, curation_db_url: str
) -> None:
    """Unknown source/canonical raise ValueError and leave the DB unchanged."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    ghost = TagRef(name="genre", value="ghost", namespace="default")
    engine = _storage_engine(curation_db_url)
    try:

        def _snapshot() -> list[tuple[int, int]]:
            with engine.connect() as c:
                return [
                    tuple(r) for r in c.execute(text("SELECT song_id, tag_id FROM song_tags ORDER BY song_id, tag_id"))
                ]

        before = _snapshot()
        svc = _svc(curation_db)
        with pytest.raises(ValueError, match="not found"):
            svc.rename_tag(ghost, "anything")
        with pytest.raises(ValueError, match="not found"):
            svc.merge_tags([ghost], GENRE)
        with pytest.raises(ValueError, match="not found"):
            svc.merge_tags([GENRE], ghost)
        with pytest.raises(ValueError, match="not found"):
            svc.split_tag(ghost, [str(song_ids[0])], "prog")
        assert _snapshot() == before
        assert curation_db.library.get_tag(GENRE) is not None
    finally:
        engine.dispose()


def test_idempotent_retry_rename_to_same_value_is_noop(curation_db: Database, curation_db_url: str) -> None:
    """Renaming a tag to its own value mutates nothing and reports moved=0."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    engine = _storage_engine(curation_db_url)
    try:
        before = _edges_of_tag(engine, _tag_row_required(engine, GENRE)[0])
        res = _svc(curation_db).rename_tag(GENRE, "rock")
        assert res["moved"] == 0
        assert res["merged_into_existing"] is False
        assert _songs_with(curation_db, GENRE) == {song_ids[0]}
        assert _edges_of_tag(engine, _tag_row_required(engine, GENRE)[0]) == before
    finally:
        engine.dispose()


def test_write_pending_transitions_persist_after_rename(curation_db: Database) -> None:
    """Songs under a renamed tag flip written->not_written, tags_current->tags_not_fresh."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    assert "written" in curation_db.app.song_state_membership(song_ids[0])
    assert "tags_current" in curation_db.app.song_state_membership(song_ids[0])

    _svc(curation_db).rename_tag(GENRE, "alternative")
    for sid in song_ids[:2]:
        mem = curation_db.app.song_state_membership(sid)
        assert "not_written" in mem
        assert "tags_not_fresh" in mem
    mem2 = curation_db.app.song_state_membership(song_ids[2])
    assert "written" in mem2
    assert "tags_current" in mem2


def test_failed_post_relink_step_leaves_consistent_edges_and_retry_recovers(
    curation_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An injected failure after the cross-tag relink leaves no partial edge
    mutation; a retry completes the write-pending marking (idempotent recovery)."""
    _lib, identities, song_ids = _seed(curation_db)
    _tag(curation_db, identities[0], [("genre", "rock")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    svc = _svc(curation_db)

    def _boom(song_id: int) -> None:
        raise RuntimeError("injected write-pending failure")

    monkeypatch.setattr(svc, "_mark_song_write_pending", _boom)

    with pytest.raises(RuntimeError, match="injected"):
        svc.rename_tag(GENRE, "alternative")

    # Cross-tag edge relink is complete and consistent (no partial cross-tag state).
    alt = TagRef(name="genre", value="alternative", namespace="default")
    assert _songs_with(curation_db, alt) == {song_ids[0], song_ids[1]}
    assert _songs_with(curation_db, GENRE) == set()

    # Retry (fault removed) is idempotent and now completes pending marking.
    monkeypatch.undo()
    res = svc.rename_tag(GENRE, "alternative")
    assert res["moved"] == 0  # already fully moved
    for sid in song_ids[:2]:
        mem = curation_db.app.song_state_membership(sid)
        assert "not_written" in mem
        assert "tags_not_fresh" in mem


# ---------------------------------------------------------------------------
# P1-S3 — concurrency under repository transactions
# ---------------------------------------------------------------------------


def _run_jobs_concurrently(url: str, n: int, job: Callable[[Database, int], object]) -> list[Exception | None]:
    """Run ``n`` workers, each on its own Database/connection, in lockstep."""
    barrier = threading.Barrier(n)
    outcomes: list[Exception | None] = [None] * n

    def _worker(idx: int) -> None:
        db = Database(url=url)
        try:
            barrier.wait(timeout=60)
            job(db, idx)
        except Exception as exc:
            outcomes[idx] = exc
        finally:
            db.close()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    return outcomes


def test_concurrent_disjoint_merges_into_one_canonical_are_consistent(
    curation_db: Database, curation_db_url: str
) -> None:
    """Merging three disjoint source tags into one canonical concurrently never
    duplicates an edge; every source edge lands at the canonical exactly once."""
    _lib, identities, song_ids = _seed(curation_db)
    for idx, value in enumerate(["happy", "sad", "calm"]):
        _tag(curation_db, identities[idx], [("mood", value)])
    # Canonical must pre-exist (merge_tags requires it).
    curation_db.library.ensure_tag(TagRef(name="mood", value="mellow", namespace="default"))
    engine = _storage_engine(curation_db_url)
    try:
        outcomes = _run_jobs_concurrently(
            curation_db_url,
            3,
            lambda db, idx: _svc(db).merge_tags(
                [TagRef(name="mood", value=["happy", "sad", "calm"][idx], namespace="default")],
                TagRef(name="mood", value="mellow", namespace="default"),
            ),
        )
        assert all(e is None for e in outcomes), outcomes

        canonical = TagRef(name="mood", value="mellow", namespace="default")
        assert _songs_with(curation_db, canonical) == set(song_ids)
        can_id = _tag_row_required(engine, canonical)[0]
        edges = _edges_of_tag(engine, can_id)
        assert len(edges) == len(set(edges)) == len(song_ids)  # unique constraint holds
        for value in ("happy", "sad", "calm"):
            row = _tag_row(engine, TagRef(name="mood", value=value, namespace="default"))
            if row is not None:
                assert _edges_of_tag(engine, row[0]) == []
    finally:
        engine.dispose()


def test_concurrent_same_target_renames_no_duplicate_edges_and_retry_converges(
    curation_db: Database, curation_db_url: str
) -> None:
    """Concurrent renames of distinct sources that share songs into one target may
    race; the DB UNIQUE(song_id, tag_id) constraint rejects any duplicate, so no
    duplicate edge ever persists. A retry of the rejected operation converges."""
    _lib, identities, song_ids = _seed(curation_db)
    # song0 has both rock and blues; song1 rock; song2 blues.
    _tag(curation_db, identities[0], [("genre", "rock"), ("genre", "blues")])
    _tag(curation_db, identities[1], [("genre", "rock")])
    _tag(curation_db, identities[2], [("genre", "blues")])
    sources = [GENRE, BLUES]
    engine = _storage_engine(curation_db_url)
    try:
        outcomes = _run_jobs_concurrently(
            curation_db_url,
            2,
            lambda db, idx: _svc(db).rename_tag(sources[idx], "unified"),
        )

        # Retry any operation the DB constraint rejected so the state converges.
        for idx, exc in enumerate(outcomes):
            if exc is not None:
                _svc(curation_db).rename_tag(sources[idx], "unified")

        unified = TagRef(name="genre", value="unified", namespace="default")
        assert _songs_with(curation_db, unified) == set(song_ids)
        unif_id = _tag_row_required(engine, unified)[0]
        edges = _edges_of_tag(engine, unif_id)
        assert len(edges) == len(set(edges)) == len(song_ids)  # no duplicate edges
        for src in sources:
            row = _tag_row(engine, src)
            if row is not None:
                assert _edges_of_tag(engine, row[0]) == []
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# P1-S4 — restart/reload + pagination + cache invariance
# ---------------------------------------------------------------------------


def test_handle_resolves_after_fresh_session_no_pk_cache(curation_db_url: str) -> None:
    """A listed tag's opaque handle resolves across a fresh Database/connection
    (simulated restart) with no in-memory PK cache, by complete natural identity."""
    db1 = Database(url=curation_db_url)
    identities: list[Any] = []
    song_ids: list[int] = []
    try:
        _lib, identities, song_ids = _seed(db1, n=2)
        _tag(db1, identities[0], [("genre", "rock")])
        _tag(db1, identities[1], [("genre", "rock")])
        listing = db1.library.list_tags_with_song_count(name=None, limit=100, offset=0)
        handle = next(encode_tag_handle(u.identity) for u in listing if u.identity.name == "genre")
    finally:
        db1.close()

    # Fresh Database == fresh engine/session: no cached mapping from db1 survives.
    db2 = Database(url=curation_db_url)
    try:
        identity = decode_tag_handle(handle)
        assert isinstance(identity, TagRef)
        assert (identity.name, identity.value, identity.namespace) == ("genre", "rock", "default")
        assert db2.library.get_tag(identity) is not None
        assert _songs_with(db2, identity) == set(song_ids)
    finally:
        db2.close()


def test_after_rename_old_identity_not_found_and_refreshed_listing_emits_new(curation_db_url: str) -> None:
    """After rename, the old identity no longer selects songs and disappears from a
    refreshed listing after orphan cleanup; a fresh session sees the same thing."""
    db1 = Database(url=curation_db_url)
    song_ids: list[int] = []
    try:
        _lib, identities, song_ids = _seed(db1, n=2)
        _tag(db1, identities[0], [("genre", "rock")])
        _tag(db1, identities[1], [("genre", "rock")])
        old_handle = encode_tag_handle(GENRE)
        _svc(db1).rename_tag(GENRE, "alternative")
        db1.library.admin_cleanup_orphaned_tags()  # drop the orphaned source row
    finally:
        db1.close()

    db2 = Database(url=curation_db_url)
    try:
        old_identity = decode_tag_handle(old_handle)
        assert _songs_with(db2, old_identity) == set()
        assert db2.library.get_tag(old_identity) is None

        listing = db2.library.list_tags_with_song_count(name=None, limit=100, offset=0)
        names = {f"{u.identity.name}:{u.identity.value}" for u in listing}
        assert "genre:rock" not in names
        assert "genre:alternative" in names
        new_handle = encode_tag_handle(next(u.identity for u in listing if u.identity.name == "genre"))
        assert _songs_with(db2, decode_tag_handle(new_handle)) == set(song_ids)
    finally:
        db2.close()


def test_handles_survive_pagination_boundaries_and_fresh_session(curation_db_url: str) -> None:
    """Handles are stable and resolve identically across page boundaries and after
    a fresh session (no dependence on a pagination cursor or in-memory PK)."""
    db1 = Database(url=curation_db_url)
    try:
        _lib, identities, _song_ids = _seed(db1, n=4)
        for idx, value in enumerate(["rock", "jazz", "blues", "prog"]):
            _tag(db1, identities[idx], [("genre", value)])

        page1 = db1.library.list_tags_with_song_count(name=None, limit=2, offset=0)
        page2 = db1.library.list_tags_with_song_count(name=None, limit=2, offset=2)
        page1_again = db1.library.list_tags_with_song_count(name=None, limit=2, offset=0)
        assert [encode_tag_handle(u.identity) for u in page1] == [encode_tag_handle(u.identity) for u in page1_again]
        # Every page-1 handle resolves before touching page 2.
        for u in page1:
            identity = u.identity
            assert decode_tag_handle(encode_tag_handle(identity)) == identity
            assert db1.library.get_tag(identity) is not None
        # Page 1 and page 2 handles are distinct (no PK collision bleed).
        handles = [encode_tag_handle(u.identity) for u in list(page1) + list(page2)]
        assert len(set(handles)) == len(handles)
    finally:
        db1.close()

    # After a fresh session, a handle captured on page 1 still resolves by name/value.
    db2 = Database(url=curation_db_url)
    try:
        for u in db2.library.list_tags_with_song_count(name=None, limit=2, offset=0):
            identity = decode_tag_handle(encode_tag_handle(u.identity))
            assert db2.library.get_tag(identity) is not None
    finally:
        db2.close()
