"""Tests for ``nomarr.components.infrastructure.health_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.infrastructure.health_comp import HealthComp
from nomarr.helpers.dto.health_dto import WorkerHealth


@pytest.mark.unit
class TestHealthComp:
    def test_get_all_workers_uses_health_facade(self) -> None:
        db = MagicMock()
        db.app.list_worker_health.return_value = [WorkerHealth("worker:1", "healthy", 100)]
        comp = HealthComp(db)

        result = comp.get_all_workers()

        assert result == [WorkerHealth("worker:1", "healthy", 100)]
        db.app.list_worker_health.assert_called_once_with()

    def test_get_component_uses_health_facade(self) -> None:
        db = MagicMock()
        db.app.get_health.return_value = WorkerHealth("worker:1", "healthy", 100)
        comp = HealthComp(db)

        result = comp.get_component("worker:1")

        assert result == WorkerHealth("worker:1", "healthy", 100)
        db.app.get_health.assert_called_once_with("worker:1")
