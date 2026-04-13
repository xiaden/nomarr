"""Tests for ``nomarr.services.domain.vector_maintenance_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService


def _make_service(db: MagicMock | None = None, models_dir: str = "/models") -> VectorMaintenanceService:
    """Build a minimal VectorMaintenanceService for tests."""
    return VectorMaintenanceService(
        db=db or MagicMock(),
        models_dir=models_dir,
        config_svc=MagicMock(),
    )


class TestGetLibraryVectorStats:
    """Tests for ``VectorMaintenanceService.get_library_vector_stats``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_library_not_found(self) -> None:
        """Unknown libraries should raise ValueError before scanning backbones."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch("nomarr.services.domain.vector_maintenance_svc.get_library_record", return_value=None),
            pytest.raises(ValueError, match="Library not found: libraries/1"),
        ):
            service.get_library_vector_stats("libraries/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_backbones_discovered(self) -> None:
        """No discovered backbones should produce an empty stats list."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch("nomarr.services.domain.vector_maintenance_svc.get_library_record", return_value={"_key": "1"}),
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=[],
            ) as mock_discover_backbones,
        ):
            result = service.get_library_vector_stats("libraries/1")

        assert result == []
        mock_discover_backbones.assert_called_once_with("/models")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_stats_row_for_each_backbone(self) -> None:
        """Successful backbone stats should be normalized into response rows."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch("nomarr.services.domain.vector_maintenance_svc.get_library_record", return_value={"_key": "1"}),
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=["effnet"],
            ),
            patch.object(
                service,
                "get_hot_cold_stats",
                return_value={"hot_count": 5, "cold_count": 100, "index_exists": True},
            ) as mock_get_hot_cold_stats,
        ):
            result = service.get_library_vector_stats("libraries/1")

        assert result == [
            {
                "backbone_id": "effnet",
                "hot_count": 5,
                "cold_count": 100,
                "index_exists": True,
            }
        ]
        mock_get_hot_cold_stats.assert_called_once_with("effnet", "1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_backbones_that_fail_stats_lookup(self) -> None:
        """Backbones with stats errors should be skipped instead of failing the whole request."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch("nomarr.services.domain.vector_maintenance_svc.get_library_record", return_value={"_key": "abc"}),
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=["broken", "effnet"],
            ),
            patch.object(
                service,
                "get_hot_cold_stats",
                side_effect=[RuntimeError("boom"), {"hot_count": 1, "cold_count": 2, "index_exists": False}],
            ) as mock_get_hot_cold_stats,
        ):
            result = service.get_library_vector_stats("libraries/1")

        assert result == [
            {
                "backbone_id": "effnet",
                "hot_count": 1,
                "cold_count": 2,
                "index_exists": False,
            }
        ]
        assert mock_get_hot_cold_stats.call_count == 2
