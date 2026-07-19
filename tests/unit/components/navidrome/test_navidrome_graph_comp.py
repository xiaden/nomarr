"""Tests for ``nomarr.components.navidrome.navidrome_graph_comp``.

Updated for PostgreSQL: all functions are synchronous, file IDs are ``int``,
edge keys replaced by JOIN tables, and the ``_edge_key`` function is removed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.navidrome.navidrome_graph_comp import (
    bulk_ensure_navidrome_file_links,
    bulk_resolve_files_to_navidrome_ids,
    bulk_resolve_navidrome_tracks_to_files,
    bulk_upsert_navidrome_plays,
    bulk_upsert_navidrome_tracks,
    delete_navidrome_tracks_cascade,
    ensure_navidrome_file_link,
    get_top_navidrome_plays,
    list_navidrome_track_keys,
    resolve_file_to_navidrome_track,
    resolve_navidrome_track_to_file,
    upsert_navidrome_track,
)


@pytest.mark.unit
class TestUpsertNavidromeTrack:
    def test_calls_app_upsert_nd_track(self) -> None:
        db = MagicMock()
        db.app.upsert_navidrome_track = MagicMock()

        upsert_navidrome_track(db, "nd-42")

        db.app.upsert_navidrome_track.assert_called_once_with(
            "nd-42", title=None, artist=None, album=None, file_path=None
        )


@pytest.mark.unit
class TestBulkUpsertNavidromeTracks:
    def test_returns_zero_for_empty_list(self) -> None:
        db = MagicMock()

        result = bulk_upsert_navidrome_tracks(db, [])

        assert result == 0
        db.app.bulk_upsert_navidrome_tracks.assert_not_called()

    def test_delegates_to_app_bulk_upsert(self) -> None:
        db = MagicMock()
        db.app.bulk_upsert_navidrome_tracks = MagicMock(return_value=3)

        result = bulk_upsert_navidrome_tracks(db, ["a", "b", "c"])

        assert result == 3
        db.app.bulk_upsert_navidrome_tracks.assert_called_once_with(["a", "b", "c"])


@pytest.mark.unit
class TestEnsureNavidromeFileLink:
    def test_delegates_to_app_map(self) -> None:
        db = MagicMock()
        db.app.map_navidrome_track_to_file = MagicMock()

        ensure_navidrome_file_link(db, "nd-1", 42)

        db.app.map_navidrome_track_to_file.assert_called_once_with("nd-1", 42)


@pytest.mark.unit
class TestBulkEnsureNavidromeFileLinks:
    def test_returns_zero_for_empty_mappings(self) -> None:
        db = MagicMock()

        result = bulk_ensure_navidrome_file_links(db, [])

        assert result == 0
        db.app.bulk_map_navidrome_tracks.assert_not_called()

    def test_delegates_to_app_bulk_map(self) -> None:
        db = MagicMock()
        db.app.bulk_map_navidrome_tracks = MagicMock(return_value=2)
        mappings = [
            {"nd_id": "nd-1", "file_id": 10},
            {"nd_id": "nd-2", "file_id": 20},
        ]

        result = bulk_ensure_navidrome_file_links(db, mappings)

        assert result == 2
        db.app.bulk_map_navidrome_tracks.assert_called_once_with(mappings)


@pytest.mark.unit
class TestListNavidromeTrackKeys:
    def test_returns_all_keys_as_strings(self) -> None:
        db = MagicMock()
        db.app.legacy_navidrome = MagicMock()
        db.app.legacy_navidrome.list_nd_track_keys = MagicMock(return_value=[1, 2])

        result = list_navidrome_track_keys(db)

        assert result == ["1", "2"]
        db.app.legacy_navidrome.list_nd_track_keys.assert_called_once_with()


@pytest.mark.unit
class TestDeleteNavidromeTracksCascade:
    def test_returns_zero_for_empty_list(self) -> None:
        db = MagicMock()

        result = delete_navidrome_tracks_cascade(db, [])

        assert result == 0

    def test_cascade_deletes_resolved_tracks(self) -> None:
        db = MagicMock()
        db.app.get_mapped_file_for_navidrome_track = MagicMock(side_effect=[10, None, 20])
        db.app.delete_navidrome_tracks_for_file = MagicMock(side_effect=[1, 1])

        result = delete_navidrome_tracks_cascade(db, ["nd-1", "nd-2", "nd-3"])

        assert result == 2
        assert db.app.get_mapped_file_for_navidrome_track.call_count == 3
        assert db.app.delete_navidrome_tracks_for_file.call_count == 2


@pytest.mark.unit
class TestResolveNavidromeTrackToFile:
    def test_returns_int_file_id(self) -> None:
        db = MagicMock()
        db.app.get_mapped_file_for_navidrome_track = MagicMock(return_value=42)

        result = resolve_navidrome_track_to_file(db, "nd-1")

        assert result == 42
        db.app.get_mapped_file_for_navidrome_track.assert_called_once_with("nd-1")

    def test_returns_none_when_no_mapping(self) -> None:
        db = MagicMock()
        db.app.get_mapped_file_for_navidrome_track = MagicMock(return_value=None)

        result = resolve_navidrome_track_to_file(db, "nd-1")

        assert result is None


@pytest.mark.unit
class TestResolveFileToNavidromeTrack:
    def test_returns_nd_id_string(self) -> None:
        db = MagicMock()
        db.app.resolve_file_to_navidrome_track = MagicMock(return_value="nd-42")

        result = resolve_file_to_navidrome_track(db, 10)

        assert result == "nd-42"
        db.app.resolve_file_to_navidrome_track.assert_called_once_with(10)

    def test_returns_none_when_no_mapping(self) -> None:
        db = MagicMock()
        db.app.resolve_file_to_navidrome_track = MagicMock(return_value=None)

        result = resolve_file_to_navidrome_track(db, 10)

        assert result is None


@pytest.mark.unit
class TestBulkResolveNavidromeTracksToFiles:
    def test_returns_empty_dict_when_no_ids(self) -> None:
        db = MagicMock()

        result = bulk_resolve_navidrome_tracks_to_files(db, [])

        assert result == {}

    def test_resolves_multiple_tracks(self) -> None:
        db = MagicMock()
        db.app.get_mapped_file_for_navidrome_track = MagicMock(side_effect=[10, None, 30])

        result = bulk_resolve_navidrome_tracks_to_files(db, ["nd-1", "nd-2", "nd-3"])

        assert result == {"nd-1": 10, "nd-3": 30}
        assert db.app.get_mapped_file_for_navidrome_track.call_count == 3


@pytest.mark.unit
class TestBulkResolveFilesToNavidromeIds:
    def test_returns_empty_dict_for_empty_input(self) -> None:
        db = MagicMock()

        result = bulk_resolve_files_to_navidrome_ids(db, [])

        assert result == {}

    def test_resolves_multiple_files(self) -> None:
        db = MagicMock()
        db.app.resolve_file_to_navidrome_track = MagicMock(side_effect=["nd-1", None])

        result = bulk_resolve_files_to_navidrome_ids(db, [10, 20])

        assert result == {10: "nd-1"}
        assert db.app.resolve_file_to_navidrome_track.call_count == 2


@pytest.mark.unit
class TestBulkUpsertNavidromePlays:
    def test_records_plays(self) -> None:
        db = MagicMock()
        db.app.record_navidrome_play = MagicMock(side_effect=[1, 1])
        plays = [
            {"nd_id": "nd-1", "playcount": 5, "last_played": 1700000000, "played_at": 1700000000},
            {"nd_id": "nd-2", "playcount": 3, "last_played": 1699000000, "played_at": 1699000000},
        ]

        result = bulk_upsert_navidrome_plays(db, "user1", plays)

        assert result == 2
        assert db.app.record_navidrome_play.call_count == 2

    def test_returns_zero_for_empty_payload(self) -> None:
        db = MagicMock()

        result = bulk_upsert_navidrome_plays(db, "user1", [])

        assert result == 0
        db.app.record_navidrome_play.assert_not_called()


@pytest.mark.unit
class TestGetTopNavidromePlays:
    def test_returns_empty_when_top_n_is_zero(self) -> None:
        db = MagicMock()

        result = get_top_navidrome_plays(db, "user1", 0)

        assert result == []
        db.app.get_top_navidrome_plays.assert_not_called()

    def test_returns_empty_when_top_n_is_negative(self) -> None:
        db = MagicMock()

        result = get_top_navidrome_plays(db, "user1", -5)

        assert result == []
        db.app.get_top_navidrome_plays.assert_not_called()

    def test_coerces_rows_to_track_play_data(self) -> None:
        db = MagicMock()
        db.app.get_top_navidrome_plays = MagicMock(
            return_value=[
                {
                    "nd_id": "nd-1",
                    "file_id": 10,
                    "playcount": 10,
                    "last_played": 1700000000,
                },
                {"nd_id": "nd-2", "playcount": 3, "last_played": None},
            ]
        )

        result = get_top_navidrome_plays(db, "user1", 5)

        assert len(result) == 2
        assert result[0]["nd_id"] == "nd-1"
        assert result[0]["file_id"] == 10
        assert result[0]["playcount"] == 10
        assert result[0]["last_played"] == 1700000000
        assert result[1]["nd_id"] == "nd-2"
        assert result[1]["file_id"] is None
        assert result[1]["playcount"] == 3
        assert result[1]["last_played"] is None
        db.app.get_top_navidrome_plays.assert_called_once_with("user1", 5)
