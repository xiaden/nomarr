"""Tests for tag query operations in ``nomarr.services.domain.tagging_svc``.

Focused coverage for the natural-identity query path (``get_tag_songs``): the
service threads a complete ``TagRef`` into the query components without integer
conversion, preserves the public response shape, and keeps a missing natural
identity a deterministic empty result.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig


def _make_service(*, db: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for query tests."""
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


def _song_identity(song_id: int) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(name="Music", root_path="/music"),
        normalized_path=f"music/{song_id}.flac",
    )


class TestGetTagSongs:
    """Tests for ``TaggingQueryMixin.get_tag_songs``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_threads_natural_identity_without_integer_conversion(self) -> None:
        """A complete TagRef flows to the components; no tag PK is ever parsed."""
        service = _make_service()
        electronic = TagRef(name="genre", value="Electronic")
        song = _song(1)
        song_identity = _song_identity(1)
        # Both the metadata listing (limit=50, offset=0) and the count (limit=None)
        # route through the same natural song lookup.
        service.db.library.find_songs_with_tag.return_value = (song,)
        service.db.library.get_song.return_value = song
        service.db.library.resolve_song_identity.return_value = song_identity
        service.db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="title", value="Neon"),
            SongTagAssignment(name="artist", value="Synthwave Artist"),
            SongTagAssignment(name="album", value="Retro"),
        )

        result = service.get_tag_songs(electronic, limit=50, offset=0)

        assert result["total"] == 1
        assert len(result["songs"]) == 1
        assert result["songs"][0]["file_id"] == 1
        assert result["songs"][0]["title"] == "Neon"
        assert result["songs"][0]["artist"] == "Synthwave Artist"
        assert result["songs"][0]["album"] == "Retro"
        assert result["songs"][0]["path"] == "/music/1.flac"

        # The natural identity is forwarded unchanged; the list and count lookups
        # both use ``find_songs_with_tag`` with the exact natural identity.
        assert service.db.library.find_songs_with_tag.call_args_list == [
            ((electronic,), {"limit": 50, "offset": 0}),
            ((electronic,), {"limit": None}),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_numeric_looking_string_value_is_data_not_storage_pk(self) -> None:
        """A natural value '120' is forwarded verbatim; no int(tag_id) parsing."""
        service = _make_service()
        string_120 = TagRef(name="bpm", value="120")
        service.db.library.find_songs_with_tag.return_value = ()

        result = service.get_tag_songs(string_120, limit=50, offset=0)

        assert result == {"songs": [], "total": 0}
        assert service.db.library.find_songs_with_tag.call_args_list == [
            ((string_120,), {"limit": 50, "offset": 0}),
            ((string_120,), {"limit": None}),
        ]
        # The string "120" is never coerced into a storage primary key.
        service.db.get_tag.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_missing_natural_identity_returns_empty_result(self) -> None:
        """A tag that does not exist yields a deterministic empty result (no 404)."""
        service = _make_service()
        ghost = TagRef(name="genre", value="Does Not Exist")
        service.db.library.find_songs_with_tag.return_value = ()

        result = service.get_tag_songs(ghost, limit=50, offset=0)

        assert result == {"songs": [], "total": 0}
        service.db.library.get_song.assert_not_called()
