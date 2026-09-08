"""LibraryResetRepo — repository-owned all-or-nothing global library reset.

Per ASR-0013/ASR-0014, ADR-046/047 and the library-reset persistence
choreography CONTRACTS.md (2026-09-08), a successful admin clear removes the
documented reset set (``embeddings``, ``ml_output_streams``,
``pipeline_states``, ``song_tags``, ``song_state_assignments``, ``songs``,
``library_folders``, ``tags``, ``library_scans``) while preserving configured
``libraries``, model/model-output rows, calibration, embedding streams, health,
and worker claims.

The repository owns the whole aggregate: physical table enumeration, delete
ordering, set-based statements, foreign-key handling, batching, and the single
transaction boundary. Callers never supply storage names, song ids, collection
names, or a delete order, and no facade/caller opens a transaction around this
primitive (AR-SDR-4).

Atomicity mirrors ``MlInferenceRepo.replace_song_inference_results`` exactly: every
statement runs inside one repository-owned ``begin_nested`` savepoint and the unit
commits exactly once on success. On any failure the savepoint is rolled back (no
uncommitted partial write can leak) and the exception propagates, so a failed
reset exposes no partial-success result and leaves the session usable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import Table, delete

from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.library_folder import LibraryFolder
from nomarr.persistence.models.library_scan import LibraryScan
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.models.pipeline_state import PipelineState
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state_assignment import SongStateAssignment
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

# Physical table representations owned by the reset. Enumerating them here (not
# in any caller) is what lets persistence own storage mechanics end-to-end.
_T_EMBEDDINGS = cast("Table", Embedding.__table__)
_T_OUTPUT_STREAMS = cast("Table", MlOutputStream.__table__)
_T_SONG_STATE_ASSIGNMENTS = cast("Table", SongStateAssignment.__table__)
_T_SONG_TAGS = cast("Table", SongTag.__table__)
_T_SONGS = cast("Table", Song.__table__)
_T_PIPELINE_STATES = cast("Table", PipelineState.__table__)
_T_LIBRARY_SCANS = cast("Table", LibraryScan.__table__)
_T_LIBRARY_FOLDERS = cast("Table", LibraryFolder.__table__)
_T_TAGS = cast("Table", Tag.__table__)


class LibraryResetRepo:
    """Repository owning the all-or-nothing global library reset aggregate."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def reset_library_data(self) -> None:
        """Atomically clear the documented reset data set.

        Runs every table-wide delete through private, no-commit statements
        inside one repository-owned ``begin_nested`` savepoint and commits once
        on success. On any failure the savepoint rolls back and the exception
        propagates, so no partial-success result is ever exposed. The method
        takes no caller-provided collections, song ids, library ids, or storage
        identifiers and returns ``None``.

        Delete order is child-first so foreign keys are respected even without
        relying on ``ON DELETE`` cascades, and tables whose parent (``libraries``)
        is preserved (``pipeline_states``, ``library_scans``,
        ``library_folders``) are always deleted explicitly. ``song_states``,
        ``libraries``, and every preserved-boundary table are never touched.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                # Children of ``songs`` (and of ``tags`` / ``song_states``) go
                # first so bulk parent deletes cannot strand referencing rows.
                self._delete_embeddings()
                self._delete_output_streams()
                self._delete_song_state_assignments()
                self._delete_song_tags()
                self._delete_songs()
                # Parents that survive the reset still have rows explicitly removed.
                self._delete_pipeline_states()
                self._delete_library_scans()
                self._delete_library_folders()
                self._delete_tags()
            self._session.commit()

    # ── private no-commit, set-based table clears ─────────────────

    def _delete_embeddings(self) -> None:
        """Delete all vector rows (no commit)."""
        self._session.execute(delete(_T_EMBEDDINGS))

    def _delete_output_streams(self) -> None:
        """Delete all output streams in one table-wide statement (no commit).

        Replaces the legacy song-by-song (N+1) output-stream delete.
        """
        self._session.execute(delete(_T_OUTPUT_STREAMS))

    def _delete_song_state_assignments(self) -> None:
        """Delete all song→state edges (no commit). Preserves ``song_states``."""
        self._session.execute(delete(_T_SONG_STATE_ASSIGNMENTS))

    def _delete_song_tags(self) -> None:
        """Delete the ``song_tags`` junction (no commit). Preserves ``tags`` rows."""
        self._session.execute(delete(_T_SONG_TAGS))

    def _delete_songs(self) -> None:
        """Delete all song rows (no commit)."""
        self._session.execute(delete(_T_SONGS))

    def _delete_pipeline_states(self) -> None:
        """Delete all pipeline-state rows, including for empty libraries (no commit)."""
        self._session.execute(delete(_T_PIPELINE_STATES))

    def _delete_library_scans(self) -> None:
        """Delete all scan records (no commit)."""
        self._session.execute(delete(_T_LIBRARY_SCANS))

    def _delete_library_folders(self) -> None:
        """Delete all folder rows, including nested ``parent_id`` chains (no commit)."""
        self._session.execute(delete(_T_LIBRARY_FOLDERS))

    def _delete_tags(self) -> None:
        """Delete all tag rows (no commit)."""
        self._session.execute(delete(_T_TAGS))
