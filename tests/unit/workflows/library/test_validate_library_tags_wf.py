"""Tests for ``nomarr.workflows.library.validate_library_tags_wf``.

The workflow consumes typed ``IncompleteTagCandidate`` values from
``get_songs_with_incomplete_tags`` and addresses repair through each candidate's
``SongIdentity`` locator. No raw row, integer ``file_id``, or resolver participates.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.file_states import STATE_NOT_WRITTEN, STATE_WRITTEN
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import IncompleteTagCandidate
from nomarr.workflows.library.validate_library_tags_wf import validate_library_tags_workflow

MODULE = "nomarr.workflows.library.validate_library_tags_wf"


def _song(normalized_path: str) -> Song:
    """Build a semantic ``Song`` (natural identity) for validation tests."""
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=100,
        modified_time=1000,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _candidate(normalized_path: str, missing_heads: tuple[str, ...]) -> IncompleteTagCandidate:
    """Build a real typed incomplete-tag candidate (what the component now returns)."""
    return IncompleteTagCandidate(
        identity=SongIdentity(
            library=LibraryIdentity(library_uuid="uuid-lib", name="lib", root_path="/music"),
            normalized_path=normalized_path,
        ),
        song=_song(normalized_path),
        matched_count=1,
        missing_count=len(missing_heads),
        missing_heads=missing_heads,
    )


class TestValidateLibraryTagsWorkflow:
    """Typed consumption of the incomplete-tag candidates."""

    @pytest.mark.unit
    def test_transitions_candidate_identities_without_row_ids(self) -> None:
        """Repair transitions must receive typed ``SongIdentity`` locators, not row ids."""
        db = MagicMock()
        candidates = [
            _candidate("a.mp3", ("model-a:mood",)),
            _candidate("b.mp3", ("model-a:mood", "model-b:energy")),
        ]
        head = SimpleNamespace(backbone="model-a", name="mood", labels=["happy"])

        with (
            patch(f"{MODULE}.discover_heads", return_value=[head]),
            patch(f"{MODULE}.get_songs_with_incomplete_tags", return_value=candidates),
            patch(f"{MODULE}.transition_song_state") as mock_transition,
        ):
            result = validate_library_tags_workflow(db, "models", library=MagicMock())

        assert result["files_checked"] == 2
        assert result["complete_files"] == 0
        assert result["incomplete_files"] == 2
        assert result["files_repaired"] == 2
        assert result["missing_names_summary"] == {"model-a:mood": 2, "model-b:energy": 1}
        assert result["details"] == candidates
        mock_transition.assert_called_once_with(
            db,
            [candidate.identity for candidate in candidates],
            STATE_WRITTEN,
            STATE_NOT_WRITTEN,
        )

    @pytest.mark.unit
    def test_no_repair_when_auto_repair_disabled(self) -> None:
        """``auto_repair=False`` reports typed candidates without transitioning state."""
        db = MagicMock()
        candidates = [_candidate("a.mp3", ("model-a:mood",))]
        head = SimpleNamespace(backbone="model-a", name="mood", labels=["happy"])

        with (
            patch(f"{MODULE}.discover_heads", return_value=[head]),
            patch(f"{MODULE}.get_songs_with_incomplete_tags", return_value=candidates),
            patch(f"{MODULE}.transition_song_state") as mock_transition,
        ):
            result = validate_library_tags_workflow(db, "models", library=MagicMock(), auto_repair=False)

        assert result["incomplete_files"] == 1
        assert result["files_repaired"] == 0
        mock_transition.assert_not_called()

    @pytest.mark.unit
    def test_zero_expected_heads_returns_early_without_details(self) -> None:
        """No discovered heads must short-circuit with zeroed counts and no ``details``."""
        db = MagicMock()

        with (
            patch(f"{MODULE}.discover_heads", return_value=[]),
            patch(f"{MODULE}.get_songs_with_incomplete_tags") as mock_incomplete,
            patch(f"{MODULE}.transition_song_state") as mock_transition,
        ):
            result = validate_library_tags_workflow(db, "models", library=MagicMock())

        assert result == {
            "files_checked": 0,
            "complete_files": 0,
            "incomplete_files": 0,
            "files_repaired": 0,
            "missing_names_summary": {},
            "expected_heads": 0,
        }
        assert "details" not in result
        mock_incomplete.assert_not_called()
        mock_transition.assert_not_called()
