"""Tests for ``nomarr.components.ml.onnx.ml_model_registry_comp``."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.onnx.ml_model_registry_comp import (
    build_model_output_id_map,
    delete_model_outputs_for_model,
    delete_registered_model,
    ensure_model_outputs,
    get_registered_model_by_path,
    list_fully_labeled_model_outputs,
    list_model_outputs_for_model,
    list_registered_models,
    mark_model_fully_configured,
    mark_model_known,
    prune_registered_model,
    update_model_output_label,
    upsert_registered_model,
)


@pytest.mark.unit
class TestListRegisteredModels:
    """Tests for ``list_registered_models``."""

    def test_returns_empty_when_list_is_empty(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = []

        result = list_registered_models(mock_db)

        assert result == []
        mock_db.ml.count_models.assert_not_called()
        mock_db.ml.list_models.assert_called_once_with()

    def test_returns_documents_when_models_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = [
            {"_id": "ml_models/k1", "path": "/a.onnx"},
            {"_id": "ml_models/k2", "path": "/b.onnx"},
        ]

        result = list_registered_models(mock_db)

        assert len(result) == 2
        mock_db.ml.count_models.assert_not_called()
        mock_db.ml.list_models.assert_called_once_with()


@pytest.mark.unit
class TestGetRegisteredModelByPath:
    """Tests for ``get_registered_model_by_path``."""

    def test_returns_none_when_path_not_registered(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model_by_path.return_value = None

        result = get_registered_model_by_path(mock_db, "/missing.onnx")

        assert result is None
        mock_db.ml.get_model_by_path.assert_called_once_with("/missing.onnx")

    def test_returns_doc_when_path_exists(self) -> None:
        mock_db = MagicMock()
        expected = {"_id": "ml_models/abc", "path": "/effnet.onnx", "backbone": "effnet"}
        mock_db.ml.get_model_by_path.return_value = expected

        result = get_registered_model_by_path(mock_db, "/effnet.onnx")

        assert result == expected


@pytest.mark.unit
class TestUpsertRegisteredModel:
    """Tests for ``upsert_registered_model``."""

    def test_inserts_new_model_with_defaults(self) -> None:
        mock_db = MagicMock()
        model_doc = {
            "_id": "ml_models/abc",
            "path": "/effnet.onnx",
            "backbone": "effnet",
            "fully_configured": False,
            "is_known": False,
        }
        # First call (existing check) returns None, second (post-upsert) returns doc
        mock_db.ml.get_model_by_path.side_effect = [None, model_doc]

        result = upsert_registered_model(
            mock_db,
            path="/effnet.onnx",
            backbone="effnet",
            head_type="classifier",
            model_stem="effnet_head",
            output_count=3,
        )

        assert result == model_doc
        upserted = mock_db.ml.upsert_model.call_args.args[0]
        assert upserted["fully_configured"] is False
        assert upserted["is_known"] is False
        assert "registered_at" in upserted

    def test_preserves_flags_for_existing_model(self) -> None:
        mock_db = MagicMock()
        existing = {
            "_id": "ml_models/abc",
            "path": "/effnet.onnx",
            "backbone": "effnet",
            "fully_configured": True,
            "is_known": True,
            "registered_at": 9999,
        }
        updated = {**existing, "output_count": 4}
        mock_db.ml.get_model_by_path.side_effect = [existing, updated]

        result = upsert_registered_model(
            mock_db,
            path="/effnet.onnx",
            backbone="effnet",
            head_type="classifier",
            model_stem="effnet_head",
            output_count=4,
        )

        assert result == updated
        upserted = mock_db.ml.upsert_model.call_args.args[0]
        assert upserted["fully_configured"] is True
        assert upserted["is_known"] is True
        assert upserted["registered_at"] == 9999

    def test_raises_when_post_upsert_read_fails(self) -> None:
        mock_db = MagicMock()
        # First call returns None (no existing), second returns None (upsert failure)
        mock_db.ml.get_model_by_path.side_effect = [None, None]

        with pytest.raises(RuntimeError, match="Failed to load persisted ml_models document"):
            upsert_registered_model(
                mock_db,
                path="/fail.onnx",
                backbone="effnet",
                head_type="classifier",
                model_stem="effnet_head",
                output_count=2,
            )


@pytest.mark.unit
class TestMarkModelFullyConfigured:
    """Tests for ``mark_model_fully_configured``."""

    def test_no_op_when_model_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = None

        mark_model_fully_configured(mock_db, "ml_models/missing", True)

        mock_db.ml.upsert_model.assert_not_called()

    def test_updates_fully_configured_flag(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = {
            "_id": "ml_models/abc",
            "_key": "abc",
            "_rev": "xyz",
            "path": "/effnet.onnx",
            "fully_configured": False,
        }

        mark_model_fully_configured(mock_db, "ml_models/abc", True)

        upserted = mock_db.ml.upsert_model.call_args.args[0]
        assert upserted["fully_configured"] is True
        assert "_rev" not in upserted
        assert "_id" not in upserted


@pytest.mark.unit
class TestMarkModelKnown:
    """Tests for ``mark_model_known``."""

    def test_no_op_when_model_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = None

        mark_model_known(mock_db, "ml_models/missing", True)

        mock_db.ml.upsert_model.assert_not_called()

    def test_updates_is_known_flag(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = {
            "_id": "ml_models/abc",
            "_key": "abc",
            "_rev": "xyz",
            "path": "/effnet.onnx",
            "is_known": False,
        }

        mark_model_known(mock_db, "ml_models/abc", True)

        upserted = mock_db.ml.upsert_model.call_args.args[0]
        assert upserted["is_known"] is True
        assert "_rev" not in upserted
        assert "_id" not in upserted


@pytest.mark.unit
class TestDeleteRegisteredModel:
    """Tests for ``delete_registered_model``."""

    def test_delegates_to_db_delete(self) -> None:
        mock_db = MagicMock()

        delete_registered_model(mock_db, "ml_models/abc")

        mock_db.ml.delete_model.assert_called_once_with("ml_models/abc")


@pytest.mark.unit
class TestListModelOutputsForModel:
    """Tests for ``list_model_outputs_for_model``."""

    def test_returns_outputs_sorted_by_index(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = [
            {"_id": "ml_model_outputs/a", "output_index": 0},
            {"_id": "ml_model_outputs/b", "output_index": 1},
            {"_id": "ml_model_outputs/c", "output_index": 2},
        ]

        result = list_model_outputs_for_model(mock_db, "ml_models/abc")

        assert [doc["output_index"] for doc in result] == [0, 1, 2]
        mock_db.ml.list_model_outputs.assert_called_once_with("ml_models/abc")

    def test_returns_empty_when_traversal_empty(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = []

        result = list_model_outputs_for_model(mock_db, "ml_models/abc")

        assert result == []


@pytest.mark.unit
class TestListFullyLabeledModelOutputs:
    """Tests for ``list_fully_labeled_model_outputs``."""

    def test_filters_to_only_fully_labeled(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = [
            {"output_index": 0, "fully_labeled": True, "label": "mood"},
            {"output_index": 1, "fully_labeled": False, "label": None},
            {"output_index": 2, "fully_labeled": True, "label": "genre"},
        ]

        result = list_fully_labeled_model_outputs(mock_db, "ml_models/abc")

        assert len(result) == 2
        assert all(doc["fully_labeled"] for doc in result)

    def test_returns_empty_when_none_labeled(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = [
            {"output_index": 0, "fully_labeled": False, "label": None},
        ]

        result = list_fully_labeled_model_outputs(mock_db, "ml_models/abc")

        assert result == []


@pytest.mark.unit
class TestEnsureModelOutputs:
    """Tests for ``ensure_model_outputs``."""

    def test_inserts_missing_output_and_upserts_edge(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model_output.return_value = None
        mock_db.ml.add_model_output.return_value = "ml_model_outputs/new-output"
        mock_db.ml.list_model_outputs.return_value = [{"_id": "ml_model_outputs/new-output", "output_index": 0}]

        ensure_model_outputs(mock_db, "ml_models/abc", 1)

        mock_db.ml.add_model_output.assert_called_once()
        inserted = mock_db.ml.add_model_output.call_args.args[0]
        assert inserted["output_index"] == 0
        assert inserted["fully_labeled"] is False
        mock_db.ml.upsert_model_output_edge.assert_called_once_with(
            inserted["_key"],
            "ml_models/abc",
            "ml_model_outputs/new-output",
        )

    def test_skips_insert_when_output_exists(self) -> None:
        mock_db = MagicMock()
        output_key = hashlib.sha256(b"ml_models/abc:0").hexdigest()[:16]
        existing_output = {"_id": "ml_model_outputs/existing", "_key": "existing", "output_index": 0}
        mock_db.ml.get_model_output.return_value = existing_output
        mock_db.ml.list_model_outputs.return_value = [existing_output]

        ensure_model_outputs(mock_db, "ml_models/abc", 1)

        mock_db.ml.add_model_output.assert_not_called()
        mock_db.ml.upsert_model_output_edge.assert_called_once_with(
            output_key,
            "ml_models/abc",
            existing_output["_id"],
        )


@pytest.mark.unit
class TestUpdateModelOutputLabel:
    """Tests for ``update_model_output_label``."""

    def test_updates_output_doc(self) -> None:
        mock_db = MagicMock()

        update_model_output_label(mock_db, "ml_model_outputs/abc123", "mood")

        mock_db.ml.update_model_output.assert_called_once_with(
            "ml_model_outputs/abc123",
            {"label": "mood", "fully_labeled": True},
        )


@pytest.mark.unit
class TestBuildModelOutputIdMap:
    """Tests for ``build_model_output_id_map``."""

    def test_returns_empty_when_no_models(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = []

        result = build_model_output_id_map(mock_db)

        assert result == {}

    def test_builds_nested_map_for_labeled_outputs(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = [{"_id": "ml_models/m1", "path": "/effnet.onnx"}]
        mock_db.ml.list_model_outputs.return_value = [
            {"_id": "ml_model_outputs/o1", "_key": "o1", "output_index": 0, "label": "genre", "fully_labeled": True},
            {"_id": "ml_model_outputs/o2", "_key": "o2", "output_index": 1, "label": "mood", "fully_labeled": True},
        ]

        result = build_model_output_id_map(mock_db)

        assert result == {
            "/effnet.onnx": {
                "genre": "ml_model_outputs/o1",
                "mood": "ml_model_outputs/o2",
            }
        }


@pytest.mark.unit
class TestDeleteModelOutputsForModel:
    """Tests for ``delete_model_outputs_for_model``."""

    def test_returns_empty_when_no_outputs(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.delete_model_outputs_for_model.return_value = []

        result = delete_model_outputs_for_model(mock_db, "ml_models/abc")

        assert result == []
        mock_db.ml.delete_model_outputs_for_model.assert_called_once_with("ml_models/abc")

    def test_deletes_edges_and_outputs(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.delete_model_outputs_for_model.return_value = ["ml_model_outputs/o1", "ml_model_outputs/o2"]

        result = delete_model_outputs_for_model(mock_db, "ml_models/abc")

        assert result == ["ml_model_outputs/o1", "ml_model_outputs/o2"]
        mock_db.ml.delete_model_outputs_for_model.assert_called_once_with("ml_models/abc")


@pytest.mark.unit
class TestPruneRegisteredModel:
    """Tests for ``prune_registered_model``."""

    @patch("nomarr.components.ml.onnx.ml_model_registry_comp.delete_tag_model_output_edges_for_outputs")
    def test_prunes_model_with_outputs(self, mock_delete_tag_edges: MagicMock) -> None:
        mock_db = MagicMock()
        mock_delete_tag_edges.return_value = 3
        mock_db.ml.list_model_outputs.return_value = [
            {"_id": "ml_model_outputs/o1", "_key": "o1", "output_index": 0},
        ]
        mock_db.ml.delete_model_outputs_for_model.return_value = ["ml_model_outputs/o1"]

        result = prune_registered_model(mock_db, "ml_models/abc")

        mock_delete_tag_edges.assert_called_once_with(mock_db, ["ml_model_outputs/o1"])
        mock_db.ml.delete_model.assert_called_once_with("ml_models/abc")
        assert result["tag_model_output_edges_deleted"] == 3
        output_ids = result["output_ids"]
        assert isinstance(output_ids, list)
        assert "ml_model_outputs/o1" in output_ids

    @patch("nomarr.components.ml.onnx.ml_model_registry_comp.delete_tag_model_output_edges_for_outputs")
    def test_prunes_model_with_no_outputs(self, mock_delete_tag_edges: MagicMock) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = []
        mock_db.ml.delete_model_outputs_for_model.return_value = []

        result = prune_registered_model(mock_db, "ml_models/abc")

        mock_delete_tag_edges.assert_not_called()
        mock_db.ml.delete_model.assert_called_once_with("ml_models/abc")
        assert result["tag_model_output_edges_deleted"] == 0
        assert result["output_ids"] == []
