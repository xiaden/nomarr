"""Tests for tag curation operations in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.song_query_types import TrackSong
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import RelinkResult, SongTagAssignment, TagRef
from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult
from nomarr.helpers.song_locator_codec import SongLocatorFormatError, encode_song_locator
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.domain.tagging_svc.curation import TaggingCurationMixin


def _make_service(*, db: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for curation tests."""
    return TaggingService(
        database=db or MagicMock(),
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=MagicMock(),
        config_service=MagicMock(),
    )


def _song(song_id: int) -> Song:
    """Build a minimal domain ``Song`` for facade song-read mocks."""
    return Song(
        path=f"/music/{song_id}.flac",
        normalized_path=f"music/{song_id}.flac",
        file_size=0,
        modified_time=0,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=0,
    )


_LIBRARY = LibraryIdentity(library_uuid="2621ebfb-71ff-4168-a812-5342ca310e8c", name="music", root_path="/music")


def _song_identity(song_id: int) -> SongIdentity:
    """Semantic locator matching the ``_token`` helper for one test fixture."""
    return SongIdentity(library=_LIBRARY, normalized_path=f"{song_id}.flac")


def _token(song_id: int) -> str:
    """Opaque ``nom1`` SongLocator token for one test fixture."""
    return encode_song_locator(_song_identity(song_id))


def _stub_song_lookup(service: TaggingService) -> None:
    """Stub the library-by-uuid read used to decode song locator tokens."""
    service.db.library.get_library_by_uuid = MagicMock(return_value=Library(name="music", root_path="/music"))


def _present(service: TaggingService, identity: TagRef) -> MagicMock:
    """Stub the natural-facade lookup so ``identity`` exists for curation.

    Returns the ``get_tag`` mock so callers can assert on it with full typing.
    """
    get_tag = MagicMock(return_value=identity)
    service.db.library.get_tag = get_tag
    return get_tag


class TestTagCurationRejectNomPrefix:
    """Tests for ``TaggingCurationMixin._reject_nom_prefix``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_by_name_raises(self) -> None:
        """A name starting with 'nom:' should raise ValueError (ADR-009)."""
        with pytest.raises(ValueError, match="read-only"):
            TaggingCurationMixin._reject_nom_prefix(name="nom:genre")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_by_identity_raises(self) -> None:
        """A TagRef with a 'nom:' name should raise ValueError (ADR-009)."""
        with pytest.raises(ValueError, match="read-only"):
            TaggingCurationMixin._reject_nom_prefix(identity=TagRef(name="nom:genre", value="rock", namespace="nom"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_non_nom_passes(self) -> None:
        """A non-nom: name should not raise."""
        TaggingCurationMixin._reject_nom_prefix(name="genre")  # no exception

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_no_args_passes(self) -> None:
        """Calling with no arguments should not raise."""
        TaggingCurationMixin._reject_nom_prefix()  # no exception


class TestGetTagOrError:
    """Tests for ``TaggingCurationMixin._get_tag_or_error`` (natural facade lookup)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_tag_or_error_resolves_via_natural_facade(self) -> None:
        """An existing natural identity resolves through ``db.library.get_tag``."""
        identity = TagRef(name="genre", value="rock", namespace="default")
        service = _make_service()
        get_tag = _present(service, identity)

        result = service._get_tag_or_error(identity)

        assert result == identity
        # Natural lookup receives the complete TagRef -- no int(), no PK.
        get_tag.assert_called_once_with(identity)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_tag_or_error_raises_for_unknown_natural_identity(self) -> None:
        """A missing natural identity is a deterministic not-found ValueError."""
        service = _make_service()
        service.db.library.get_tag = MagicMock(return_value=None)

        with pytest.raises(ValueError, match="Tag not found"):
            service._get_tag_or_error(TagRef(name="genre", value="missing", namespace="default"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_tag_or_error_numeric_natural_value_is_not_a_pk(self) -> None:
        """A numeric-looking natural value ('120') is data, never a storage id."""
        service = _make_service()
        identity = TagRef(name="genre", value="120", namespace="default")
        get_tag = _present(service, identity)

        result = service._get_tag_or_error(identity)

        assert result.value == "120"
        assert isinstance(result.value, str)
        get_tag.assert_called_once_with(TagRef(name="genre", value="120", namespace="default"))


class TestRenameTag:
    """Tests for ``TaggingCurationMixin.rename_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_tag_success(self) -> None:
        """Successful rename should return moved count and merged_into_existing flag."""
        service = _make_service()
        source = TagRef(name="genre", value="genre", namespace="default")
        target = TagRef(name="genre", value="music_genre", namespace="default")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=target)
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10), _song(20)))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=5, skipped=0, source_orphaned=1),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[_song_identity(10), _song_identity(20)],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.rename_tag(source, "music_genre")

        assert result == RenameResult(moved=5, merged_into_existing=True)
        assert mock_transition.call_count == 2
        get_tag.assert_called_once_with(source)
        service.db.library.ensure_tag.assert_called_once_with(
            TagRef(name="genre", value="music_genre", namespace="default")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_never_mutates_shared_source_identity(self) -> None:
        """Curation builds a fresh target identity and never mutates the shared source TagRef."""
        service = _make_service()
        source = TagRef(name="genre", value="old", namespace="default")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="new", namespace="default"))
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=0, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            service.rename_tag(source, "new")

        # The shared source identity is untouched (frozen, still carries the old value).
        assert source.value == "old"
        assert source.name == "genre"
        assert source.namespace == "default"
        # The ordinary target is a distinct identity with the new value in "default".
        called = service.db.library.ensure_tag.call_args.args[0]
        assert called.value == "new"
        assert called.namespace == "default"
        assert called is not source

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_tag_rejects_nom_prefix(self) -> None:
        """Renaming a nom: tag should raise ValueError before any mutation (ADR-009)."""
        service = _make_service()
        nom = TagRef(name="nom:genre", value="x", namespace="nom")
        _present(service, nom)
        service.db.library.ensure_tag = MagicMock()
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
            pytest.raises(ValueError, match="read-only"),
        ):
            service.rename_tag(nom, "new_value")

        # No partial mutation: validation fails before the target is created or edges relinked.
        service.db.library.ensure_tag.assert_not_called()
        mock_relink.assert_not_called()
        mock_transition.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_tag_missing_identity_is_no_partial_mutation(self) -> None:
        """A missing source identity raises before the target is created."""
        service = _make_service()
        service.db.library.get_tag = MagicMock(return_value=None)
        service.db.library.ensure_tag = MagicMock()
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            pytest.raises(ValueError, match="Tag not found"),
        ):
            service.rename_tag(TagRef(name="genre", value="missing", namespace="default"), "new_value")

        service.db.library.ensure_tag.assert_not_called()
        mock_relink.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_target_collision_merges_into_existing(self) -> None:
        """Renaming onto an existing target merges (collision-safe) via the facade relink."""
        service = _make_service()
        source = TagRef(name="genre", value="old", namespace="default")
        existing = TagRef(name="genre", value="new", namespace="default")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=existing)  # target already exists
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10),))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=2, skipped=1, source_orphaned=1),
            ) as mock_relink,
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[_song_identity(10)],
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.rename_tag(source, "new")

        # merged_into_existing True: target pre-existed and relink is duplicate-safe
        # (collision deletions are the facade's typed skipped/moved contract, ADR-014).
        assert result == RenameResult(moved=2, merged_into_existing=True)
        mock_relink.assert_called_once_with(service.db, source, existing)
        service.db.library.find_songs_with_tag.assert_called_once_with(existing, limit=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_retry_same_value_is_idempotent(self) -> None:
        """Renaming to the tag's current value is a no-op relink (retry idempotence)."""
        service = _make_service()
        source = TagRef(name="genre", value="rock", namespace="default")
        _present(service, source)
        # ensure_tag returns the same natural identity because the target already equals source.
        service.db.library.ensure_tag = MagicMock(return_value=source)
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=0, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.rename_tag(source, "rock")

        assert result == RenameResult(moved=0, merged_into_existing=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_numeric_natural_value_is_data(self) -> None:
        """A numeric natural value ('120') is addressed as data, not a storage PK."""
        service = _make_service()
        source = TagRef(name="genre", value="120", namespace="default")
        target = TagRef(name="genre", value="121", namespace="default")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=target)
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=0, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.rename_tag(source, "121")

        assert result == RenameResult(moved=0, merged_into_existing=True)
        # The source is looked up by its complete natural identity, value forwarded verbatim.
        get_tag.assert_called_once_with(TagRef(name="genre", value="120", namespace="default"))
        service.db.library.ensure_tag.assert_called_once_with(TagRef(name="genre", value="121", namespace="default"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_relink_failure_does_not_enqueue_write_pending(self) -> None:
        """A relink failure propagates and does not mark songs write-pending (no partial)."""
        service = _make_service()
        source = TagRef(name="genre", value="old", namespace="default")
        target = TagRef(name="genre", value="new", namespace="default")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=target)
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10),))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                side_effect=RuntimeError("relink failed"),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
            pytest.raises(RuntimeError, match="relink failed"),
        ):
            service.rename_tag(source, "new")

        # Mutation after the failed relink is not reached.
        service.db.library.find_songs_with_tag.assert_not_called()
        mock_transition.assert_not_called()


class TestMergeTags:
    """Tests for ``TaggingCurationMixin.merge_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_success(self) -> None:
        """Successful merge should return total_moved and sources_removed counts."""
        service = _make_service()
        canonical = TagRef(name="genre", value="genre", namespace="default")
        source = TagRef(name="genre", value="rock", namespace="default")
        service.db.library.get_tag = MagicMock(side_effect=[canonical, source])
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10),))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=3, skipped=0, source_orphaned=1),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[_song_identity(10)],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.merge_tags([source], canonical)

        assert result == MergeResult(total_moved=3, sources_removed=1)
        mock_transition.assert_called_once()
        service.db.library.get_tag.assert_has_calls([call(canonical), call(source)])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_skips_self_reference(self) -> None:
        """Source list containing only the canonical tag should skip it without any merging."""
        service = _make_service()
        canonical = TagRef(name="genre", value="genre", namespace="default")
        get_tag = _present(service, canonical)
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ),
        ):
            result = service.merge_tags([canonical], canonical)

        assert result == MergeResult(total_moved=0, sources_removed=0)
        # Canonical resolved once; the self-referencing source is skipped without relink.
        get_tag.assert_called_once_with(canonical)
        mock_relink.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_rejects_nom_prefix(self) -> None:
        """Merging into a nom: canonical tag should raise ValueError (ADR-009)."""
        service = _make_service()
        nom = TagRef(name="nom:genre", value="x", namespace="nom")
        _present(service, nom)
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
            pytest.raises(ValueError, match="read-only"),
        ):
            service.merge_tags([TagRef(name="genre", value="rock", namespace="default")], nom)

        # Validation of the canonical tag fails before any source is relinked.
        mock_relink.assert_not_called()
        mock_transition.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_numeric_natural_value_is_data(self) -> None:
        """Merge source/canonical '120' natural values are data, never storage PKs."""
        service = _make_service()
        canonical = TagRef(name="genre", value="120", namespace="default")
        source = TagRef(name="genre", value="rock", namespace="default")
        service.db.library.get_tag = MagicMock(side_effect=[canonical, source])
        service.db.library.find_songs_with_tag = MagicMock(return_value=())
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=1),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.merge_tags([source], canonical)

        assert result == MergeResult(total_moved=1, sources_removed=1)
        # Canonical '120' natural identity forwarded verbatim (string), not int 120.
        first_call = service.db.library.get_tag.call_args_list[0].args[0]
        assert first_call == TagRef(name="genre", value="120", namespace="default")
        assert first_call.value == "120"


class TestSplitTag:
    """Tests for ``TaggingCurationMixin.split_tag``."""

    def _lib(self) -> LibraryIdentity:
        return LibraryIdentity(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="music", root_path="/music")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_success(self) -> None:
        """Successful split should return moved count and new_tag_created flag."""
        service = _make_service()
        _stub_song_lookup(service)
        source = TagRef(name="genre", value="genre", namespace="default")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=2, skipped=0, source_orphaned=0),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.split_tag(source, [_token(10), _token(20)], "rock")

        assert result == SplitResult(moved=2, new_tag_created=True)
        assert mock_transition.call_count == 2
        get_tag.assert_called_once_with(source)
        # The split creates an ordinary target in the literal "default" namespace.
        service.db.library.ensure_tag.assert_called_once_with(TagRef(name="genre", value="rock", namespace="default"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_song_boundary_unchanged(self) -> None:
        """Split locator tokens resolve through the song-side semantic boundary (separate from tags)."""
        service = _make_service()
        _stub_song_lookup(service)
        source = TagRef(name="genre", value="genre", namespace="default")
        si_10 = _song_identity(10)
        token = _token(10)
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=0),
            ) as mock_relink,
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            service.split_tag(source, [token], "rock")

        # Song identity is NOT a tag identity: the opaque SongLocator token is
        # decoded to a semantic locator; no integer identity bridge participates.
        service.db.library.resolve_song_identities.assert_not_called()
        mock_relink.assert_called_once_with(
            service.db,
            source,
            TagRef(name="genre", value="rock", namespace="default"),
            song_identities=[si_10],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_rejects_nom_prefix(self) -> None:
        """Splitting a nom: tag should raise ValueError (ADR-009)."""
        service = _make_service()
        nom = TagRef(name="nom:genre", value="x", namespace="nom")
        _present(service, nom)
        service.db.library.ensure_tag = MagicMock()
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            pytest.raises(ValueError, match="read-only"),
        ):
            service.split_tag(nom, ["10"], "rock")

        service.db.library.ensure_tag.assert_not_called()
        mock_relink.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_existing_target_does_not_report_new_created(self) -> None:
        """Splitting onto the source's own identity reports ``new_tag_created=False``."""
        service = _make_service()
        _stub_song_lookup(service)
        source = TagRef(name="genre", value="rock", namespace="default")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=source)
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.split_tag(source, [_token(10)], "rock")

        assert result == SplitResult(moved=1, new_tag_created=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_numeric_natural_value_is_data(self) -> None:
        """A numeric source natural value ('120') is addressed as data, never a storage PK."""
        service = _make_service()
        _stub_song_lookup(service)
        source = TagRef(name="genre", value="120", namespace="default")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.split_tag(source, [_token(10)], "rock")

        assert result == SplitResult(moved=1, new_tag_created=True)
        get_tag.assert_called_once_with(TagRef(name="genre", value="120", namespace="default"))


class TestRenameTagWritePending:
    """Deferred write-back (ADR-008) on rename: curation enqueues write-pending states."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_marks_target_song_write_pending(self) -> None:
        """Rename transitions the target song to not-written / not-fresh."""
        service = _make_service()
        source = TagRef(name="genre", value="old", namespace="default")
        target = TagRef(name="genre", value="new", namespace="default")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=target)
        si_10 = _song_identity(10)
        si_20 = _song_identity(20)
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10), _song(20)))
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN, STATE_TAGS_CURRENT})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=2, skipped=0, source_orphaned=0),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[si_10, si_20],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            service.rename_tag(source, "new")

        # ADR-008: each curated song is queued for both projection and write-back.
        assert [call.args[1:] for call in mock_transition.call_args_list] == [
            ([si_10], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([si_10], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
            ([si_20], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([si_20], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
        ]


class TestUpdateSongTags:
    """Tests for ``TaggingCurationMixin.update_song_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_curated_song_is_marked_not_fresh_for_file_write(self) -> None:
        """Curation must enqueue the song in the reconciliation stale state."""
        service = _make_service()
        _stub_song_lookup(service)
        si = _song_identity(1)
        token = _token(1)
        service.db.library.list_tags_for_song = MagicMock(return_value=[])
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN, STATE_TAGS_CURRENT})
        with (
            patch("nomarr.services.domain.tagging_svc.curation.set_song_tags"),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition,
        ):
            service.update_song_tags(token, "genre", ["rock"])

        assert [call.args[1:] for call in transition.call_args_list] == [
            ([si], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([si], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_success(self) -> None:
        """Successful update should return file_id, name, and tag list."""
        service = _make_service()
        _stub_song_lookup(service)
        si = _song_identity(1)
        token = _token(1)
        service.db.library.list_tags_for_song = MagicMock(
            return_value=[SongTagAssignment(name="genre", value="rock", namespace="default")]
        )
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.set_song_tags",
            ) as mock_set,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.update_song_tags(token, "genre", ["rock"])

        assert result == {
            "file_id": token,
            "name": "genre",
            "tags": [
                {
                    "key": "genre",
                    "value": "rock",
                    "tag_type": "string",
                    "is_nomarr": False,
                },
            ],
        }
        mock_set.assert_called_once_with(service.db, si, "genre", ["rock"])
        mock_transition.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_returns_empty_tags_when_no_tags_match(self) -> None:
        """An empty tag read maps to an empty ``tags`` list in the response."""
        service = _make_service()
        _stub_song_lookup(service)
        token = _token(1)
        service.db.library.list_tags_for_song = MagicMock(return_value=[])
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.set_song_tags",
            ) as mock_set,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.update_song_tags(token, "genre", ["rock"])

        assert result == {
            "file_id": token,
            "name": "genre",
            "tags": [],
        }
        mock_set.assert_called_once()
        mock_transition.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_rejects_nom_prefix(self) -> None:
        """Updating with a nom: name should raise ValueError (ADR-009)."""
        service = _make_service()
        with pytest.raises(ValueError, match="read-only"):
            service.update_song_tags("1", "nom:genre", ["rock"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_filters_to_the_named_tag_only(self) -> None:
        """Only assignments whose name matches are returned, tagged with is_nomarr."""
        service = _make_service()
        _stub_song_lookup(service)
        token = _token(1)
        service.db.library.list_tags_for_song = MagicMock(
            return_value=[
                SongTagAssignment(name="genre", value="rock", namespace="default"),
                SongTagAssignment(name="mood", value="happy", namespace="nom"),
            ]
        )
        with (
            patch("nomarr.services.domain.tagging_svc.curation.set_song_tags"),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.update_song_tags(token, "genre", ["rock"])

        # The non-matching 'mood' assignment is excluded from the echoed tag list.
        assert result["tags"] == [
            {"key": "genre", "value": "rock", "tag_type": "string", "is_nomarr": False},
        ]


class TestMarkSongWritePending:
    """Tests for ``TaggingCurationMixin._mark_song_write_pending``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_written_and_current_then_not_fresh(self) -> None:
        service = _make_service()
        si = _song_identity(1)
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN, STATE_TAGS_CURRENT})
        with patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition:
            service._mark_song_write_pending(si)

        assert [call.args[1:] for call in transition.call_args_list] == [
            ([si], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([si], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_tags_transition_when_tags_current_absent(self) -> None:
        """Without TAGS_CURRENT membership no tags-not-fresh transition may run."""
        service = _make_service()
        si = _song_identity(1)
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN})
        with patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition:
            service._mark_song_write_pending(si)

        assert [call.args[1:] for call in transition.call_args_list] == [
            ([si], STATE_WRITTEN, STATE_NOT_WRITTEN),
        ]


class TestSongIdentityFromToken:
    """Tests for ``TaggingCurationMixin._song_identity_from_token``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_unknown_library_token_raises_value_error(self) -> None:
        """A syntactically valid token for a missing library is a not-found error."""
        service = _make_service()
        service.db.library.get_library_by_uuid = MagicMock(return_value=None)

        with pytest.raises(ValueError, match="Unknown library"):
            service._song_identity_from_token(_token(1))

        service.db.library.get_library_by_uuid.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_malformed_token_propagates_decode_error_without_fallback(self) -> None:
        """A non-token string propagates the decode error; no library lookup runs."""
        service = _make_service()
        service.db.library.get_library_by_uuid = MagicMock()

        with pytest.raises(SongLocatorFormatError):
            service._song_identity_from_token("10")

        service.db.library.get_library_by_uuid.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_existing_library_to_semantic_locator(self) -> None:
        """A valid token resolves through the UUID facade to a semantic locator."""
        service = _make_service()
        _stub_song_lookup(service)

        result = service._song_identity_from_token(_token(1))

        assert result == SongIdentity(library=_LIBRARY, normalized_path="1.flac")
        assert not isinstance(result.normalized_path, int)


class TestMarkMatchedSongsWritePending:
    """Deferred write-back (ADR-008) on matched-tag curation."""

    @pytest.mark.unit
    def test_projects_real_track_carriers_before_marking_resolved_songs(self) -> None:
        """The curation path uses the public carrier projection without patching it."""

        class FakeLibraryDb:
            def find_songs_with_tag(self, tag: TagRef, *, limit: int | None) -> tuple[Song, ...]:
                assert limit is None
                return (_song(10), _song(20))

            def list_libraries(self) -> list[Library]:
                return [Library(library_uuid=_LIBRARY.library_uuid, name="music", root_path="/music")]

            def list_songs_by_identity(self, identities: list[SongIdentity]) -> list[Song]:
                assert [identity.normalized_path for identity in identities] == [
                    "music/10.flac",
                    "music/20.flac",
                ]
                return [_song(10), _song(20)]

        class FakeDatabase:
            library = FakeLibraryDb()

        class RecordingCuration(TaggingCurationMixin):
            db: Any = FakeDatabase()

            def __init__(self) -> None:
                self.marked: list[SongIdentity] = []

            def _mark_song_write_pending(self, song: SongIdentity) -> None:
                self.marked.append(song)

        service = RecordingCuration()
        service._mark_matched_songs_write_pending(TagRef(name="genre", value="rock", namespace="default"))

        assert service.marked == [
            SongIdentity(_LIBRARY, "music/10.flac"),
            SongIdentity(_LIBRARY, "music/20.flac"),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_stale_none_locator_and_never_readdresses(self) -> None:
        """A ``None`` (stale) locator is skipped; resolved entries are marked."""
        service = _make_service()
        tag = TagRef(name="genre", value="rock", namespace="default")
        si_20 = _song_identity(20)
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10), _song(20)))
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[None, si_20],
            ) as mock_locators,
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition,
        ):
            service._mark_matched_songs_write_pending(tag)

        mock_locators.assert_called_once()
        assert [call.args[1] for call in transition.call_args_list] == [[si_20]]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_constructs_track_song_carriers_with_empty_metadata_and_no_isrc(self) -> None:
        """Each matched song is wrapped as ``TrackSong(song, metadata={}, isrc=None)``."""
        service = _make_service()
        tag = TagRef(name="genre", value="rock", namespace="default")
        songs = (_song(10), _song(20))
        service.db.library.find_songs_with_tag = MagicMock(return_value=songs)
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                return_value=[None, None],
            ) as mock_locators,
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            service._mark_matched_songs_write_pending(tag)

        (carriers,) = mock_locators.call_args.args[1:]
        assert carriers == [TrackSong(song=song, metadata={}, isrc=None) for song in songs]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_propagates_locator_projection_error_without_marking(self) -> None:
        """A projection failure propagates and runs no write-pending transition."""
        service = _make_service()
        tag = TagRef(name="genre", value="rock", namespace="default")
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10),))
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.locators_for_carriers",
                side_effect=RuntimeError("projection failed"),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition,
            pytest.raises(RuntimeError, match="projection failed"),
        ):
            service._mark_matched_songs_write_pending(tag)

        transition.assert_not_called()
