"""Tests for ``nomarr.services.domain.vector_maintenance_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService


def _make_library(name: str = "Test Library") -> Library:
    """Build a domain ``Library`` (natural identity) for stats tests."""
    return Library(name=name, root_path="/music")


def _make_service(db: MagicMock | None = None, models_dir: str = "/models") -> VectorMaintenanceService:
    """Build a minimal VectorMaintenanceService for tests."""
    return VectorMaintenanceService(
        db=db or MagicMock(),
        models_dir=models_dir,
        config_svc=MagicMock(),
    )


class TestGetBackboneVectorStats:
    """Tests for ``VectorMaintenanceService.get_backbone_vector_stats``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_backbones_discovered(self) -> None:
        """No discovered backbones should produce an empty stats list."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=[],
            ) as mock_discover_backbones,
        ):
            result = service.get_backbone_vector_stats()

        assert result == []
        mock_discover_backbones.assert_called_once_with("/models")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_stats_row_for_each_backbone(self) -> None:
        """Successful backbone stats should be normalized into response rows."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=["effnet"],
            ),
            patch.object(
                service,
                "get_hot_cold_stats",
                new_callable=MagicMock,
                return_value={"hot_count": 5, "cold_count": 100, "index_exists": True},
            ) as mock_get_hot_cold_stats,
        ):
            result = service.get_backbone_vector_stats()

        assert result == [
            {
                "backbone_id": "effnet",
                "hot_count": 5,
                "cold_count": 100,
                "index_exists": True,
            }
        ]
        mock_get_hot_cold_stats.assert_called_once_with("effnet", library=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_backbones_that_fail_stats_lookup(self) -> None:
        """Backbones with stats errors should be skipped instead of failing the whole request."""
        mock_db = MagicMock()
        service = _make_service(mock_db)

        with (
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=["broken", "effnet"],
            ),
            patch.object(
                service,
                "get_hot_cold_stats",
                new_callable=MagicMock,
                side_effect=[RuntimeError("boom"), {"hot_count": 1, "cold_count": 2, "index_exists": False}],
            ) as mock_get_hot_cold_stats,
        ):
            result = service.get_backbone_vector_stats()

        assert result == [
            {
                "backbone_id": "effnet",
                "hot_count": 1,
                "cold_count": 2,
                "index_exists": False,
            }
        ]
        assert mock_get_hot_cold_stats.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scopes_stats_lookup_to_library(self) -> None:
        """A library request should pass the domain ``Library`` to each backbone lookup."""
        service = _make_service(MagicMock())
        library = _make_library()

        with (
            patch(
                "nomarr.services.domain.vector_maintenance_svc.discover_backbones",
                return_value=["effnet"],
            ),
            patch.object(
                service,
                "get_hot_cold_stats",
                new_callable=MagicMock,
                return_value={"hot_count": 2, "cold_count": 3, "index_exists": True},
            ) as mock_get_hot_cold_stats,
        ):
            result = service.get_backbone_vector_stats(library=library)

        assert result[0]["hot_count"] == 2
        mock_get_hot_cold_stats.assert_called_once_with("effnet", library=library)


@pytest.mark.unit
@pytest.mark.mocked
def test_get_hot_cold_stats_includes_index_status() -> None:
    """Stats returned by the service include the shared vector index status.

    Per-library scoping falls back to global counts (no ``Library``->int
    resolver above the ML facade); the underlying lookup stays global.
    """
    db = MagicMock()
    db.ml.get_embedding_stats.return_value = {"hot_count": 2, "cold_count": 3}
    db.ml.has_embedding_index.return_value = True
    service = _make_service(db)
    library = _make_library()

    result = service.get_hot_cold_stats("effnet", library=library)

    assert result == {"hot_count": 2, "cold_count": 3, "index_exists": True}
    db.ml.get_embedding_stats.assert_called_once_with("effnet", library_id=None)
    db.ml.has_embedding_index.assert_called_once_with("effnet")
