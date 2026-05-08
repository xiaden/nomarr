# ruff: noqa: N999
"""Unit tests for V029/V030 raw-output-stream migrations."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from arango.exceptions import CollectionCreateError, IndexCreateError

from nomarr.migrations.V029_raw_output_streams import upgrade as upgrade_v029
from nomarr.migrations.V030_drop_segment_scores_stats import upgrade as upgrade_v030


@pytest.mark.unit
@pytest.mark.mocked
class TestV029RawOutputStreams:
    """Tests for creation of canonical raw-output-stream collections."""

    def test_creates_missing_collections_and_indexes(self) -> None:
        db = MagicMock()
        file_edge_coll = MagicMock()
        output_edge_coll = MagicMock()
        db.has_collection.side_effect = lambda _name: False
        db.collection.side_effect = lambda name: {
            "file_has_output_stream": file_edge_coll,
            "output_has_stream": output_edge_coll,
        }[name]

        upgrade_v029(db)

        assert db.create_collection.call_args_list == [
            call("ml_output_streams"),
            call("file_has_output_stream", edge=True),
            call("output_has_stream", edge=True),
        ]
        file_edge_coll.add_persistent_index.assert_has_calls(
            [
                call(fields=["_from", "_to"], unique=True),
                call(fields=["_from"]),
                call(fields=["_to"]),
            ]
        )
        output_edge_coll.add_persistent_index.assert_has_calls(
            [
                call(fields=["_from", "_to"], unique=True),
                call(fields=["_from"]),
                call(fields=["_to"]),
            ]
        )

    def test_safe_rerun_skips_existing_collections_but_reapplies_index_guards(self) -> None:
        db = MagicMock()
        file_edge_coll = MagicMock()
        output_edge_coll = MagicMock()
        db.has_collection.side_effect = lambda _name: True
        db.collection.side_effect = lambda name: {
            "file_has_output_stream": file_edge_coll,
            "output_has_stream": output_edge_coll,
        }[name]

        upgrade_v029(db)

        db.create_collection.assert_not_called()
        file_edge_coll.add_persistent_index.assert_has_calls(
            [
                call(fields=["_from", "_to"], unique=True),
                call(fields=["_from"]),
                call(fields=["_to"]),
            ]
        )
        output_edge_coll.add_persistent_index.assert_has_calls(
            [
                call(fields=["_from", "_to"], unique=True),
                call(fields=["_from"]),
                call(fields=["_to"]),
            ]
        )

    def test_suppresses_duplicate_create_and_index_errors(self) -> None:
        db = MagicMock()
        file_edge_coll = MagicMock()
        output_edge_coll = MagicMock()
        db.has_collection.side_effect = lambda _name: False
        db.create_collection.side_effect = [
            CollectionCreateError(MagicMock(), MagicMock()),
            CollectionCreateError(MagicMock(), MagicMock()),
            CollectionCreateError(MagicMock(), MagicMock()),
        ]
        file_edge_coll.add_persistent_index.side_effect = [
            IndexCreateError(MagicMock(), MagicMock()),
            IndexCreateError(MagicMock(), MagicMock()),
            IndexCreateError(MagicMock(), MagicMock()),
        ]
        output_edge_coll.add_persistent_index.side_effect = [
            IndexCreateError(MagicMock(), MagicMock()),
            IndexCreateError(MagicMock(), MagicMock()),
            IndexCreateError(MagicMock(), MagicMock()),
        ]
        db.collection.side_effect = lambda name: {
            "file_has_output_stream": file_edge_coll,
            "output_has_stream": output_edge_coll,
        }[name]

        upgrade_v029(db)

        assert db.create_collection.call_count == 3
        assert file_edge_coll.add_persistent_index.call_count == 3
        assert output_edge_coll.add_persistent_index.call_count == 3


@pytest.mark.unit
@pytest.mark.mocked
class TestV030DropSegmentScoresStats:
    """Tests for dropping legacy segment-stats collections."""

    def test_drops_only_legacy_segment_stats_collections(self) -> None:
        db = MagicMock()
        existing = {
            "ml_output_streams",
            "file_has_output_stream",
            "output_has_stream",
            "file_has_segment_stats",
            "segment_scores_stats",
        }
        db.has_collection.side_effect = lambda name: name in existing

        upgrade_v030(db)

        db.delete_collection.assert_has_calls([call("file_has_segment_stats"), call("segment_scores_stats")])
        assert db.delete_collection.call_count == 2

    def test_safe_rerun_skips_missing_legacy_collections(self) -> None:
        db = MagicMock()
        db.has_collection.side_effect = lambda _name: False

        upgrade_v030(db)

        db.delete_collection.assert_not_called()
