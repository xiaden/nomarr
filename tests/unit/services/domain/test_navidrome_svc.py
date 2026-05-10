"""Tests for ``nomarr.services.domain.navidrome_svc`` playlist generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto import NavidromeGeneratePlaylistsResult
from nomarr.helpers.exceptions import MisconfiguredError
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
        "file_ids": ["library_files/track-1", "library_files/track-2"],
    }


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceGeneratePlaylists:
    """Tests for ``NavidromeService.generate_playlists``."""

    def test_generate_playlists_raises_when_library_key_empty(self) -> None:
        """Empty ``library_key`` should raise ``MisconfiguredError``."""
        service, _ = _make_service({"library_key": ""})

        with pytest.raises(MisconfiguredError, match="library_key not configured"):
            service.generate_playlists("user-1")

    def test_generate_playlists_reads_pp_keys_not_playlist_keys(self) -> None:
        """Service should read the current ``pp_*`` config keys only."""
        config_values = {
            "library_key": "lib-main",
            "pp_backbone_id": "effnet-discogs",
            "pp_half_life_days": 45.0,
            "pp_top_n": 123,
            "pp_max_songs": 77,
            "pp_min_songs": 11,
            "pp_min_play_count": 4,
            "pp_max_genre_playlists": 6,
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
            service.generate_playlists("user-1")

        called_keys = [call.args[0] for call in config_service.get.call_args_list]
        assert called_keys == [
            "pp_backbone_id",
            "library_key",
            "pp_type_familiar",
            "pp_type_discovery",
            "pp_type_hidden_gems",
            "pp_type_genre",
            "pp_type_universal",
            "pp_max_songs",
            "pp_min_songs",
            "pp_max_genre_playlists",
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
                "library_key": "lib-main",
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
            service.generate_playlists("user-1")

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
            result = service.generate_playlists("user-1")

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
            result = service.generate_playlists("user-1")

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
            service.generate_playlists("user-1", max_genre_playlists=30)

        assert mock_generate.call_args.kwargs["max_genre_playlists"] == 25


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceSync:
    """Tests for ``NavidromeService.sync_navidrome``."""

    def test_sync_navidrome_passes_live_path_prefix_map(self) -> None:
        """Service should parse and forward the live Navidrome path-prefix config."""
        service, _ = _make_service(
            {
                "navidrome_api_user": "nav-user",
                "navidrome_path_prefix_map": "/music:D:/Media,/alt:/mnt/library",
            },
        )
        mock_client = MagicMock()

        with (
            patch.object(service, "_get_client", return_value=mock_client),
            patch(
                "nomarr.services.domain.navidrome_svc.sync_navidrome",
                return_value={
                    "total_songs": 0,
                    "resolved": 0,
                    "unresolved": 0,
                    "tracks_upserted": 0,
                    "play_edges_upserted": 0,
                    "orphans_removed": 0,
                    "duration_ms": 0,
                },
            ) as mock_sync,
        ):
            service.sync_navidrome()

        assert mock_sync.call_args.kwargs["path_prefix_map"] == [
            ("/music", "D:/Media"),
            ("/alt", "/mnt/library"),
        ]
        assert mock_sync.call_args.kwargs["user_id"] == "nav-user"

    def test_sync_navidrome_allows_empty_remap_targets(self) -> None:
        """Service should preserve prefix-strip mappings with empty targets."""
        service, _ = _make_service(
            {
                "navidrome_api_user": "nav-user",
                "navidrome_path_prefix_map": "/music/:,/alt:/mnt/library",
            },
        )
        mock_client = MagicMock()

        with (
            patch.object(service, "_get_client", return_value=mock_client),
            patch(
                "nomarr.services.domain.navidrome_svc.sync_navidrome",
                return_value={
                    "total_songs": 0,
                    "resolved": 0,
                    "unresolved": 0,
                    "tracks_upserted": 0,
                    "play_edges_upserted": 0,
                    "orphans_removed": 0,
                    "duration_ms": 0,
                },
            ) as mock_sync,
        ):
            service.sync_navidrome()

        assert mock_sync.call_args.kwargs["path_prefix_map"] == [
            ("/music/", ""),
            ("/alt", "/mnt/library"),
        ]
        assert mock_sync.call_args.kwargs["user_id"] == "nav-user"


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeServiceDescriptorResolution:
    """Tests for ``NavidromeService.resolve_files_to_descriptors``."""

    def test_resolve_files_to_descriptors_returns_descriptor_map(self) -> None:
        service, _ = _make_service()

        with (
            patch(
                "nomarr.services.domain.navidrome_svc.get_files_by_ids_with_tags",
                return_value=[{"_id": "library_files/track-1", "_key": "track-1"}],
            ) as mock_get_files,
            patch(
                "nomarr.services.domain.navidrome_svc.build_track_descriptor",
                return_value={
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "album_artist": "",
                    "duration_ms": None,
                    "track_number": None,
                    "disc_number": None,
                    "year": None,
                    "musicbrainz_track_id": None,
                    "musicbrainz_recording_id": None,
                    "nomarr_file_key": "track-1",
                },
            ) as mock_build,
        ):
            descriptors = service.resolve_files_to_descriptors(["library_files/track-1"])

        assert descriptors == {
            "library_files/track-1": {
                "title": "Song A",
                "artist": "Artist A",
                "album": "Album A",
                "album_artist": "",
                "duration_ms": None,
                "track_number": None,
                "disc_number": None,
                "year": None,
                "musicbrainz_track_id": None,
                "musicbrainz_recording_id": None,
                "nomarr_file_key": "track-1",
            },
        }
        mock_get_files.assert_called_once_with(service._db, ["library_files/track-1"])
        mock_build.assert_called_once()

    def test_resolve_files_to_descriptors_ignores_docs_without_id(self) -> None:
        service, _ = _make_service()

        with patch(
            "nomarr.services.domain.navidrome_svc.get_files_by_ids_with_tags",
            return_value=[{"_key": "missing-id"}],
        ):
            descriptors = service.resolve_files_to_descriptors(["library_files/track-1"])

        assert descriptors == {}

    def test_resolve_files_to_descriptors_propagates_query_errors(self) -> None:
        service, _ = _make_service()

        with patch(
            "nomarr.services.domain.navidrome_svc.get_files_by_ids_with_tags",
            side_effect=RuntimeError("query failed"),
        ), pytest.raises(RuntimeError, match="query failed"):
            service.resolve_files_to_descriptors(["library_files/track-1"])

    def test_resolve_files_to_descriptors_propagates_build_errors(self) -> None:
        service, _ = _make_service()

        with (
            patch(
                "nomarr.services.domain.navidrome_svc.get_files_by_ids_with_tags",
                return_value=[{"_id": "library_files/track-1"}],
            ),
            patch(
                "nomarr.services.domain.navidrome_svc.build_track_descriptor",
                side_effect=ValueError("bad descriptor"),
            ),pytest.raises(ValueError, match="bad descriptor")
        ):
            service.resolve_files_to_descriptors(["library_files/track-1"])
