"""Tests for ``nomarr.components.platform.arango_bootstrap_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestCreateCollectionsEdgeGuards:
    """Regression guards for removed edge collections."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_tag_model_output_not_in_edge_collections(self) -> None:
        """tag_model_output must not be provisioned as an edge collection (removed in V032)."""
        from nomarr.components.platform.arango_bootstrap_comp import _create_collections

        db = MagicMock()
        db.has_collection.return_value = False  # always create

        _create_collections(db)

        edge_create_calls = [c for c in db.create_collection.call_args_list if c.kwargs.get("edge") is True]
        created_edge_names = [c.args[0] for c in edge_create_calls]
        assert "tag_model_output" not in created_edge_names
