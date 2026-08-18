"""Unit tests for ``tag_extraction_worker`` single-intent hydration.

``TagExtractionWorker._process_file`` extracts audio metadata and submits
exactly one :class:`HydrateSongInput` to ``db.library.songs.hydrate_song``.
These tests assert the intent boundary: no old per-purpose choreography
(``save_song_tags`` / ``seed_entities_for_scan_batch`` / duration /
``transition_song_state``) is recreated in the worker.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.services.infrastructure.workers.tag_extraction_worker import _process_file

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


def _song_doc(song_id: int = 1) -> dict:
    return {"id": song_id, "path": "/music/lib/track.flac", "namespace": "nom"}


def _make_db(song_id: int = 1) -> MagicMock:
    db = MagicMock()
    db.library.get_song.return_value = _song_doc(song_id)
    return db


def _valid_path_mock() -> MagicMock:
    path = MagicMock()
    path.is_valid.return_value = True
    return path


class TestProcessFile:
    """Tests for the single-intent ``_process_file`` helper."""

    def test_builds_one_hydrate_input_and_calls_hydrate_song_once(self) -> None:
        db = _make_db()
        metadata = {
            "duration": 245.5,
            "nom_tags": {"mood": "chill", "energy": ["high"]},
        }
        path_mock = _valid_path_mock()

        with (
            patch("nomarr.components.infrastructure.path_comp.build_library_path_from_input", return_value=path_mock),
            patch("nomarr.components.library.metadata_extraction_comp.extract_metadata", return_value=metadata),
            patch("nomarr.components.tagging.tag_parsing_comp.parse_tag_values", return_value={"mood": ["chill"]}),
            patch(
                "nomarr.components.metadata.entity_seeding_comp.extract_entity_tag_mapping",
                return_value={"genre": ["rock"]},
            ),
            patch(
                "nomarr.components.metadata.metadata_cache_comp.compute_metadata_cache_fields",
                return_value={"artist": "The Test"},
            ),
        ):
            _process_file(db, 1)

        # Exactly one atomic hydration intent is issued.
        db.library.songs.hydrate_song.assert_called_once()
        input_arg = db.library.songs.hydrate_song.call_args[0][0]
        assert isinstance(input_arg, HydrateSongInput)
        assert input_arg.song_id == 1
        # parsed_nom_tags are namespace-prefixed.
        assert input_arg.parsed_nom_tags == {"nom:mood": ["chill"]}
        assert input_arg.entity_tags == {"genre": ["rock"]}
        assert input_arg.metadata_cache == {"artist": "The Test"}
        assert input_arg.duration_seconds == 245.5

        # No old per-purpose choreography is recreated.
        db.library.save_song_tags.assert_not_called()
        db.library.seed_entities_for_scan_batch.assert_not_called()
        db.library.update_library_song_duration.assert_not_called()
        db.library.transition_song_state.assert_not_called()

    def test_uses_default_namespace_when_absent(self) -> None:
        db = _make_db()
        db.library.get_song.return_value = {"id": 1, "path": "/music/lib/track.flac"}
        metadata = {"duration": 100.0, "nom_tags": {"mood": "chill"}}
        path_mock = _valid_path_mock()

        with (
            patch("nomarr.components.infrastructure.path_comp.build_library_path_from_input", return_value=path_mock),
            patch("nomarr.components.library.metadata_extraction_comp.extract_metadata", return_value=metadata),
            patch("nomarr.components.tagging.tag_parsing_comp.parse_tag_values", return_value={"mood": ["chill"]}),
            patch("nomarr.components.metadata.entity_seeding_comp.extract_entity_tag_mapping", return_value={}),
            patch("nomarr.components.metadata.metadata_cache_comp.compute_metadata_cache_fields", return_value={}),
        ):
            _process_file(db, 1)

        input_arg = db.library.songs.hydrate_song.call_args[0][0]
        assert input_arg.parsed_nom_tags == {"nom:mood": ["chill"]}

    def test_duration_none_when_metadata_has_no_duration(self) -> None:
        db = _make_db()
        metadata: dict[str, object] = {"nom_tags": {}}
        path_mock = _valid_path_mock()

        with (
            patch("nomarr.components.infrastructure.path_comp.build_library_path_from_input", return_value=path_mock),
            patch("nomarr.components.library.metadata_extraction_comp.extract_metadata", return_value=metadata),
            patch("nomarr.components.tagging.tag_parsing_comp.parse_tag_values", return_value={}),
            patch("nomarr.components.metadata.entity_seeding_comp.extract_entity_tag_mapping", return_value={}),
            patch("nomarr.components.metadata.metadata_cache_comp.compute_metadata_cache_fields", return_value={}),
        ):
            _process_file(db, 1)

        input_arg = db.library.songs.hydrate_song.call_args[0][0]
        assert input_arg.duration_seconds is None

    def test_missing_song_raises_value_error(self) -> None:
        db = MagicMock()
        db.library.get_song.return_value = None

        with pytest.raises(ValueError):
            _process_file(db, 999)

        db.library.songs.hydrate_song.assert_not_called()

    def test_invalid_path_raises_value_error(self) -> None:
        db = _make_db()
        path_mock = MagicMock()
        path_mock.is_valid.return_value = False
        path_mock.reason = "outside library root"

        with (
            patch("nomarr.components.infrastructure.path_comp.build_library_path_from_input", return_value=path_mock),
            patch("nomarr.components.library.metadata_extraction_comp.extract_metadata"),
            pytest.raises(ValueError, match="outside library root"),
        ):
            _process_file(db, 1)

        db.library.songs.hydrate_song.assert_not_called()
