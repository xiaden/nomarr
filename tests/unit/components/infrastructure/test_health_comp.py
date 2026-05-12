"""Tests for ``nomarr.components.infrastructure.health_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.infrastructure.health_comp import HealthComp


@pytest.mark.unit
class TestHealthComp:
    def test_get_all_workers_uses_app_worker_health(self) -> None:
        db = MagicMock()
        db.app.list_worker_health.return_value = [{"component_id": "worker:1"}]
        comp = HealthComp(db)

        result = comp.get_all_workers()

        assert result == [{"component_id": "worker:1"}]
        db.app.list_worker_health.assert_called_once_with()

    def test_get_component_uses_app_get_health(self) -> None:
        db = MagicMock()
        db.app.get_health.return_value = {"component_id": "worker:1", "status": "healthy"}
        comp = HealthComp(db)

        result = comp.get_component("worker:1")

        assert result == {"component_id": "worker:1", "status": "healthy"}
        db.app.get_health.assert_called_once_with("worker:1")
