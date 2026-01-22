"""Tests for ml_capacity_probe_comp.py."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from nomarr.components.ml.ml_capacity_probe_comp import (
    CapacityEstimate,
    compute_model_set_hash,
    get_or_run_capacity_probe,
    invalidate_capacity_estimate,
)


class TestComputeModelSetHash:
    """Tests for compute_model_set_hash()."""

    def test_hash_is_deterministic(self):
        """Same models directory produces same hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake model files
            os.makedirs(os.path.join(tmpdir, "effnet", "heads"))
            model_file = os.path.join(tmpdir, "effnet", "heads", "genre.pb")
            with open(model_file, "wb") as f:
                f.write(b"fake model data")

            hash1 = compute_model_set_hash(tmpdir)
            hash2 = compute_model_set_hash(tmpdir)

            assert hash1 == hash2

    def test_hash_changes_with_different_files(self):
        """Hash changes when model files change."""
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            # First dir with one model
            os.makedirs(os.path.join(tmpdir1, "effnet"))
            with open(os.path.join(tmpdir1, "effnet", "model.pb"), "wb") as f:
                f.write(b"model1")

            # Second dir with different model
            os.makedirs(os.path.join(tmpdir2, "effnet"))
            with open(os.path.join(tmpdir2, "effnet", "model.pb"), "wb") as f:
                f.write(b"model2_different")

            hash1 = compute_model_set_hash(tmpdir1)
            hash2 = compute_model_set_hash(tmpdir2)

            assert hash1 != hash2

    def test_hash_handles_empty_dir(self):
        """Hash handles empty models directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hash_result = compute_model_set_hash(tmpdir)
            # Should return a hash (all zeros or similar for empty)
            assert len(hash_result) == 16  # 16-char hex digest


class TestCapacityEstimate:
    """Tests for CapacityEstimate dataclass."""

    def test_dataclass_fields(self):
        """CapacityEstimate has expected fields."""
        estimate = CapacityEstimate(
            model_set_hash="abc123",
            measured_backbone_vram_mb=8000,
            estimated_worker_ram_mb=2000,
            gpu_capable=True,
        )

        assert estimate.model_set_hash == "abc123"
        assert estimate.measured_backbone_vram_mb == 8000
        assert estimate.estimated_worker_ram_mb == 2000
        assert estimate.gpu_capable is True
        assert estimate.is_conservative is False  # default

    def test_is_conservative_flag(self):
        """CapacityEstimate tracks conservative fallback status."""
        estimate = CapacityEstimate(
            model_set_hash="abc123",
            measured_backbone_vram_mb=8192,  # Conservative default
            estimated_worker_ram_mb=4096,  # Conservative default
            gpu_capable=True,
            is_conservative=True,
        )

        assert estimate.is_conservative is True


class TestGetOrRunCapacityProbe:
    """Tests for get_or_run_capacity_probe()."""

    def test_returns_cached_estimate_when_exists(self):
        """Returns cached estimate if it exists for the model hash."""
        mock_db = MagicMock()
        cached = {
            "measured_backbone_vram_mb": 8000,
            "estimated_worker_ram_mb": 2000,
        }
        mock_db.ml_capacity.get_capacity_estimate.return_value = cached

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.ml_capacity_probe_comp.compute_model_set_hash",
                return_value="abc123",
            ),
            patch(
                "nomarr.components.ml.ml_capacity_probe_comp.check_nvidia_gpu_capability",
                return_value=True,
            ),
        ):
            result = get_or_run_capacity_probe(
                db=mock_db,
                models_dir=tmpdir,
                worker_id="worker-1",
            )

        assert result.model_set_hash == "abc123"
        assert result.measured_backbone_vram_mb == 8000
        assert result.is_conservative is False


class TestInvalidateCapacityEstimate:
    """Tests for invalidate_capacity_estimate()."""

    def test_deletes_cached_estimate(self):
        """Invalidate calls delete on DB."""
        mock_db = MagicMock()

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.ml_capacity_probe_comp.compute_model_set_hash",
                return_value="abc123",
            ),
        ):
            invalidate_capacity_estimate(mock_db, tmpdir)

        mock_db.ml_capacity.delete_capacity_estimate.assert_called_once_with("abc123")
