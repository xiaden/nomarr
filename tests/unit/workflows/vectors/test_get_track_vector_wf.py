"""Tests for the typed get_track_vector workflow.

The workflow delegates to the cold-tier retrieve component and returns a domain
:class:`SongVector` (carrying the actual stored embedding) or ``None`` when no
promoted vector exists — never a raw persistence dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector
from nomarr.workflows.vectors.get_track_vector_wf import get_track_vector

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _make_db() -> Database:
    return MagicMock()


@pytest.fixture(autouse=True)
def comp_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the workflow's component call to the mock DB surface."""

    def _get_vector(db, file_id, backbone_id):  # type: ignore[no-untyped-def]
        return db._get_cold_track_vector(file_id, backbone_id)

    monkeypatch.setattr(
        "nomarr.workflows.vectors.get_track_vector_wf.get_cold_track_vector",
        _get_vector,
    )


def _song_vector(vector: tuple[float, ...]) -> SongVector:
    song = SongIdentity(
        library=LibraryIdentity(name="Music", root_path="/music"),
        normalized_path="songs/1.mp3",
    )
    return SongVector(
        song=song,
        backbone="effnet",
        vector=vector,
        model_suite_hash="suite",
        num_segments=1,
        segmentation_hash=None,
        genres=None,
    )


@pytest.mark.unit
class TestGetTrackVectorWorkflow:
    """get_track_vector returns the typed SongVector contract."""

    def test_returns_typed_song_vector(self) -> None:
        db = _make_db()
        expected = _song_vector((0.1, 0.2, 0.3))
        db._get_cold_track_vector = MagicMock(return_value=expected)

        result = get_track_vector(db, 1, "effnet")

        assert result is expected
        assert isinstance(result, SongVector)
        assert result.vector == (0.1, 0.2, 0.3)
        db._get_cold_track_vector.assert_called_once_with(1, "effnet")

    def test_returns_none_when_no_vector(self) -> None:
        db = _make_db()
        db._get_cold_track_vector = MagicMock(return_value=None)

        result = get_track_vector(db, 999, "effnet")

        assert result is None
        db._get_cold_track_vector.assert_called_once_with(999, "effnet")
