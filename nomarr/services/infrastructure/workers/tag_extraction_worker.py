"""Tag extraction worker thread.

Single background threading.Thread that reads audio tags for files in the
``not_hydrated`` state and seeds entities (artist, album, genre etc.)
into the graph.  This is Pass 2 of the two-pass scan pipeline:

  Pass 1 (scan): fast disk walk → upsert files → seed initial state edges
  Pass 2 (this): read audio tags → write to DB → seed entities
                 → transition not_hydrated → hydrated

No locking needed — single thread, no other worker touches not_hydrated files.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import (
    discover_next_file_needing_tags,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_HYDRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_HYDRATED,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

IDLE_SLEEP_S = 1.0
MAX_CONSECUTIVE_ERRORS = 10


def _process_file(db: Database, song_id: int) -> None:
    """Extract tags for one song and transition it to hydrated.

    Steps:
    1. Load track record and resolve absolute path
    2. Extract audio metadata (mutagen via extract_metadata)
    3. Persist nom: tags to DB (save_song_tags)
    4. Seed entity graph (artist, album, genre etc.)
    5. Transition state: not_hydrated → hydrated
    6. Clear any error state that may have been set previously

    Args:
        db: Database instance
        song_id: Integer primary key of the song record

    Raises:
        Exception: Propagated to caller for error counting and state transition

    """
    from nomarr.components.infrastructure.path_comp import build_library_path_from_input
    from nomarr.components.library.metadata_extraction_comp import extract_metadata
    from nomarr.components.library.song_sync_comp import save_song_tags
    from nomarr.components.metadata.entity_seeding_comp import seed_entities_for_scan_batch
    from nomarr.components.tagging.tag_parsing_comp import parse_tag_values

    song_doc = db.library.get_song(song_id)
    if song_doc is None:
        msg = f"Song not found: {song_id}"
        raise ValueError(msg)
    path: str = str(song_doc["path"])
    namespace: str = str(song_doc.get("namespace", "nom"))

    library_path = build_library_path_from_input(path, db)
    if not library_path.is_valid():
        msg = f"Invalid library path for {song_id}: {library_path.reason}"
        raise ValueError(msg)

    metadata = extract_metadata(library_path, namespace=namespace)

    # Persist nom: tags stored inside the audio file
    nom_tags: dict = metadata.get("nom_tags") or {}
    if nom_tags:
        parsed_nom_tags = parse_tag_values(nom_tags)
        prefixed = {
            (f"{namespace}:{name}" if not name.startswith(f"{namespace}:") else name): values
            for name, values in parsed_nom_tags.items()
        }
        save_song_tags(db, str(song_id), prefixed)

    # Seed entity graph (artist, album, genre etc.)
    seed_entities_for_scan_batch(db, [str(song_id)], {str(song_id): metadata})

    # Update duration_seconds on the track record if not already set
    duration = metadata.get("duration")
    if duration is not None and not song_doc.get("duration_seconds"):
        db.library.update_song_fields(song_id, {"duration_seconds": duration})

    transition_song_state(db, [song_id], STATE_NOT_HYDRATED, STATE_HYDRATED)


class TagExtractionWorker(threading.Thread):
    """Background thread that extracts audio tags for unprocessed library files.

    Claims files in the ``not_hydrated`` state, reads their audio
    metadata via mutagen, writes tags and entity graph edges to DB, then
    transitions the state to ``hydrated``.

    Args:
        db: Shared Database instance (same as the application's main db)
        worker_id: Stable identifier for claim ownership tracking
        stop_event: Optional external threading.Event for cooperative shutdown

    """

    def __init__(
        self,
        db: Database,
        worker_id: str = "tag_extractor",
        stop_event: threading.Event | None = None,
    ) -> None:
        super().__init__(daemon=True, name=f"TagExtractor-{worker_id}")
        self._db = db
        self._worker_id = worker_id
        self._stop_event = stop_event or threading.Event()

    def stop(self) -> None:
        """Signal the worker to stop after its current file completes."""
        self._stop_event.set()

    def run(self) -> None:
        """Worker main loop: discover → process, repeat."""
        logger.info("[%s] Tag extraction worker started", self._worker_id)
        consecutive_errors = 0

        while not self._stop_event.is_set():
            file_doc = discover_next_file_needing_tags(self._db, exclude_claimed=False)
            if file_doc is None:
                self._stop_event.wait(IDLE_SLEEP_S)
                continue
            song_id: int = int(file_doc["id"])

            try:
                _process_file(self._db, song_id)
                consecutive_errors = 0
                logger.debug("[%s] Extracted tags for %s", self._worker_id, song_id)
            except Exception:
                logger.exception("[%s] Error extracting tags for %s", self._worker_id, song_id)
                try:
                    transition_song_state(self._db, [song_id], STATE_NOT_ERRORED, STATE_ERRORED)
                except Exception:
                    logger.exception("[%s] Failed to set error state for %s", self._worker_id, song_id)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "[%s] %d consecutive errors — stopping tag extraction worker",
                        self._worker_id,
                        consecutive_errors,
                    )
                    break

        logger.info("[%s] Tag extraction worker stopped", self._worker_id)
