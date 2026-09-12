"""Tests for search behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import TaggedSong, TagMatchedSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dto.library_dto import FileTag, SearchFilesResult
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.domain.tagging_svc.query import TaggingQueryMixin

_LIBRARY_UUID = "6313b0d3-d270-47a8-9e0d-21e8255107e3"
_LIBRARY = Library(name="Music", root_path="/music", library_uuid=_LIBRARY_UUID)


def _make_service(*, db: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for search tests."""
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


def _song(normalized_path: str) -> Song:
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=100,
        modified_time=1000,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _locator(normalized_path: str) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid=_LIBRARY_UUID, name="Music", root_path="/music"),
        normalized_path=normalized_path,
    )


def _wire_projection(db: MagicMock, songs: list[Song]) -> None:
    """Wire the public Q3-C carrier projection for the given songs."""
    db.library.list_libraries.return_value = [_LIBRARY]
    by_path = {song.normalized_path: song for song in songs}

    def _resolve(requested: list[SongIdentity]) -> list[Song]:
        return [by_path[r.normalized_path] for r in requested if r.normalized_path in by_path]

    db.library.list_songs_by_identity.side_effect = _resolve


class TestSearchFilesByTag:
    """Tests for ``TaggingService.search_songs_by_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_projects_typed_carriers_to_opaque_locator_dtos(self) -> None:
        """Typed ``TagMatchedSong`` carriers project to ``nom1`` locator DTOs.

        The service must not route typed carriers through a dict mapper; each
        ``file_id`` is the opaque locator token and the result shape (total from
        the dedicated count query, forwarded limit/offset) is preserved.
        """
        mock_db = MagicMock()
        first = TagMatchedSong(
            song=_song("one.flac"),
            metadata={"artist": "Artist One", "album": "Album One", "title": "Title One"},
            matched_tag=TagRef(name="genre", value="rock"),
            distance=0.0,
        )
        second = TagMatchedSong(
            song=_song("two.flac"),
            metadata={"artist": "Artist Two", "album": "Album Two", "title": "Title Two"},
            matched_tag=TagRef(name="genre", value="rock"),
            distance=0.5,
        )
        _wire_projection(mock_db, [first.song, second.song])
        service = _make_service(db=mock_db)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.query.search_songs_by_tag",
                return_value=[first, second],
            ) as mock_search,
            patch(
                "nomarr.services.domain.tagging_svc.query.count_songs_by_tag",
                return_value=50,
            ) as mock_count,
        ):
            result = service.search_songs_by_tag(
                tag_key="genre",
                target_value="rock",
                limit=25,
                offset=10,
            )

        assert isinstance(result, SearchFilesResult)
        assert result.total == 50
        assert result.limit == 25
        assert result.offset == 10
        assert [song.file_id for song in result.songs] == [
            encode_song_locator(_locator("one.flac")),
            encode_song_locator(_locator("two.flac")),
        ]
        assert all(song.file_id.startswith("nom1") for song in result.songs)
        assert result.songs[0].path == "/music/one.flac"
        assert result.songs[0].artist == "Artist One"
        assert result.songs[0].title == "Title One"
        assert result.songs[0].library_uuid == _LIBRARY_UUID
        assert result.songs[0].tags == []
        mock_search.assert_called_once_with(mock_db, "genre", "rock", 25, 10)
        mock_count.assert_called_once_with(mock_db, "genre", "rock")
        assert result.total != len(result.songs)


class TestTaggedSongDtoNoGeneratedId:
    """Negative proof: the service projection never derives a generated id."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_tagged_song_dto_has_no_generated_id_or_resolver(self) -> None:
        source = inspect.getsource(TaggingQueryMixin._tagged_song_dto)
        forbidden = (
            ".song_id",
            ".to_dict(",
            "from_row",
            "resolve_song_identity",
            "resolve_song_identities",
            "require_library_song_id",
            "_locators_for_songs(",
        )
        for token in forbidden:
            assert token not in source, f"_tagged_song_dto contains forbidden token {token!r}"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_unresolved_locator_raises_value_error(self) -> None:
        """An unresolvable carrier fails deterministically instead of faking an id."""
        mock_db = MagicMock()
        service = _make_service(db=mock_db)
        carrier = TagMatchedSong(
            song=_song("ghost.flac"),
            metadata={},
            matched_tag=TagRef(name="genre", value="rock"),
            distance=0.0,
        )

        with (
            patch(
                "nomarr.services.domain.tagging_svc.query.locators_for_carriers",
                return_value=[None],
            ),
            pytest.raises(ValueError, match="Unable to resolve song locator"),
        ):
            service._tagged_song_dto(carrier)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_tagged_carrier_preserves_sealed_tags(self) -> None:
        """A ``TaggedSong`` carrier projects its sealed tags to opaque ``FileTag``s."""
        mock_db = MagicMock()
        song = _song("tagged.flac")
        _wire_projection(mock_db, [song])
        service = _make_service(db=mock_db)
        sealed = FileTag(key="genre", value="Rock", tag_type="string", is_nomarr=False)
        carrier = TaggedSong(
            song=song,
            metadata={"artist": "Artist", "album": "Album", "title": "Title"},
            tags=(sealed,),
        )

        dto = service._tagged_song_dto(carrier)

        assert dto.file_id == encode_song_locator(_locator("tagged.flac"))
        assert dto.file_id.startswith("nom1")
        assert dto.tags == [sealed]
