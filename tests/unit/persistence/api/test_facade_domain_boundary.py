# mypy: disable-error-code=func-returns-value
"""Spec-first domain-boundary tests for the song/tag intent facades.

These tests are **SPEC-FIRST**: they assert the canonical domain contract that the
facade-correction phases of ``TASK-song-intent-facade-correction-A`` must implement
per ADR-032, ADR-041, ADR-043, the song-domain-repair design doc, and the Plan A
contracts ledger entry (2026-08-30). The plan is narrowed to the **song-tag slice**
only; folders, ML/vectors/streams, and worker claims are intentionally out of scope
here.

The contract:
- Facades return frozen/slotted domain values and never repository TypedDict rows
  (``SongRow``, ``TagRow``) or raw edge dictionaries.
- Facade inputs are typed domain commands / value objects, never arbitrary
  column-shaped dictionaries.
- Song identity is ``(library identity, normalized_path)`` (ADR-043 natural key);
  absolute path is a maintained detail.

QA / executor note: do NOT weaken an assertion to make it pass early; that would
silently re-open the ADR-032/041 boundary. Assertions that already pass pin the
domain behavior that must be preserved.

Phase 2 adaptations (per the binding signatures in the Plan A ledger):
- ``find_or_create_tag`` renamed to ``ensure_tag`` (same assertion body).
- ``list_tags_by_name`` folded into ``list_tags(name=...)`` (binding hard-cut).
- ``list_song_tag_edges`` removed (binding hard-cut: no edge-list method at the
  facade); the leak test now asserts the method is gone.
- ``SongIdentity(library_id=...)`` -> ``SongIdentity(library=LibraryIdentity(...))``
  (P1-S4 natural library identity gate).
- ``list_tags_for_song`` / ``list_genre_tags_for_songs`` / ``list_song_tags_for_songs``
  accept ``Sequence[SongIdentity]``; ``assignment.song_id`` -> ``assignment.song``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongRemoval,
    SongScanUpdate,
    SongSyncResult,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_songs import LibrarySongsDb
from nomarr.persistence.api.library_tags import LibraryTagsDb

# ── constructors ────────────────────────────────────────────────────────────

_TEST_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")


def _song(normalized_path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_TEST_LIBRARY, normalized_path=normalized_path)


def _make_tags_db() -> tuple[LibraryTagsDb, MagicMock, MagicMock]:
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    song_repo = MagicMock()
    library_repo = MagicMock()
    # Default natural-key resolution: library identity -> library_id 1 and
    # normalized path -> song_id 7, so tag reads resolve without per-test setup.
    # Both the single-key and set-based (P2-S6) resolvers are stubbed.
    library_repo.get_library_by_natural_key.return_value = {"id": 1}
    library_repo.get_library_ids_by_natural_keys.return_value = {("TestLib", "/music"): 1}
    song_repo.get_song_by_normalized_path.return_value = {"id": 7}
    song_repo.get_song_ids_by_normalized_paths.return_value = {(1, "a.mp3"): 7}
    tags = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=song_repo,
        library_repo=library_repo,
    )
    return tags, tag_repo, song_tag_repo


def _make_library_db() -> tuple[LibraryDb, LibraryTagsDb, MagicMock, MagicMock]:
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    song_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_by_natural_key.return_value = {"id": 1}
    library_repo.get_library_ids_by_natural_keys.return_value = {("TestLib", "/music"): 1}
    song_repo.get_song_by_normalized_path.return_value = {"id": 7}
    song_repo.get_song_ids_by_normalized_paths.return_value = {(1, "a.mp3"): 7}
    tags = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=song_repo,
        library_repo=library_repo,
    )
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=MagicMock(),
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    db = LibraryDb(
        session=MagicMock(),
        songs=songs,
        tags=tags,
        scans=MagicMock(),
        regions=MagicMock(),
    )
    return db, tags, tag_repo, song_tag_repo


# ── passing baseline: tag reads already return domain values ────────────────


@pytest.mark.unit
class TestTagDomainBaseline:
    """Pin domain behavior that is already correct and must be preserved."""

    def test_list_tags_for_song_returns_domain_assignments(self) -> None:
        tags, _, song_tag_repo = _make_tags_db()
        song_tag_repo.get_tags_for_song.return_value = [
            {"name": "artist", "value": "X", "namespace": "", "confidence": 0.9, "source": "nomarr"}
        ]
        song = _song()
        result = tags.list_tags_for_song(song)
        assert result
        assignment = result[0]
        assert isinstance(assignment, SongTagAssignment)
        assert assignment.name == "artist"
        assert assignment.value == "X"
        assert assignment.confidence == 0.9
        assert assignment.source == "nomarr"
        assert assignment.song == song

    def test_get_tag_returns_tag_identity(self) -> None:
        tags, tag_repo, _ = _make_tags_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("artist", "X", ""): 11}
        tag_repo.get_tags_by_ids.return_value = [{"name": "artist", "value": "X", "namespace": ""}]
        result = tags.get_tag(TagRef(name="artist", value="X"))
        assert result == TagRef(name="artist", value="X", namespace="")

    def test_ensure_tag_returns_tag_identity(self) -> None:
        tags, tag_repo, _ = _make_tags_db()
        identity = TagRef(name="artist", value="X", namespace="nom")
        result = tags.ensure_tag(identity)
        assert result == identity
        tag_repo.get_or_create_tag.assert_called_once_with("artist", "X", "nom")


# ── spec-first: reads must stop leaking repository rows / raw edges ─────────


@pytest.mark.unit
class TestTagReadRowLeaks:
    """Documented row/raw-dict leaks in tag reads (song-tag slice)."""

    def test_list_tags_returns_domain_tags_not_tag_rows(self) -> None:
        tags, tag_repo, _ = _make_tags_db()
        tag_repo.list_tags.return_value = [{"id": 1, "name": "artist", "value": "X", "namespace": ""}]
        result = tags.list_tags()
        assert result, "spec: list_tags must return at least one domain value"
        assert not isinstance(result[0], dict), "spec: list_tags must not leak TagRow"

    def test_list_tags_name_filter_returns_domain_tags_not_tag_rows(self) -> None:
        # list_tags_by_name was folded into list_tags(name=...) per the binding.
        tags, tag_repo, _ = _make_tags_db()
        tag_repo.list_tags.return_value = [{"id": 1, "name": "artist", "value": "X", "namespace": ""}]
        result = tags.list_tags(name="artist", limit=10)
        assert not isinstance(result[0], dict), "spec: list_tags must not leak TagRow"

    def test_list_genre_tags_for_songs_returns_domain_assignments(self) -> None:
        tags, _, song_tag_repo = _make_tags_db()
        song_tag_repo.get_genre_tags_for_songs.return_value = [
            {"id": 1, "name": "genre", "value": "Jazz", "namespace": ""}
        ]
        result = tags.list_genre_tags_for_songs([_song()])
        assert not isinstance(result[0], dict), "spec: list_genre_tags_for_songs must not leak TagRow"

    def test_list_song_tags_for_songs_returns_domain_assignments_per_song(self) -> None:
        tags, _, song_tag_repo = _make_tags_db()
        song_tag_repo.get_tags_for_songs_batch.return_value = [
            {
                "song_id": 7,
                "tag_id": 1,
                "tag_name": "artist",
                "tag_value": "X",
                "namespace": "",
                "source": "nomarr",
                "confidence": 0.9,
            }
        ]
        song = _song()
        result = tags.list_song_tags_for_songs([song])
        assert song in result
        assignment = result[song][0]
        assert isinstance(assignment, SongTagAssignment), "spec: must return SongTagAssignment, not TagRow"
        assert assignment.name == "artist"

    def test_list_song_tag_edges_removed(self) -> None:
        # Binding hard-cut: no edge-list method exists at the facade; raw edge
        # dicts can therefore never leak from a tag read.
        tags, _, _ = _make_tags_db()
        assert not hasattr(tags, "list_song_tag_edges"), "spec: no edge-list method at the facade"


# ── spec-first: forwarder accepts domain identity ───────────────────────────


@pytest.mark.unit
class TestForwarderDomainIdentity:
    """The LibraryDb forwarder must accept/return domain identity, not int PKs."""

    def test_forwarder_get_tag_accepts_tag_identity(self) -> None:
        db, _, tag_repo, _ = _make_library_db()
        tag_repo.get_tag_ids_by_identities.return_value = {("artist", "X", ""): 11}
        tag_repo.get_tags_by_ids.return_value = [{"name": "artist", "value": "X", "namespace": ""}]
        # LibraryDb is the intent facade itself; methods are exposed directly.
        result = db.get_tag(TagRef(name="artist", value="X"))
        assert isinstance(result, TagRef), "spec: forwarder get_tag must accept/return TagRef"


# ── positive contract tests on the newly-defined domain commands ────────────


@pytest.mark.unit
class TestSongCommandContracts:
    """The new domain command/value objects behave as the adopted contracts."""

    def test_song_identity_natural_key(self) -> None:
        identity = _song()
        assert identity.library == _TEST_LIBRARY
        assert identity.normalized_path == "a.mp3"

    def test_song_identity_rejects_blank_path(self) -> None:
        with pytest.raises(ValueError):
            SongIdentity(library=_TEST_LIBRARY, normalized_path="   ")

    def test_song_upsert_input_composes_scan_update(self) -> None:
        scan = SongScanUpdate(
            normalized_path="a.mp3",
            file_size=100,
            modified_time=1000,
            duration_seconds=120.5,
            scanned_at=1000,
        )
        upsert = SongUpsertInput(path="/music/a.mp3", folder_id=None, scan=scan)
        # ASR-0015 composition: scan metadata lives in one authoritative type.
        assert isinstance(upsert.scan, SongScanUpdate)
        assert upsert.scan.file_size == 100

    def test_song_path_update_and_removal_carry_identity(self) -> None:
        identity = _song()
        assert SongPathUpdate(song_identity=identity, new_path="/music/b.mp3").new_path == "/music/b.mp3"
        assert SongRemoval(song_identity=identity).song_identity == identity

    def test_song_sync_result_is_domain_counts(self) -> None:
        result = SongSyncResult(added=1, updated=2, removed=0)
        assert (result.added, result.updated, result.removed) == (1, 2, 0)
