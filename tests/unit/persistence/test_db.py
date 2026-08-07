"""Unit tests for ``nomarr.persistence`` public API surface."""

from __future__ import annotations

import pytest

import nomarr.persistence.api as persistence_api


@pytest.mark.unit
def test_persistence_api_exports_final_public_facades() -> None:
    """persistence.api __all__ exports exactly the three Tier 3 public facade classes."""
    assert persistence_api.__all__ == [
        "AppDb",
        "LibraryDb",
        "MlDb",
    ]
