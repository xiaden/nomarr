"""Tests for ``nomarr.components.navidrome.navidrome_graph_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.navidrome.navidrome_graph_comp import (
    _edge_key,
    bulk_ensure_navidrome_file_links,
    bulk_resolve_files_to_navidrome_ids,
    bulk_resolve_navidrome_tracks_to_files,
    bulk_upsert_navidrome_plays,
    bulk_upsert_navidrome_tracks,
    delete_navidrome_tracks_cascade,
    ensure_navidrome_file_link,
    get_top_navidrome_plays,
    increment_navidrome_play,
    list_navidrome_track_keys,
    resolve_file_to_navidrome_track,
    resolve_navidrome_track_to_file,
    upsert_navidrome_play,
    upsert_navidrome_track,
)


@pytest.mark.unit
class TestEdgeKey:
    """Tests for ``_edge_key``."""

    def test_returns_16_char_hex_string(self) -> None:
        key = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_inputs_produce_same_key(self) -> None:
        assert _edge_key("navidrome_tracks/abc", "library_files/xyz") == _edge_key(
            "navidrome_tracks/abc", "library_files/xyz"
        )

    def test_different_inputs_produce_different_keys(self) -> None:
        assert _edge_key("navidrome_tracks/abc", "library_files/xyz") != _edge_key(
            "navidrome_tracks/abc", "library_files/other"
        )

    def test_order_matters(self) -> None:
        assert _edge_key("navidrome_tracks/abc", "library_files/xyz") != _edge_key(
            "library_files/xyz", "navidrome_tracks/abc"
        )


@pytest.mark.unit
class TestUpsertNavidromeTrack:
    def test_calls_app_upsert_nd_track(self) -> None:
        db = MagicMock()
        db.app.upsert_nd_track.return_value = None

        upsert_navidrome_track(db, "nd-42")

        db.app.upsert_nd_track.assert_called_once_with({"_key": "nd-42"})
        db.navidrome_tracks.upsert.assert_not_called()


@pytest.mark.unit
class TestBulkUpsertNavidromeTracks:
    def test_returns_zero_for_empty_list(self) -> None:
        db = MagicMock()

        result = bulk_upsert_navidrome_tracks(db, [])

        assert result == 0
        db.app.bulk_upsert_nd_tracks.assert_not_called()

    def test_delegates_to_app_bulk_upsert(self) -> None:
        db = MagicMock()
        db.app.bulk_upsert_nd_tracks.return_value = 3

        result = bulk_upsert_navidrome_tracks(db, ["a", "b", "c"])

        assert result == 3
        db.app.bulk_upsert_nd_tracks.assert_called_once_with(["a", "b", "c"])


@pytest.mark.unit
class TestEnsureNavidromeFileLink:
    def test_delegates_to_bulk_with_single_mapping(self) -> None:
        db = MagicMock()

        with patch("nomarr.components.navidrome.navidrome_graph_comp.bulk_ensure_navidrome_file_links") as mock_bulk:
            ensure_navidrome_file_link(db, "nd-1", "library_files/f1")

        mock_bulk.assert_called_once_with(db, [{"nd_id": "nd-1", "file_id": "library_files/f1"}])


@pytest.mark.unit
class TestBulkEnsureNavidromeFileLinks:
    def test_returns_zero_for_empty_mappings(self) -> None:
        db = MagicMock()

        result = bulk_ensure_navidrome_file_links(db, [])

        assert result == 0
        db.app.bulk_ensure_nd_file_links.assert_not_called()

    def test_delegates_to_app_bulk_link_helper(self) -> None:
        db = MagicMock()
        db.app.bulk_ensure_nd_file_links.return_value = 2
        mappings = [
            {"nd_id": "nd-1", "file_id": "library_files/f1"},
            {"nd_id": "nd-2", "file_id": "library_files/f2"},
        ]

        result = bulk_ensure_navidrome_file_links(db, mappings)

        assert result == 2
        db.app.bulk_ensure_nd_file_links.assert_called_once_with(mappings)


@pytest.mark.unit
class TestListNavidromeTrackKeys:
    def test_returns_all_keys_as_strings(self) -> None:
        db = MagicMock()
        db.app.list_nd_track_keys.return_value = ["key1", 2]

        result = list_navidrome_track_keys(db)

        assert result == ["key1", "2"]
        db.app.list_nd_track_keys.assert_called_once_with()


@pytest.mark.unit
class TestDeleteNavidromeTracksCascade:
    def test_returns_zero_for_empty_list(self) -> None:
        db = MagicMock()

        result = delete_navidrome_tracks_cascade(db, [])

        assert result == 0
        db.app.delete_nd_tracks_cascade.assert_not_called()

    def test_delegates_to_app_cascade_delete(self) -> None:
        db = MagicMock()
        db.app.delete_nd_tracks_cascade.return_value = 3

        result = delete_navidrome_tracks_cascade(db, ["nd-1", "nd-2", "nd-3"])

        assert result == 3
        db.app.delete_nd_tracks_cascade.assert_called_once_with(["nd-1", "nd-2", "nd-3"])


@pytest.mark.unit
class TestResolveNavidromeTrackToFile:
    def test_returns_app_result(self) -> None:
        db = MagicMock()
        db.app.resolve_nd_track_to_file.return_value = "library_files/f1"

        result = resolve_navidrome_track_to_file(db, "nd-1")

        assert result == "library_files/f1"
        db.app.resolve_nd_track_to_file.assert_called_once_with("nd-1")

    def test_returns_none_when_app_has_no_mapping(self) -> None:
        db = MagicMock()
        db.app.resolve_nd_track_to_file.return_value = None

        result = resolve_navidrome_track_to_file(db, "nd-1")

        assert result is None


@pytest.mark.unit
class TestResolveFileToNavidromeTrack:
    def test_returns_app_result(self) -> None:
        db = MagicMock()
        db.app.resolve_file_to_nd_track.return_value = "nd-42"

        result = resolve_file_to_navidrome_track(db, "library_files/f1")

        assert result == "nd-42"
        db.app.resolve_file_to_nd_track.assert_called_once_with("library_files/f1")

    def test_returns_none_when_app_has_no_mapping(self) -> None:
        db = MagicMock()
        db.app.resolve_file_to_nd_track.return_value = None

        result = resolve_file_to_navidrome_track(db, "library_files/f1")

        assert result is None


@pytest.mark.unit
class TestBulkResolveNavidromeTracksToFiles:
    def test_returns_empty_dict_when_no_ids(self) -> None:
        db = MagicMock()

        result = bulk_resolve_navidrome_tracks_to_files(db, [])

        assert result == {}
        db.app.bulk_resolve_nd_tracks_to_files.assert_not_called()

    def test_delegates_to_app_bulk_resolution(self) -> None:
        db = MagicMock()
        db.app.bulk_resolve_nd_tracks_to_files.return_value = {"nd-1": "library_files/f1", "nd-3": "library_files/f3"}

        result = bulk_resolve_navidrome_tracks_to_files(db, ["nd-1", "nd-2", "nd-3"])

        assert result == {"nd-1": "library_files/f1", "nd-3": "library_files/f3"}
        db.app.bulk_resolve_nd_tracks_to_files.assert_called_once_with(["nd-1", "nd-2", "nd-3"])


@pytest.mark.unit
class TestBulkResolveFilesToNavidromeIds:
    def test_returns_empty_dict_for_empty_input(self) -> None:
        db = MagicMock()

        result = bulk_resolve_files_to_navidrome_ids(db, [])

        assert result == {}
        db.app.bulk_resolve_files_to_nd_ids.assert_not_called()

    def test_delegates_to_app_bulk_reverse_resolution(self) -> None:
        db = MagicMock()
        db.app.bulk_resolve_files_to_nd_ids.return_value = {"library_files/f1": "nd-1"}

        result = bulk_resolve_files_to_navidrome_ids(db, ["library_files/f1", "library_files/f2"])

        assert result == {"library_files/f1": "nd-1"}
        db.app.bulk_resolve_files_to_nd_ids.assert_called_once_with(["library_files/f1", "library_files/f2"])


@pytest.mark.unit
class TestUpsertNavidromePlay:
    def test_skips_when_playcount_is_negative(self) -> None:
        db = MagicMock()

        upsert_navidrome_play(db, "user1", "nd-1", -1, 0)

        db.app.upsert_nd_playcount.assert_not_called()

    def test_delegates_to_app_upsert_playcount(self) -> None:
        db = MagicMock()
        db.app.upsert_nd_playcount.return_value = None

        upsert_navidrome_play(db, "user1", "nd-42", 5, 1700000000)

        db.app.upsert_nd_playcount.assert_called_once_with("user1", "nd-42", 5, 1700000000)


@pytest.mark.unit
class TestIncrementNavidromePlay:
    def test_delegates_to_app_increment(self) -> None:
        db = MagicMock()
        db.app.increment_nd_play.return_value = None

        increment_navidrome_play(db, "user1", "nd-42", 1701000000)

        db.app.increment_nd_play.assert_called_once_with("user1", "nd-42", 1701000000)


@pytest.mark.unit
class TestBulkUpsertNavidromePlays:
    def test_delegates_to_app_bulk_upsert(self) -> None:
        db = MagicMock()
        plays = [
            {"nd_id": "nd-1", "playcount": 5, "last_played": 1700000000},
            {"nd_id": "nd-2", "playcount": 3, "last_played": 1699000000},
        ]
        db.app.bulk_upsert_nd_plays.return_value = 2

        result = bulk_upsert_navidrome_plays(db, "user1", plays)

        assert result == 2
        db.app.bulk_upsert_nd_plays.assert_called_once_with("user1", plays)

    def test_returns_zero_for_empty_payload(self) -> None:
        db = MagicMock()
        db.app.bulk_upsert_nd_plays.return_value = 0

        result = bulk_upsert_navidrome_plays(db, "user1", [])

        assert result == 0
        db.app.bulk_upsert_nd_plays.assert_called_once_with("user1", [])


@pytest.mark.unit
class TestGetTopNavidromePlays:
    def test_returns_empty_when_top_n_is_zero(self) -> None:
        db = MagicMock()

        result = get_top_navidrome_plays(db, "user1", 0)

        assert result == []
        db.app.get_top_nd_plays.assert_not_called()

    def test_returns_empty_when_top_n_is_negative(self) -> None:
        db = MagicMock()

        result = get_top_navidrome_plays(db, "user1", -5)

        assert result == []
        db.app.get_top_nd_plays.assert_not_called()

    def test_coerces_rows_from_app(self) -> None:
        db = MagicMock()
        db.app.get_top_nd_plays.return_value = [
            {"nd_id": "nd-1", "file_id": "library_files/f1", "playcount": 10, "last_played": 1700000000},
            {"nd_id": "nd-2", "playcount": 3, "last_played": None},
        ]

        result = get_top_navidrome_plays(db, "user1", 5)

        assert len(result) == 2
        assert result[0]["nd_id"] == "nd-1"
        assert result[0]["file_id"] == "library_files/f1"
        assert result[0]["playcount"] == 10
        assert result[0]["last_played"] == 1700000000
        assert result[1]["nd_id"] == "nd-2"
        assert result[1]["file_id"] is None
        assert result[1]["playcount"] == 3
        assert result[1]["last_played"] is None
        db.app.get_top_nd_plays.assert_called_once_with("user1", 5)
