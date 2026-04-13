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


def _mock_edge_ns() -> MagicMock:
    """Return a fresh MagicMock representing a built edge namespace."""
    return MagicMock()


class TestEdgeKey:
    """Tests for ``_edge_key``."""

    @pytest.mark.unit
    def test_returns_16_char_hex_string(self) -> None:
        key = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    @pytest.mark.unit
    def test_same_inputs_produce_same_key(self) -> None:
        k1 = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        k2 = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        assert k1 == k2

    @pytest.mark.unit
    def test_different_inputs_produce_different_keys(self) -> None:
        k1 = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        k2 = _edge_key("navidrome_tracks/abc", "library_files/other")
        assert k1 != k2

    @pytest.mark.unit
    def test_order_matters(self) -> None:
        k1 = _edge_key("navidrome_tracks/abc", "library_files/xyz")
        k2 = _edge_key("library_files/xyz", "navidrome_tracks/abc")
        assert k1 != k2


@pytest.mark.unit
class TestUpsertNavidromeTrack:
    """Tests for ``upsert_navidrome_track``."""

    def test_calls_key_upsert_with_nd_id(self) -> None:
        mock_db = MagicMock()
        upsert_navidrome_track(mock_db, "nd-42")
        mock_db.navidrome_tracks._key.upsert.assert_called_once_with([{"_key": "nd-42"}], match_field="_key")

    def test_returns_none(self) -> None:
        mock_db = MagicMock()
        result = upsert_navidrome_track(mock_db, "nd-42")  # type: ignore[func-returns-value]
        assert result is None


@pytest.mark.unit
class TestBulkUpsertNavidromeTracks:
    """Tests for ``bulk_upsert_navidrome_tracks``."""

    def test_returns_zero_for_empty_list(self) -> None:
        mock_db = MagicMock()
        result = bulk_upsert_navidrome_tracks(mock_db, [])
        assert result == 0
        mock_db.navidrome_tracks._key.upsert.assert_not_called()

    def test_upserts_all_tracks_and_returns_count(self) -> None:
        mock_db = MagicMock()
        result = bulk_upsert_navidrome_tracks(mock_db, ["a", "b", "c"])
        assert result == 3
        mock_db.navidrome_tracks._key.upsert.assert_called_once_with(
            [{"_key": "a"}, {"_key": "b"}, {"_key": "c"}],
            match_field="_key",
        )

    def test_single_track_returns_one(self) -> None:
        mock_db = MagicMock()
        result = bulk_upsert_navidrome_tracks(mock_db, ["solo"])
        assert result == 1


@pytest.mark.unit
class TestEnsureNavidromeFileLink:
    """Tests for ``ensure_navidrome_file_link``."""

    def test_delegates_to_bulk_with_single_mapping(self) -> None:
        mock_db = MagicMock()
        with patch("nomarr.components.navidrome.navidrome_graph_comp.bulk_ensure_navidrome_file_links") as mock_bulk:
            ensure_navidrome_file_link(mock_db, "nd-1", "library_files/f1")
            mock_bulk.assert_called_once_with(mock_db, [{"nd_id": "nd-1", "file_id": "library_files/f1"}])


@pytest.mark.unit
class TestBulkEnsureNavidromeFileLinks:
    """Tests for ``bulk_ensure_navidrome_file_links``."""

    def test_returns_zero_for_empty_mappings(self) -> None:
        mock_db = MagicMock()
        result = bulk_ensure_navidrome_file_links(mock_db, [])
        assert result == 0

    def test_inserts_new_link_when_none_exists(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 0
        mock_ns._from.get.many.return_value = []

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = bulk_ensure_navidrome_file_links(mock_db, [{"nd_id": "nd-1", "file_id": "library_files/f1"}])

        assert result == 1
        mock_ns.insert.assert_called_once()
        inserted = mock_ns.insert.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0]["_from"] == "navidrome_tracks/nd-1"
        assert inserted[0]["_to"] == "library_files/f1"

    def test_skips_link_that_already_exists(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 1
        mock_ns._from.get.many.return_value = [{"_to": "library_files/f1"}]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = bulk_ensure_navidrome_file_links(mock_db, [{"nd_id": "nd-1", "file_id": "library_files/f1"}])

        assert result == 0
        mock_ns.insert.assert_not_called()


@pytest.mark.unit
class TestListNavidromeTrackKeys:
    """Tests for ``list_navidrome_track_keys``."""

    def test_returns_all_keys_as_strings(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.count.return_value = 2
        mock_db.navidrome_tracks._key.collect.return_value = ["key1", "key2"]

        result = list_navidrome_track_keys(mock_db)

        assert result == ["key1", "key2"]
        mock_db.navidrome_tracks._key.collect.assert_called_once_with(limit=2)

    def test_returns_empty_list_when_no_tracks(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.count.return_value = 0
        mock_db.navidrome_tracks._key.collect.return_value = []

        result = list_navidrome_track_keys(mock_db)

        assert result == []


@pytest.mark.unit
class TestDeleteNavidromeTracksCascade:
    """Tests for ``delete_navidrome_tracks_cascade``."""

    def test_returns_zero_for_empty_list(self) -> None:
        mock_db = MagicMock()
        result = delete_navidrome_tracks_cascade(mock_db, [])
        assert result == 0
        mock_db.navidrome_tracks.cascade.assert_not_called()

    def test_cascades_with_prefixed_ids_and_returns_count(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.cascade.return_value = 3
        result = delete_navidrome_tracks_cascade(mock_db, ["nd-1", "nd-2", "nd-3"])
        assert result == 3
        mock_db.navidrome_tracks.cascade.assert_called_once_with(
            ["navidrome_tracks/nd-1", "navidrome_tracks/nd-2", "navidrome_tracks/nd-3"]
        )


@pytest.mark.unit
class TestResolveNavidromeTrackToFile:
    """Tests for ``resolve_navidrome_track_to_file``."""

    def test_returns_file_id_when_edge_exists(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.traversal.return_value = [{"_id": "library_files/f1"}]

        result = resolve_navidrome_track_to_file(mock_db, "nd-1")

        assert result == "library_files/f1"
        mock_db.navidrome_tracks.traversal.assert_called_once_with("navidrome_tracks/nd-1", edge="has_nd_id", limit=1)

    def test_returns_none_when_no_edge(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.traversal.return_value = []

        result = resolve_navidrome_track_to_file(mock_db, "nd-1")

        assert result is None

    def test_returns_none_when_id_missing_from_doc(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_tracks.traversal.return_value = [{}]

        result = resolve_navidrome_track_to_file(mock_db, "nd-1")

        assert result is None


@pytest.mark.unit
class TestResolveFileToNavidromeTrack:
    """Tests for ``resolve_file_to_navidrome_track``."""

    def test_returns_track_key_when_edge_exists(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns._to.get.many.return_value = [{"_from": "navidrome_tracks/nd-42"}]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = resolve_file_to_navidrome_track(mock_db, "library_files/f1")

        assert result == "nd-42"

    def test_returns_none_when_no_edge(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns._to.get.many.return_value = []

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = resolve_file_to_navidrome_track(mock_db, "library_files/f1")

        assert result is None

    def test_returns_none_when_from_absent(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns._to.get.many.return_value = [{}]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = resolve_file_to_navidrome_track(mock_db, "library_files/f1")

        assert result is None


@pytest.mark.unit
class TestBulkResolveNavidromeTracksToFiles:
    """Tests for ``bulk_resolve_navidrome_tracks_to_files``."""

    def test_returns_empty_dict_when_no_ids(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp.resolve_navidrome_track_to_file",
            return_value=None,
        ):
            result = bulk_resolve_navidrome_tracks_to_files(mock_db, [])
        assert result == {}

    def test_maps_resolved_ids_and_omits_nones(self) -> None:
        mock_db = MagicMock()
        side_effects = ["library_files/f1", None, "library_files/f3"]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp.resolve_navidrome_track_to_file",
            side_effect=side_effects,
        ):
            result = bulk_resolve_navidrome_tracks_to_files(mock_db, ["nd-1", "nd-2", "nd-3"])

        assert result == {"nd-1": "library_files/f1", "nd-3": "library_files/f3"}


@pytest.mark.unit
class TestBulkResolveFilesToNavidromeIds:
    """Tests for ``bulk_resolve_files_to_navidrome_ids``."""

    def test_returns_empty_dict_for_empty_input(self) -> None:
        mock_db = MagicMock()
        result = bulk_resolve_files_to_navidrome_ids(mock_db, [])
        assert result == {}

    def test_maps_file_ids_to_track_keys(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns._to.get.many.side_effect = [
            [{"_from": "navidrome_tracks/nd-1"}],
            [],
        ]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = bulk_resolve_files_to_navidrome_ids(mock_db, ["library_files/f1", "library_files/f2"])

        assert result == {"library_files/f1": "nd-1"}


@pytest.mark.unit
class TestUpsertNavidromePlay:
    """Tests for ``upsert_navidrome_play``."""

    def test_skips_when_playcount_is_negative(self) -> None:
        mock_db = MagicMock()
        with patch("nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace") as mock_build:
            upsert_navidrome_play(mock_db, "user1", "nd-1", -1, 0)
            mock_build.assert_not_called()

    def test_inserts_bucket_and_edge_when_no_existing_play(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 0
        mock_ns._from.get.many.return_value = []

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            upsert_navidrome_play(mock_db, "user1", "nd-42", 5, 1700000000)

        mock_db.navidrome_playcounts._key.upsert.assert_called_once()
        mock_ns.insert.assert_called_once()
        edge = mock_ns.insert.call_args[0][0][0]
        assert edge["_from"] == "navidrome_tracks/nd-42"
        assert edge["last_played"] == 1700000000

    def test_removes_old_bucket_when_user_already_has_play(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 1
        mock_ns._from.get.many.return_value = [{"_id": "has_plays/eid", "_to": "navidrome_playcounts/3:user1"}]
        mock_db.navidrome_playcounts.get.return_value = {
            "_id": "navidrome_playcounts/3:user1",
            "userid": "user1",
            "playcount": 3,
        }

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            upsert_navidrome_play(mock_db, "user1", "nd-42", 5, 1700000000)

        mock_ns.delete.assert_called_once_with(["has_plays/eid"])


@pytest.mark.unit
class TestIncrementNavidromePlay:
    """Tests for ``increment_navidrome_play``."""

    def test_increments_playcount_by_one_from_zero(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 0
        mock_ns._from.get.many.return_value = []

        with (
            patch(
                "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
                return_value=mock_ns,
            ),
            patch("nomarr.components.navidrome.navidrome_graph_comp.upsert_navidrome_play") as mock_upsert,
        ):
            increment_navidrome_play(mock_db, "user1", "nd-42", 1701000000)

        mock_upsert.assert_called_once_with(mock_db, "user1", "nd-42", 1, 1701000000)

    def test_increments_from_existing_count(self) -> None:
        mock_db = MagicMock()
        mock_ns = _mock_edge_ns()
        mock_ns.count.return_value = 1
        mock_ns._from.get.many.return_value = [{"_id": "has_plays/eid", "_to": "navidrome_playcounts/7:user1"}]
        mock_db.navidrome_playcounts.get.return_value = {
            "_id": "navidrome_playcounts/7:user1",
            "userid": "user1",
            "playcount": 7,
        }

        with (
            patch(
                "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
                return_value=mock_ns,
            ),
            patch("nomarr.components.navidrome.navidrome_graph_comp.upsert_navidrome_play") as mock_upsert,
        ):
            increment_navidrome_play(mock_db, "user1", "nd-42", 1701000000)

        mock_upsert.assert_called_once_with(mock_db, "user1", "nd-42", 8, 1701000000)


@pytest.mark.unit
class TestBulkUpsertNavidromePlays:
    """Tests for ``bulk_upsert_navidrome_plays``."""

    def test_returns_zero_for_empty_plays_after_clearing(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_playcounts.count.return_value = 0
        mock_db.navidrome_playcounts.userid.get.many.return_value = []
        mock_ns = _mock_edge_ns()

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = bulk_upsert_navidrome_plays(mock_db, "user1", [])

        assert result == 0

    def test_inserts_edges_for_provided_plays(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_playcounts.count.return_value = 0
        mock_db.navidrome_playcounts.userid.get.many.return_value = []
        mock_ns = _mock_edge_ns()

        plays = [
            {"nd_id": "nd-1", "playcount": 5, "last_played": 1700000000},
            {"nd_id": "nd-2", "playcount": 3, "last_played": 1699000000},
        ]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = bulk_upsert_navidrome_plays(mock_db, "user1", plays)

        assert result == 2
        mock_ns.insert.assert_called_once()
        edges = mock_ns.insert.call_args[0][0]
        assert len(edges) == 2
        assert edges[0]["_from"] == "navidrome_tracks/nd-1"
        assert edges[1]["_from"] == "navidrome_tracks/nd-2"

    def test_clears_existing_buckets_before_insert(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_playcounts.count.return_value = 1
        mock_db.navidrome_playcounts.userid.get.many.return_value = [{"_id": "navidrome_playcounts/5:user1"}]
        mock_ns = _mock_edge_ns()
        mock_ns._to.delete = MagicMock()

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            bulk_upsert_navidrome_plays(mock_db, "user1", [])

        mock_ns._to.delete.assert_called_once_with("navidrome_playcounts/5:user1")
        mock_db.navidrome_playcounts.userid.delete.assert_called_once_with("user1")


@pytest.mark.unit
class TestGetTopNavidromePlays:
    """Tests for ``get_top_navidrome_plays``."""

    def test_returns_empty_when_top_n_is_zero(self) -> None:
        mock_db = MagicMock()
        result = get_top_navidrome_plays(mock_db, "user1", 0)
        assert result == []
        mock_db.navidrome_playcounts.userid.get.many.assert_not_called()

    def test_returns_empty_when_top_n_is_negative(self) -> None:
        mock_db = MagicMock()
        result = get_top_navidrome_plays(mock_db, "user1", -5)
        assert result == []

    def test_returns_empty_when_no_buckets(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_playcounts.count.return_value = 0
        mock_db.navidrome_playcounts.userid.get.many.return_value = []
        mock_ns = _mock_edge_ns()

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            return_value=mock_ns,
        ):
            result = get_top_navidrome_plays(mock_db, "user1", 10)

        assert result == []

    def test_returns_top_plays_sorted_by_playcount(self) -> None:
        mock_db = MagicMock()
        mock_db.navidrome_playcounts.count.return_value = 2
        mock_db.navidrome_playcounts.userid.get.many.return_value = [
            {"_id": "navidrome_playcounts/3:user1", "userid": "user1", "playcount": 3},
            {"_id": "navidrome_playcounts/10:user1", "userid": "user1", "playcount": 10},
        ]
        mock_plays_ns = _mock_edge_ns()
        mock_has_nd_ns = _mock_edge_ns()

        # First bucket (playcount=10) edges
        mock_plays_ns._to.get.side_effect = [
            [{"_from": "navidrome_tracks/nd-1", "last_played": 1700000000}],
            [],
        ]
        mock_has_nd_ns._from.get.return_value = [{"_to": "library_files/f1"}]

        with patch(
            "nomarr.components.navidrome.navidrome_graph_comp._build_edge_namespace",
            side_effect=[mock_plays_ns, mock_has_nd_ns],
        ):
            result = get_top_navidrome_plays(mock_db, "user1", 5)

        assert len(result) == 1
        assert result[0]["nd_id"] == "nd-1"
        assert result[0]["playcount"] == 10
        assert result[0]["file_id"] == "library_files/f1"
        assert result[0]["last_played"] == 1700000000
