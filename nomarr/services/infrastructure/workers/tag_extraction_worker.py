"""Tag extraction worker thread.

Single background threading.Thread that reads audio tags for files in the
``not_hydrated`` state and submits them to the atomic song-hydration
intent (``db.library.songs.hydrate_song``).  This is Pass 2 of the
two-pass scan pipeline:

  Pass 1 (scan): fast disk walk → upsert files → seed initial state edges
  Pass 2 (this): read audio tags → build one ``HydrateSongInput`` →
                 hydrate atomically (tags, relationships, duration,
                 not_hydrated → hydrated in one unit of work)

  Files are claimed through the shared worker-claim mechanism so multiple
  extraction workers cannot process the same song concurrently.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from nomarr.components.library.library_song_state_comp import (
    transition_song_state,
)
from nomarr.components.workers.worker_discovery_comp import release_claim
from nomarr.components.workers.worker_tag_comp import discover_and_claim_file_for_tags
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

IDLE_SLEEP_S = 1.0
MAX_CONSECUTIVE_ERRORS = 10


def _process_file(db: Database, song_id: int) -> None:
    """Extract tags for one song and hydrate it via the atomic intent.

    Builds exactly one :class:`HydrateSongInput` from the extracted audio
    metadata and submits it to ``db.library.songs.hydrate_song``, which
    owns the whole unit of work: parsed ``nom:`` tags, entity relationships,
    the forward-compatible (accepted-but-ignored) metadata-cache fields,
    the one-shot duration fill, and the ``not_hydrated`` → ``hydrated``
    state transition are committed together (or rolled back together on
    failure).

    Steps:
    1. Load track record and resolve absolute path
    2. Extract audio metadata (mutagen via extract_metadata)
    3. Parse/prefix ``nom:`` tag values (namespace prefixing stays here)
    4. Derive entity tags and metadata-cache fields in the metadata components
    5. Submit one HydrateSongInput to the atomic hydration intent

    Args:
        db: Database instance
        song_id: Integer primary key of the song record

    Raises:
        Exception: Propagated to caller for error counting and state transition

    """
    from nomarr.components.infrastructure.path_comp import build_library_path_from_input
    from nomarr.components.library.metadata_extraction_comp import extract_metadata
    from nomarr.components.metadata.entity_seeding_comp import extract_entity_tag_mapping
    from nomarr.components.metadata.metadata_cache_comp import compute_metadata_cache_fields
    from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
    from nomarr.helpers.dto.hydration_dto import HydrateSongInput

    song = db.library.get_song(song_id)
    if song is None:
        msg = f"Song not found: {song_id}"
        raise ValueError(msg)
    path: str = song.path
    namespace: str = "nom"

    library_path = build_library_path_from_input(path, db)
    if not library_path.is_valid():
        msg = f"Invalid library path for {song_id}: {library_path.reason}"
        raise ValueError(msg)

    metadata = extract_metadata(library_path, namespace=namespace)

    # Parse/prefix nom: tags stored inside the audio file (prefixing stays here)
    parsed_nom_tags: dict[str, list[str | int | float]] = {}
    nom_tags: dict = metadata.get("nom_tags") or {}
    if nom_tags:
        parsed = parse_tag_values(nom_tags)
        parsed_nom_tags = {
            (f"{namespace}:{name}" if not name.startswith(f"{namespace}:") else name): values
            for name, values in parsed.items()
        }

    # Derive entity tags and forward-compatible metadata-cache fields in the
    # metadata components (never in persistence).
    entity_tags = extract_entity_tag_mapping(metadata)
    metadata_cache = compute_metadata_cache_fields(metadata)

    # One atomic single-song hydration intent (tags, relationships, cache
    # fields, one-shot duration, state transition all in one unit of work).
    duration = metadata.get("duration")
    hydrate_input = HydrateSongInput(
        song_id=song_id,
        parsed_nom_tags=parsed_nom_tags,
        entity_tags=entity_tags,
        metadata_cache=metadata_cache,
        duration_seconds=float(duration) if duration is not None else None,
    )
    db.library.songs.hydrate_song(hydrate_input)


class TagExtractionWorker(threading.Thread):
    """Background thread that extracts audio tags for unprocessed library files.

    Claims files in the ``not_hydrated`` state, reads their audio metadata
    via mutagen, and submits one ``HydrateSongInput`` to the atomic
    ``db.library.songs.hydrate_song`` intent, which writes tags, entity
    edges, one-shot duration, and the ``hydrated`` state in one unit of work.

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
            file_id = discover_and_claim_file_for_tags(self._db, self._worker_id)
            if file_id is None:
                self._stop_event.wait(IDLE_SLEEP_S)
                continue
            song_id: int = int(file_id)

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
            finally:
                try:
                    release_claim(self._db, song_id, self._worker_id)
                except Exception:
                    logger.exception("[%s] Failed to release claim for %s", self._worker_id, song_id)

        logger.info("[%s] Tag extraction worker stopped", self._worker_id)
