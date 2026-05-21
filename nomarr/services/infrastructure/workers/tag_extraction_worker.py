"""Tag extraction worker thread.

Single background threading.Thread that reads audio tags for files in the
``tags_not_extracted`` state and seeds entities (artist, album, genre etc.)
into the graph.  This is Pass 2 of the two-pass scan pipeline:

  Pass 1 (scan): fast disk walk → upsert files → seed initial state edges
  Pass 2 (this): claim file → read audio tags → write to DB → seed entities
                 → transition tags_not_extracted → tags_extracted

"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.workers.worker_discovery_comp import release_claim
from nomarr.components.workers.worker_tag_comp import discover_and_claim_file_for_tags
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_TAGS_EXTRACTED,
    STATE_TAGS_NOT_EXTRACTED,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

IDLE_SLEEP_S = 1.0
MAX_CONSECUTIVE_ERRORS = 10


def _process_file(db: Database, file_id: str) -> None:
    """Extract tags for one file and transition it to tags_extracted.

    Steps:
    1. Load file document and resolve absolute path
    2. Extract audio metadata (mutagen via extract_metadata)
    3. Persist nom: tags to DB (save_file_tags)
    4. Seed entity graph (artist, album, genre etc.)
    5. Transition state: tags_not_extracted → tags_extracted
    6. Clear any error state that may have been set previously

    Args:
        db: Database instance
        file_id: Full file document ``_id`` (e.g. ``library_files/12345``)

    Raises:
        Exception: Propagated to caller for error counting and state transition

    """
    from nomarr.components.infrastructure.path_comp import build_library_path_from_input
    from nomarr.components.library.file_sync_comp import save_file_tags
    from nomarr.components.library.metadata_extraction_comp import extract_metadata
    from nomarr.components.metadata.entity_seeding_comp import seed_entities_for_scan_batch

    file_doc = db.library.get_file(file_id)
    if file_doc is None:
        msg = f"File not found: {file_id}"
        raise ValueError(msg)
    path: str = file_doc["path"]
    namespace: str = file_doc.get("namespace", "nom")

    library_path = build_library_path_from_input(path, db)
    if not library_path.is_valid():
        msg = f"Invalid library path for {file_id}: {library_path.reason}"
        raise ValueError(msg)

    metadata = extract_metadata(library_path, namespace=namespace)

    # Persist nom: tags stored inside the audio file
    nom_tags: dict = metadata.get("nom_tags") or {}
    if nom_tags:
        prefixed = {k if k.startswith(f"{namespace}:") else f"{namespace}:{k}": [v] for k, v in nom_tags.items()}
        save_file_tags(db, file_id, prefixed)

    # Seed entity graph (artist, album, genre etc.)
    seed_entities_for_scan_batch(db, [file_id], {file_id: metadata})

    # Update duration_seconds on the file document if not already set
    duration = metadata.get("duration")
    if duration is not None and not file_doc.get("duration_seconds"):
        db.library.update_file(file_id, {"duration_seconds": duration})

    transition_file_state(db, [file_id], STATE_TAGS_NOT_EXTRACTED, STATE_TAGS_EXTRACTED)


class TagExtractionWorker(threading.Thread):
    """Background thread that extracts audio tags for unprocessed library files.

    Claims files in the ``tags_not_extracted`` state, reads their audio
    metadata via mutagen, writes tags and entity graph edges to DB, then
    transitions the state to ``tags_extracted``.

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
        """Worker main loop: claim → process → release, repeat."""
        logger.info("[%s] Tag extraction worker started", self._worker_id)
        consecutive_errors = 0

        while not self._stop_event.is_set():
            file_id = discover_and_claim_file_for_tags(self._db, self._worker_id)
            if file_id is None:
                self._stop_event.wait(IDLE_SLEEP_S)
                continue

            try:
                _process_file(self._db, file_id)
                consecutive_errors = 0
                logger.debug("[%s] Extracted tags for %s", self._worker_id, file_id)
            except Exception:
                logger.exception("[%s] Error extracting tags for %s", self._worker_id, file_id)
                try:
                    transition_file_state(self._db, [file_id], STATE_NOT_ERRORED, STATE_ERRORED)
                except Exception:
                    logger.exception("[%s] Failed to set error state for %s", self._worker_id, file_id)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "[%s] %d consecutive errors — stopping tag extraction worker",
                        self._worker_id,
                        consecutive_errors,
                    )
                    break
            finally:
                try:
                    release_claim(self._db, file_id)
                except Exception:
                    logger.exception("[%s] Failed to release claim for %s", self._worker_id, file_id)

        logger.info("[%s] Tag extraction worker stopped", self._worker_id)
