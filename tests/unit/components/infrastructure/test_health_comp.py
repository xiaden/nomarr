"""Tests for ``nomarr.components.infrastructure.health_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.infrastructure.health_comp import HealthComp


@pytest.mark.unit
class TestHealthComp:
    def test_get_all_workers_uses_health_facade(self) -> None:
        db = MagicMock()
        db.health.get_all_workers.return_value = [{"component_id": "worker:1"}]
        comp = HealthComp(db)

        result = comp.get_all_workers()

        assert result == [{"component_id": "worker:1"}]
        db.health.get_all_workers.assert_called_once_with()

    def test_get_component_uses_health_facade(self) -> None:
        db = MagicMock()
        db.health.get_component.return_value = {"component_id": "worker:1", "status": "healthy"}
        comp = HealthComp(db)

        result = comp.get_component("worker:1")

        assert result == {"component_id": "worker:1", "status": "healthy"}
        db.health.get_component.assert_called_once_with("worker:1")
