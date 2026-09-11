"""Tests for tag curation operations in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import RelinkResult, TagRef
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult
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
        source = TagRef(name="genre", value="genre", namespace="default")
        si_10 = SongIdentity(library=self._lib(), normalized_path="10.flac")
        si_20 = SongIdentity(library=self._lib(), normalized_path="20.flac")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        service.db.library.resolve_song_identities = MagicMock(return_value={10: si_10, 20: si_20})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=2, skipped=0, source_orphaned=0),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            result = service.split_tag(source, ["10", "20"], "rock")

        assert result == SplitResult(moved=2, new_tag_created=True)
        assert mock_transition.call_count == 2
        get_tag.assert_called_once_with(source)
        # The split creates an ordinary target in the literal "default" namespace.
        service.db.library.ensure_tag.assert_called_once_with(TagRef(name="genre", value="rock", namespace="default"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_song_boundary_unchanged(self) -> None:
        """Split song ids resolve through the song-side identity bridge (separate boundary)."""
        service = _make_service()
        source = TagRef(name="genre", value="genre", namespace="default")
        si_10 = SongIdentity(library=self._lib(), normalized_path="10.flac")
        _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        service.db.library.resolve_song_identities = MagicMock(return_value={10: si_10})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=0),
            ) as mock_relink,
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            service.split_tag(source, ["10"], "rock")

        # Song identity is NOT a tag identity: integer song handles are still the
        # song boundary and are passed to the song-side resolver unchanged.
        service.db.library.resolve_song_identities.assert_called_once_with([10])
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
    def test_split_tag_numeric_natural_value_is_data(self) -> None:
        """A numeric source natural value ('120') is addressed as data, never a storage PK."""
        service = _make_service()
        source = TagRef(name="genre", value="120", namespace="default")
        si_10 = SongIdentity(library=self._lib(), normalized_path="10.flac")
        get_tag = _present(service, source)
        service.db.library.ensure_tag = MagicMock(return_value=TagRef(name="genre", value="rock", namespace="default"))
        service.db.library.resolve_song_identities = MagicMock(return_value={10: si_10})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=1, skipped=0, source_orphaned=0),
            ),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state"),
        ):
            result = service.split_tag(source, ["10"], "rock")

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
        service.db.library.find_songs_with_tag = MagicMock(return_value=(_song(10), _song(20)))
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN, STATE_TAGS_CURRENT})
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value=RelinkResult(moved=2, skipped=0, source_orphaned=0),
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
        ):
            service.rename_tag(source, "new")

        # ADR-008: each curated song is queued for both projection and write-back.
        assert [call.args[1:] for call in mock_transition.call_args_list] == [
            ([10], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([10], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
            ([20], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([20], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
        ]


class TestUpdateSongTags:
    """Tests for ``TaggingCurationMixin.update_song_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_curated_song_is_marked_not_fresh_for_file_write(self) -> None:
        """Curation must enqueue the song in the reconciliation stale state."""
        service = _make_service()
        service.db.app.song_state_membership = MagicMock(return_value={STATE_WRITTEN, STATE_TAGS_CURRENT})
        with (
            patch("nomarr.services.domain.tagging_svc.curation.set_song_tags"),
            patch("nomarr.services.domain.tagging_svc.curation.get_song_tags", return_value=None),
            patch("nomarr.services.domain.tagging_svc.curation.transition_song_state") as transition,
        ):
            service.update_song_tags("1", "genre", ["rock"])

        assert [call.args[1:] for call in transition.call_args_list] == [
            ([1], STATE_WRITTEN, STATE_NOT_WRITTEN),
            ([1], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_success(self) -> None:
        """Successful update should return file_id, name, and tag list."""
        service = _make_service()
        tags_obj = Tags(items=(Tag(name="genre", values=("rock",)),))
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.set_song_tags",
            ) as mock_set,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
            patch(
                "nomarr.services.domain.tagging_svc.curation.get_song_tags",
                return_value=tags_obj,
            ),
        ):
            result = service.update_song_tags("1", "genre", ["rock"])

        assert result == {
            "file_id": "1",
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
        mock_set.assert_called_once()
        mock_transition.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_song_tags_returns_empty_tags_when_get_song_tags_returns_none(self) -> None:
        """The strict None state maps to an empty ``tags`` list in the response."""
        service = _make_service()
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.set_song_tags",
            ) as mock_set,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_song_state",
            ) as mock_transition,
            patch(
                "nomarr.services.domain.tagging_svc.curation.get_song_tags",
                return_value=None,
            ),
        ):
            result = service.update_song_tags("1", "genre", ["rock"])

        assert result == {
            "file_id": "1",
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
