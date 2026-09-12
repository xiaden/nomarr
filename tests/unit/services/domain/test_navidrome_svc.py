"""Tests for ``nomarr.services.domain.navidrome_svc`` playlist generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto import NavidromeGeneratePlaylistsResult
from nomarr.helpers.song_locator_codec import encode_song_locator

# MisconfiguredError import removed per ADR-036 (library_key no longer checked)
from nomarr.services.domain.navidrome_svc import NavidromeConfig, NavidromeService


def _make_service(config_values: dict[str, object] | None = None) -> tuple[NavidromeService, MagicMock]:
    """Build a NavidromeService with a configurable config-service mock."""
    values = config_values or {}
    config_service = MagicMock()
    config_service.get.side_effect = lambda key, default=None: values.get(key, default)

    service = NavidromeService(
        db=MagicMock(),
        cfg=NavidromeConfig(namespace="nom"),
        config_service=config_service,
    )
    return service, config_service


def _playlist_entry() -> dict[str, object]:
    """Return a representative personal playlist entry."""
    return {
        "playlist_type": "familiar",
        "playlist_name": "Familiar Favorites",
        "file_ids": [
            1,
            f"{'songs'}/track-2",
        ],
    }


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceGeneratePlaylists:
    """Tests for ``NavidromeService.generate_playlists``."""

    def test_generate_playlists_reads_pp_keys_not_playlist_keys(self) -> None:
        """Service should read the current ``pp_*`` config keys only."""
        config_values = {
            # library_key removed per ADR-036
            "pp_backbone_id": "effnet-discogs",
            "pp_half_life_days": 45.0,
            "pp_top_n": 123,
            "pp_max_songs": 77,
            "pp_min_songs": 11,
            "pp_min_play_count": 4,
            "pp_max_genre_playlists": 6,
            "pp_max_clusters": 10,
            "pp_type_familiar": True,
            "pp_type_discovery": True,
            "pp_type_hidden_gems": True,
            "pp_type_genre": True,
            "pp_type_universal": True,
        }
        service, config_service = _make_service(config_values)

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_playlists",
            return_value=[_playlist_entry()],
        ):
            service.generate_playlists("user-1", top_plays=[])

        called_keys = [call.args[0] for call in config_service.get.call_args_list]
        assert called_keys == [
            "pp_backbone_id",
            # "library_key" removed per ADR-036
            "pp_type_familiar",
            "pp_type_discovery",
            "pp_type_hidden_gems",
            "pp_type_genre",
            "pp_type_universal",
            "pp_max_songs",
            "pp_min_songs",
            "pp_max_genre_playlists",
            "pp_max_clusters",
            "pp_half_life_days",
            "pp_top_n",
            "pp_min_play_count",
        ]
        assert "vector_backbone_id" not in called_keys
        assert not any(key.startswith("playlist_") for key in called_keys)

    def test_generate_playlists_derives_enabled_types_from_type_flags(self) -> None:
        """Boolean ``pp_type_*`` flags should drive the workflow enabled-types list."""
        service, _ = _make_service(
            {
                # library_key removed per ADR-036
                "pp_type_familiar": True,
                "pp_type_discovery": False,
                "pp_type_hidden_gems": True,
                "pp_type_genre": False,
                "pp_type_universal": True,
            },
        )

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_playlists",
            return_value=[_playlist_entry()],
        ) as mock_generate:
            service.generate_playlists("user-1", top_plays=[])

        assert mock_generate.call_args.kwargs["enabled_types"] == [
            "familiar",
            "hidden_gems",
            "universal",
        ]

    def test_generate_playlists_returns_result_dto(self) -> None:
        """Successful service call should return the typed result DTO."""
        service, _ = _make_service({"library_key": "lib-main"})

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_playlists",
            return_value=[_playlist_entry()],
        ):
            result = service.generate_playlists("user-1", top_plays=[])

        assert isinstance(result, NavidromeGeneratePlaylistsResult)
        assert result.status == "ok"
        assert result.message == ""
        assert result.playlists == [_playlist_entry()]

    def test_generate_playlists_returns_no_data_when_workflow_returns_empty(self) -> None:
        """Empty workflow results should map to the no-data DTO variant."""
        service, _ = _make_service({"library_key": "lib-main"})

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_playlists",
            return_value=[],
        ):
            result = service.generate_playlists("user-1", top_plays=[])

        assert isinstance(result, NavidromeGeneratePlaylistsResult)
        assert result.status == "no_data"
        assert result.message == "No taste profile or no playlists generated"
        assert result.playlists == []

    def test_generate_playlists_caps_max_genre_playlists_at_25(self) -> None:
        """Explicit overrides above the endpoint ceiling should be clamped before workflow dispatch."""
        service, _ = _make_service({"library_key": "lib-main"})

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_playlists",
            return_value=[_playlist_entry()],
        ) as mock_generate:
            service.generate_playlists("user-1", top_plays=[], max_genre_playlists=30)

        assert mock_generate.call_args.kwargs["max_genre_playlists"] == 25


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceDescriptorResolution:
    """Tests for ``NavidromeService.resolve_files_to_descriptors``."""

    _UUID = "6313b0d3-d270-47a8-9e0d-21e8255107e3"

    @staticmethod
    def _token(path: str = "songs/a.mp3") -> str:
        return encode_song_locator(
            SongIdentity(
                library=LibraryIdentity(library_uuid=TestNavidromeServiceDescriptorResolution._UUID),
                normalized_path=path,
            )
        )

    @staticmethod
    def _configure_library(service: NavidromeService, *, present: bool = True) -> None:
        service._db.library.get_library_by_uuid.return_value = (
            Library(name="Music", root_path="/music", library_uuid=TestNavidromeServiceDescriptorResolution._UUID)
            if present
            else None
        )

    @staticmethod
    def _descriptor() -> dict[str, object]:
        return {
            "title": "Song A",
            "artist": "Artist A",
            "album": "Album A",
            "album_artist": "",
            "duration_ms": None,
            "track_number": None,
            "disc_number": None,
            "year": None,
            "nomarr_file_key": "track-1",
        }

    def test_resolve_files_to_descriptors_returns_descriptor_map(self) -> None:
        service, _ = _make_service()
        self._configure_library(service)
        token = self._token()
        descriptor = self._descriptor()

        with patch(
            "nomarr.services.domain.navidrome_svc.descriptor_for_locator",
            return_value=descriptor,
        ) as mock_build:
            descriptors = service.resolve_files_to_descriptors([token])

        assert descriptors == {token: descriptor}
        mock_build.assert_called_once()
        resolved_locator = mock_build.call_args.args[1]
        assert resolved_locator.normalized_path == "songs/a.mp3"

    def test_resolve_files_to_descriptors_ignores_malformed_tokens(self) -> None:
        service, _ = _make_service()
        self._configure_library(service)

        with patch("nomarr.services.domain.navidrome_svc.descriptor_for_locator") as mock_build:
            descriptors = service.resolve_files_to_descriptors(["not-a-valid-token"])

        assert descriptors == {}
        mock_build.assert_not_called()

    def test_resolve_files_to_descriptors_ignores_unknown_library(self) -> None:
        service, _ = _make_service()
        self._configure_library(service, present=False)

        with patch("nomarr.services.domain.navidrome_svc.descriptor_for_locator") as mock_build:
            descriptors = service.resolve_files_to_descriptors([self._token()])

        assert descriptors == {}
        mock_build.assert_not_called()

    def test_resolve_files_to_descriptors_propagates_descriptor_errors(self) -> None:
        service, _ = _make_service()
        self._configure_library(service)

        with (
            patch(
                "nomarr.services.domain.navidrome_svc.descriptor_for_locator",
                side_effect=RuntimeError("query failed"),
            ),
            pytest.raises(RuntimeError, match="query failed"),
        ):
            service.resolve_files_to_descriptors([self._token()])

    def test_resolve_files_to_descriptors_empty_input(self) -> None:
        service, _ = _make_service()

        assert service.resolve_files_to_descriptors([]) == {}


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceSmartPlaylistGeneration:
    """Tests for ``NavidromeService.generate_playlist``."""

    def test_generate_playlist_does_not_push_to_navidrome(self) -> None:
        """Smart playlist generation should return structure only (no backend push)."""
        service, _ = _make_service()

        with patch(
            "nomarr.services.domain.navidrome_svc.generate_smart_playlist_workflow",
            return_value={"name": "Mix", "all": []},
        ):
            result = service.generate_playlist(query="tag:rock > 0.5", playlist_name="Mix")

        assert result.playlist_structure == {"name": "Mix", "all": []}
