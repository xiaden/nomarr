"""Tests for common metadata extraction and tag persistence preparation."""

from __future__ import annotations

import pytest

from nomarr.components.library.metadata_extraction_comp import _apply_common_tag_fields


@pytest.mark.unit
def test_apply_common_fields_moves_isrc_into_namespace_tags() -> None:
    metadata = {"all_tags": {"title": '"Song"', "isrc": '["USRC17607839"]'}}

    _apply_common_tag_fields(metadata, "nom")

    assert metadata["nom_tags"] == {"isrc": '["USRC17607839"]'}
    assert "isrc" not in metadata["all_tags"]
