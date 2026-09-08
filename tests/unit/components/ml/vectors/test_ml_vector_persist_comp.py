"""Unit tests for the backbone vector persistence component (typed command builder)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.ml.vectors.ml_vector_persist_comp import (
    build_backbone_vector_payload,
    persist_backbone_vector,
)
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_persist_comp"

pytestmark = [pytest.mark.unit, pytest.mark.mocked]

# Storage-shaped keys that must never appear on the typed command.
_STORAGE_KEYS = ("backbone_id", "model_id", "embedding_vector", "embed_dim")


class TestBuildBackboneVectorPayload:
    """Typed command shape for the aggregate."""

    def test_builds_typed_command(self) -> None:
        command = build_backbone_vector_payload(
            model_suite_hash="abc123",
            vector=[3.0, 4.0],
            num_segments=7,
        )
        assert isinstance(command, BackboneVectorWrite)
        assert command.vector == (3.0, 4.0)
        assert command.model_suite_hash == "abc123"
        assert command.num_segments == 7
        assert command.genres is None
        assert command.segmentation_hash is None

    def test_command_has_no_storage_keys(self) -> None:
        command = build_backbone_vector_payload(model_suite_hash="h", vector=[1.0], num_segments=1)
        for key in _STORAGE_KEYS:
            assert not hasattr(command, key)
        # The command is a frozen dataclass, not a dict.
        assert isinstance(command, BackboneVectorWrite)

    def test_copies_vector_not_mutated(self) -> None:
        vector = [1.0, 2.0]
        command = build_backbone_vector_payload("h", vector, 1)
        vector.append(99.0)
        assert command.vector == (1.0, 2.0)


class TestPersistBackboneVector:
    """Typed command derivation from segment-level backbone embeddings."""

    def test_returns_typed_command_on_success(self) -> None:
        embeddings_2d = np.ones((3, 128))
        pooled_vector = [0.25] * 128
        with (
            patch(f"{PATCH_BASE}.internal_ms", side_effect=[MagicMock(value=1000), MagicMock(value=1050)]),
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=pooled_vector) as mock_pool,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=128) as mock_dim,
        ):
            command = persist_backbone_vector("effnet", embeddings_2d, "abc123", "/music/f1.mp3")

        assert command is not None
        assert isinstance(command, BackboneVectorWrite)
        assert command.vector == tuple(pooled_vector)
        assert command.model_suite_hash == "abc123"
        assert command.num_segments == embeddings_2d.shape[0]
        mock_pool.assert_called_once_with(embeddings_2d)
        mock_dim.assert_called_once_with(embeddings_2d)

    def test_emits_typed_command_with_no_storage_keys_per_backbone(self) -> None:
        """Persisting different backbones yields typed commands carrying no storage ids."""
        with (
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.1] * 64),
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=64),
        ):
            effnet = persist_backbone_vector("effnet", np.ones((3, 64)), "h1", "/music/a.flac")
            openl3 = persist_backbone_vector("openl3", np.ones((4, 64)), "h1", "/music/a.flac")

        assert effnet is not None and isinstance(effnet, BackboneVectorWrite)
        assert openl3 is not None and isinstance(openl3, BackboneVectorWrite)
        assert effnet.vector == (0.1,) * 64
        assert openl3.vector == (0.1,) * 64
        for key in _STORAGE_KEYS:
            assert not hasattr(effnet, key)
            assert not hasattr(openl3, key)

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
        """The component only derives commands — persistence flows through the aggregate."""
        db = MagicMock()
        with (
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.5, 0.5]),
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=2),
        ):
            command = persist_backbone_vector("effnet", np.ones((1, 2)), "h", "/music/a.flac")

        assert command is not None
        assert isinstance(command, BackboneVectorWrite)
        db.ml.assert_not_called()
        db.ml.replace_song_inference_results.assert_not_called()
