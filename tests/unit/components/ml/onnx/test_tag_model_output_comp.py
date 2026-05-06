"""Tests for ``nomarr.components.ml.onnx.tag_model_output_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.onnx.tag_model_output_comp import (
    _edge_key,
    delete_tag_model_output_edges_for_outputs,
    delete_tag_model_output_edges_for_tag,
    tag_has_model_output_edges,
    write_tag_model_output_edge,
    write_tag_model_output_edges_batch,
)
from nomarr.persistence.base import Field


@pytest.mark.unit
class TestEdgeKey:
    """Tests for ``_edge_key()``."""

    def test_returns_16_character_hex_string(self) -> None:
        result = _edge_key("tags/1", "outputs/1")

        assert len(result) == 16
        assert all(char in "0123456789abcdef" for char in result)

    def test_returns_same_key_for_same_inputs(self) -> None:
        first = _edge_key("tags/1", "outputs/1")
        second = _edge_key("tags/1", "outputs/1")

        assert first == second

    def test_returns_different_key_for_different_inputs(self) -> None:
        first = _edge_key("tags/1", "outputs/1")
        second = _edge_key("tags/1", "outputs/2")

        assert first != second


@pytest.mark.unit
class TestWriteTagModelOutputEdgesBatch:
    """Tests for ``write_tag_model_output_edges_batch()``."""

    @patch("nomarr.components.ml.onnx.tag_model_output_comp.now_ms")
    def test_returns_immediately_for_empty_edges(self, mock_now_ms: MagicMock) -> None:
        mock_db = MagicMock()

        write_tag_model_output_edges_batch(mock_db, [])

        mock_now_ms.assert_not_called()
        mock_db.tag_model_output.get.in_.assert_not_called()
        mock_db.tag_model_output.update_many.assert_not_called()
        mock_db.tag_model_output.insert.assert_not_called()

    @patch("nomarr.components.ml.onnx.tag_model_output_comp.now_ms")
    def test_inserts_new_edge_when_no_existing_edge_found(self, mock_now_ms: MagicMock) -> None:
        mock_now_ms.return_value.value = 1234
        mock_db = MagicMock()
        mock_db.tag_model_output.get.in_.return_value = []

        write_tag_model_output_edges_batch(mock_db, [("tags/1", "outputs/1", 0.75)])

        mock_db.tag_model_output.get.in_.assert_called_once_with(Field("_from", ["tags/1"]), limit=None)
        mock_db.tag_model_output.update_many.assert_not_called()
        mock_db.tag_model_output.insert.assert_called_once_with(
            [
                {
                    "_key": _edge_key("tags/1", "outputs/1"),
                    "_from": "tags/1",
                    "_to": "outputs/1",
                    "score": 0.75,
                    "created_at": 1234,
                    "updated_at": 1234,
                }
            ]
        )

    @patch("nomarr.components.ml.onnx.tag_model_output_comp.now_ms")
    def test_updates_existing_edge_without_inserting(self, mock_now_ms: MagicMock) -> None:
        mock_now_ms.return_value.value = 5678
        mock_db = MagicMock()
        mock_db.tag_model_output.get.in_.return_value = [{"_from": "tags/1", "_to": "outputs/1", "score": 0.25}]

        write_tag_model_output_edges_batch(mock_db, [("tags/1", "outputs/1", 0.9)])

        mock_db.tag_model_output.get.in_.assert_called_once_with(Field("_from", ["tags/1"]), limit=None)
        mock_db.tag_model_output.update_many.assert_called_once_with(
            [{"_key": _edge_key("tags/1", "outputs/1"), "score": 0.9, "updated_at": 5678}]
        )
        mock_db.tag_model_output.insert.assert_not_called()

    @patch("nomarr.components.ml.onnx.tag_model_output_comp.now_ms")
    def test_bulk_reads_existing_edges_once_for_all_tags(self, mock_now_ms: MagicMock) -> None:
        mock_now_ms.return_value.value = 91011
        mock_db = MagicMock()
        mock_db.tag_model_output.get.in_.return_value = [{"_from": "tags/1", "_to": "outputs/existing", "score": 0.1}]

        write_tag_model_output_edges_batch(
            mock_db,
            [("tags/1", "outputs/existing", 0.4), ("tags/2", "outputs/new", 0.8)],
        )

        mock_db.tag_model_output.get.in_.assert_called_once_with(
            Field("_from", ["tags/1", "tags/2"]),
            limit=None,
        )
        mock_db.tag_model_output.update_many.assert_called_once_with(
            [{"_key": _edge_key("tags/1", "outputs/existing"), "score": 0.4, "updated_at": 91011}]
        )
        mock_db.tag_model_output.insert.assert_called_once_with(
            [
                {
                    "_key": _edge_key("tags/2", "outputs/new"),
                    "_from": "tags/2",
                    "_to": "outputs/new",
                    "score": 0.8,
                    "created_at": 91011,
                    "updated_at": 91011,
                }
            ]
        )


@pytest.mark.unit
class TestWriteTagModelOutputEdge:
    """Tests for ``write_tag_model_output_edge()``."""

    @patch("nomarr.components.ml.onnx.tag_model_output_comp.write_tag_model_output_edges_batch")
    def test_delegates_to_batch_with_single_edge(self, mock_write_batch: MagicMock) -> None:
        mock_db = MagicMock()

        write_tag_model_output_edge(mock_db, "tags/1", "outputs/1", 0.55)

        mock_write_batch.assert_called_once_with(mock_db, [("tags/1", "outputs/1", 0.55)])


@pytest.mark.unit
class TestDeleteTagModelOutputEdgesForTag:
    """Tests for ``delete_tag_model_output_edges_for_tag()``."""

    def test_deletes_edges_for_tag_and_returns_deleted_count(self) -> None:
        mock_db = MagicMock()
        mock_db.tag_model_output.delete.return_value = 3

        result = delete_tag_model_output_edges_for_tag(mock_db, "tags/1")

        assert result == 3
        mock_db.tag_model_output.delete.assert_called_once_with(Field("_from", "tags/1"))


@pytest.mark.unit
class TestTagHasModelOutputEdges:
    """Tests for ``tag_has_model_output_edges()``."""

    def test_returns_true_when_edges_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.tag_model_output.get.return_value = [{"_from": "tags/1", "_to": "outputs/1"}]

        result = tag_has_model_output_edges(mock_db, "tags/1")

        assert result is True
        mock_db.tag_model_output.get.assert_called_once_with(Field("_from", "tags/1"), limit=1)

    def test_returns_false_when_no_edges_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.tag_model_output.get.return_value = []

        result = tag_has_model_output_edges(mock_db, "tags/1")

        assert result is False
        mock_db.tag_model_output.get.assert_called_once_with(Field("_from", "tags/1"), limit=1)


@pytest.mark.unit
class TestDeleteTagModelOutputEdgesForOutputs:
    """Tests for ``delete_tag_model_output_edges_for_outputs()``."""

    def test_returns_zero_when_output_ids_empty(self) -> None:
        mock_db = MagicMock()

        result = delete_tag_model_output_edges_for_outputs(mock_db, [])

        assert result == 0
        mock_db.tag_model_output._to.delete.in_.assert_not_called()

    def test_bulk_deletes_edges_for_all_output_ids_in_one_call(self) -> None:
        mock_db = MagicMock()
        mock_db.tag_model_output._to.delete.in_.return_value = 5

        result = delete_tag_model_output_edges_for_outputs(mock_db, ["outputs/1", "outputs/2", "outputs/3"])

        assert result == 5
        mock_db.tag_model_output._to.delete.in_.assert_called_once_with(["outputs/1", "outputs/2", "outputs/3"])
