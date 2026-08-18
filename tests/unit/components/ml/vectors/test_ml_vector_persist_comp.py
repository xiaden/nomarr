"""Unit tests for the backbone vector persistence component (canonical payload builder)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.ml.vectors.ml_vector_persist_comp import (
    build_backbone_vector_payload,
    persist_backbone_vector,
)

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_persist_comp"

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


class TestBuildBackboneVectorPayload:
    """Canonical payload shape for the aggregate."""

    def test_builds_canonical_payload(self) -> None:
        payload = build_backbone_vector_payload(
            backbone="effnet",
            model_suite_hash="abc123",
            embed_dim=2,
            vector=[3.0, 4.0],
            num_segments=7,
        )
        assert payload == {
            "backbone_id": "effnet",
            "model_id": "abc123",
            "embedding_vector": [3.0, 4.0],
            "embed_dim": 2,
            "num_segments": 7,
        }

    def test_copies_vector_not_mutated(self) -> None:
        vector = [1.0, 2.0]
        payload = build_backbone_vector_payload("b", "h", 2, vector, 1)
        vector.append(99.0)
        assert payload["embedding_vector"] == [1.0, 2.0]


class TestPersistBackboneVector:
    """Payload derivation from segment-level backbone embeddings."""

    def test_returns_canonical_payload_on_success(self) -> None:
        embeddings_2d = np.ones((3, 128))
        pooled_vector = [0.25] * 128
        with (
            patch(f"{PATCH_BASE}.internal_ms", side_effect=[MagicMock(value=1000), MagicMock(value=1050)]),
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=pooled_vector) as mock_pool,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=128) as mock_dim,
        ):
            payload = persist_backbone_vector("effnet", embeddings_2d, "abc123", "/music/f1.mp3")

        assert payload is not None
        assert payload["backbone_id"] == "effnet"
        assert payload["model_id"] == "abc123"
        assert payload["embedding_vector"] == pooled_vector
        assert payload["embed_dim"] == 128
        assert payload["num_segments"] == embeddings_2d.shape[0]
        mock_pool.assert_called_once_with(embeddings_2d)
        mock_dim.assert_called_once_with(embeddings_2d)

    def test_payload_is_scoped_to_supplied_backbone(self) -> None:
        """Persisting different backbones yields payloads keyed by each backbone_id."""
        with (
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.1] * 64),
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=64),
        ):
            effnet = persist_backbone_vector("effnet", np.ones((3, 64)), "h1", "/music/a.flac")
            openl3 = persist_backbone_vector("openl3", np.ones((4, 64)), "h1", "/music/a.flac")

        assert effnet["backbone_id"] == "effnet"
        assert openl3["backbone_id"] == "openl3"

    def test_returns_none_on_derivation_exception(self) -> None:
        logger = MagicMock()
        with (
            patch(f"{PATCH_BASE}.logger", logger),
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", side_effect=ValueError("bad dims")),
        ):
            result = persist_backbone_vector("effnet", np.ones((2, 3)), "abc123", "/music/f1.mp3")

        assert result is None
        logger.warning.assert_called_once_with(
            "[vectors] Failed to derive %s vector for %s", "effnet", "/music/f1.mp3", exc_info=True
        )

    def test_no_database_write_happens_here(self) -> None:
        """The component only derives payloads — persistence flows through the aggregate."""
        db = MagicMock()
        with (
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.5, 0.5]),
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=2),
        ):
            payload = persist_backbone_vector("effnet", np.ones((1, 2)), "h", "/music/a.flac")

        assert payload is not None
        db.ml.assert_not_called()
        db.ml.replace_song_inference_results.assert_not_called()
