"""Tests for ``nomarr.components.platform.arango_bootstrap_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.platform.arango_bootstrap_comp import provision_vectors_track_for_library


class TestProvisionVectorsTrackForLibrary:
    """Tests for ``provision_vectors_track_for_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_creates_collections_and_indexes_for_each_backbone(self) -> None:
        """Missing hot collections should be created and indexed for every backbone."""
        db = MagicMock()
        db.has_collection.return_value = False

        with (
            patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_backbones",
                return_value=["effnet", "yamnet"],
            ),
            patch("nomarr.components.platform.arango_bootstrap_comp._ensure_index") as mock_ensure_index,
        ):
            provision_vectors_track_for_library(db, "/models", "music")

        assert db.create_collection.call_args_list == [
            call("vectors_track_hot__effnet__music"),
            call("vectors_track_hot__yamnet__music"),
        ]
        mock_ensure_index.assert_has_calls(
            [
                call(db, "vectors_track_hot__effnet__music", "persistent", ["_key"], unique=True),
                call(db, "vectors_track_hot__effnet__music", "persistent", ["file_id"]),
                call(db, "vectors_track_hot__yamnet__music", "persistent", ["_key"], unique=True),
                call(db, "vectors_track_hot__yamnet__music", "persistent", ["file_id"]),
            ]
        )
        assert mock_ensure_index.call_count == 4

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_creation_for_existing_collections(self) -> None:
        """Existing collections should skip creation but still receive index provisioning."""
        db = MagicMock()
        db.has_collection.return_value = True

        with (
            patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_backbones",
                return_value=["effnet"],
            ),
            patch("nomarr.components.platform.arango_bootstrap_comp._ensure_index") as mock_ensure_index,
        ):
            provision_vectors_track_for_library(db, "/models", "music")

        db.create_collection.assert_not_called()
        mock_ensure_index.assert_has_calls(
            [
                call(db, "vectors_track_hot__effnet__music", "persistent", ["_key"], unique=True),
                call(db, "vectors_track_hot__effnet__music", "persistent", ["file_id"]),
            ]
        )
        assert mock_ensure_index.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_no_backbones_does_nothing(self) -> None:
        """No discovered backbones should skip collection creation and indexing."""
        db = MagicMock()

        with (
            patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_backbones",
                return_value=[],
            ),
            patch("nomarr.components.platform.arango_bootstrap_comp._ensure_index") as mock_ensure_index,
        ):
            provision_vectors_track_for_library(db, "/models", "music")

        db.create_collection.assert_not_called()
        mock_ensure_index.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_discovery_exception_skips_provisioning(self) -> None:
        """Backbone discovery failures should skip provisioning entirely."""
        db = MagicMock()

        with (
            patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_backbones",
                side_effect=Exception("no models"),
            ),
            patch("nomarr.components.platform.arango_bootstrap_comp._ensure_index") as mock_ensure_index,
        ):
            provision_vectors_track_for_library(db, "/models", "music")

        db.create_collection.assert_not_called()
        mock_ensure_index.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_collection_name_format(self) -> None:
        """Collection names should include the backbone and library key."""
        db = MagicMock()
        db.has_collection.return_value = False

        with patch(
            "nomarr.components.ml.onnx.ml_discovery_comp.discover_backbones",
            return_value=["effnet"],
        ):
            provision_vectors_track_for_library(db, "/models", "rock")

        db.create_collection.assert_called_once_with("vectors_track_hot__effnet__rock")
