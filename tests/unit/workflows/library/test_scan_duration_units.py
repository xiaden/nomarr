"""Regression tests for the duration-unit contract of the library scan workflows.

A one-file bug fix changed ``scan_library_full_wf`` to use ``internal_s``
(monotonic seconds) instead of ``internal_ms`` (monotonic milliseconds) for
``start_time`` and ``scan_duration``. Previously ``scan_duration_s`` was computed
in milliseconds (~1000x too large). The quick workflow already used ``internal_s``
and was not modified.

These tests guard the seconds contract for both workflows: with
``internal_s`` patched to return 1_000_000 then 1_000_002, the reported
``scan_duration_s`` must be ``2`` (seconds), not ``2000`` (milliseconds).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.workflows.library.scan_library_full_wf import scan_library_full_workflow
from nomarr.workflows.library.scan_library_quick_wf import scan_library_quick_workflow


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name="Main Library", root_path="/music")


class TestScanDurationUnits:
    """Scan duration must be reported in seconds, not milliseconds."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_full_scan_duration_s_reported_in_seconds(self, caplog: pytest.LogCaptureFixture) -> None:
        """A 2-second full scan must report ``scan_duration_s == 2`` and log '2.0s'.

        ``internal_s`` is patched to return 1_000_000 then 1_000_002, so the
        elapsed duration is 2. If the milliseconds bug regresses (``internal_ms``
        used instead), the reported value would be ~2000, failing this test.
        """
        mock_db = MagicMock()
        library = _make_library()

        with (
            patch(
                "nomarr.workflows.library.scan_library_full_wf.internal_s",
                side_effect=[MagicMock(value=1_000_000), MagicMock(value=1_000_002)],
            ),
            patch(
                "nomarr.workflows.library.scan_library_full_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch("nomarr.workflows.library.scan_library_full_wf.validate_library_root"),
            patch(
                "nomarr.workflows.library.scan_library_full_wf.get_folder_rel_paths",
                return_value=set(),
            ),
            patch(
                "nomarr.workflows.library.scan_library_full_wf.get_cached_folders",
                return_value={},
            ),
            patch(
                "nomarr.workflows.library.scan_library_full_wf.discover_library_folders",
                return_value=[],
            ),
            patch("nomarr.workflows.library.scan_library_full_wf.cleanup_stale_folders"),
            patch("nomarr.workflows.library.scan_library_full_wf.cleanup_orphaned_entities_workflow"),
            patch("nomarr.workflows.library.scan_library_full_wf.update_scan_progress"),
            patch("nomarr.workflows.library.scan_library_full_wf.mark_scan_completed"),
            caplog.at_level(logging.INFO, logger="nomarr.workflows.library.scan_library_full_wf"),
        ):
            result = scan_library_full_workflow(mock_db, library, tagger_version="v1")

        assert result["scan_duration_s"] == 2
        assert "Full scan complete in 2.0s" in caplog.text

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_quick_scan_duration_s_reported_in_seconds(self) -> None:
        """The quick workflow must report ``scan_duration_s`` in seconds too.

        Symmetry guard: the quick workflow already used ``internal_s``, but this
        test protects against a future regression reintroducing the milliseconds
        bug here as well.
        """
        mock_db = MagicMock()
        library = _make_library()

        with (
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.internal_s",
                side_effect=[MagicMock(value=1_000_000), MagicMock(value=1_000_002)],
            ),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.resolve_library_for_scan",
                return_value=library,
            ),
            patch("nomarr.workflows.library.scan_library_quick_wf.validate_library_root"),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.get_folder_rel_paths",
                return_value=set(),
            ),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.get_cached_folders",
                return_value={},
            ),
            patch(
                "nomarr.workflows.library.scan_library_quick_wf.discover_library_folders",
                return_value=[],
            ),
            patch("nomarr.workflows.library.scan_library_quick_wf.cleanup_stale_folders"),
            patch("nomarr.workflows.library.scan_library_quick_wf.cleanup_orphaned_entities_workflow"),
            patch("nomarr.workflows.library.scan_library_quick_wf.update_scan_progress"),
            patch("nomarr.workflows.library.scan_library_quick_wf.mark_scan_completed"),
        ):
            result = scan_library_quick_workflow(mock_db, library, tagger_version="v1")

        assert result["scan_duration_s"] == 2
