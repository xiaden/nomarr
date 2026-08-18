"""ML persistence sub-facade (``MlDb``).

Groups model, output-stream, vector, and calibration persistence into a single
intent facade wired as ``db.ml``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.calibration_repo_dto import CalibrationHistoryRecord, CalibrationStateRecord
    from nomarr.helpers.dto.embedding_stream_repo_dto import EmbeddingStreamRecord
    from nomarr.helpers.dto.model_repo_dto import ModelRecord
    from nomarr.helpers.dto.output_repo_dto import ModelOutputRecord, OutputStreamRecord
    from nomarr.helpers.dto.vector_repo_dto import EmbeddingRecord, SimilarResult
    from nomarr.persistence.database.calibration_repo import CalibrationRepo
    from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
    from nomarr.persistence.database.model_repo import ModelRepo
    from nomarr.persistence.database.output_repo import OutputRepo
    from nomarr.persistence.database.vector_repo import VectorRepo

logger = logging.getLogger(__name__)


class MlDb:
    """Persistence sub-facade for ML model, stream, and vector operations.

    Routine callers use the normalized ML intent methods on this facade.
    Destructive maintenance operations (``truncate_vectors_in_collection``,
    ``truncate_calibration_states``, ``truncate_calibration_history``) are
    exposed directly on this facade.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        vector_repo: VectorRepo | None = None,
        model_repo: ModelRepo | None = None,
        output_repo: OutputRepo | None = None,
        calibration_repo: CalibrationRepo | None = None,
        embedding_stream_repo: EmbeddingStreamRepository | None = None,
    ) -> None:
        """Initialise the ML persistence facade.

        All repository parameters are ``Optional`` to support the phased
        migration to PostgreSQL — ``db.py`` wires SQL repos
        incrementally.  ``vector_repo``, ``model_repo``, and ``calibration_repo``
        are asserted as non-None at the end of construction because they are
        required by the routine top-level API.

        Destructive maintenance operations (``truncate_vectors_in_collection``,
        ``truncate_calibration_states``, ``truncate_calibration_history``) are
        exposed directly on this facade.
        """
        self._vector_repo = vector_repo
        self._model_repo = model_repo
        self._output_repo = output_repo
        self._calibration_repo = calibration_repo
        self._embedding_stream_repo = embedding_stream_repo
        self._session = session
        assert vector_repo is not None, "VectorRepo is required"
        assert model_repo is not None, "ModelRepo is required"
        assert calibration_repo is not None, "CalibrationRepo is required"

    # ------------------------------------------------------------------
    # Maintenance methods (destructive reset/repair)
    # ------------------------------------------------------------------

    def truncate_vectors_in_collection(self, _collection_name: str) -> None:
        """Truncate all embeddings.

        ``collection_name`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses a single ``embeddings`` table.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.truncate_embeddings()

    def truncate_calibration_states(self) -> None:
        """Truncate all calibration state rows."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        self._calibration_repo.truncate_states()

    def truncate_calibration_history(self) -> None:
        """Truncate all calibration history rows."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        self._calibration_repo.truncate_history()

    # ------------------------------------------------------------------
    # Canonical routine top-level methods aligned with the DD contract
    # ------------------------------------------------------------------

    def list_vector_collection_names(self) -> list[str]:
        """Return all registered vector collection names."""
        return ["embeddings"]

    def clear_vector_collection(self, _collection_name: str) -> None:
        """Remove all vectors from the embeddings table.

        ``collection_name`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses a single ``embeddings`` table.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.delete_all_embeddings()

    def list_output_streams_for_song(self, song_id: int) -> list[OutputStreamRecord]:
        """Return all canonical output stream records linked to one song."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.list_output_streams_for_song(song_id)

    def list_song_vectors(self, _collection_name: str, song_id: int) -> list[EmbeddingRecord]:
        """Return all embedding records stored for one song.

        ``collection_name`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses a single ``embeddings`` table with a ``backbone_id`` column.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        return self._vector_repo.get_embeddings_for_song(song_id)

    def search_vectors(
        self,
        collection_name: str,
        query_vector: list[float],
        *,
        limit: int,
    ) -> list[SimilarResult]:
        """Return nearest-neighbour vectors for ``query_vector`` in ``collection_name``.

        Canonical caller entrypoint for vector similarity search; higher layers
        should use this method instead of the removed legacy ``vector_search``
        facade name.

        ``collection_name`` is repurposed as ``backbone_id`` — PostgreSQL uses a
        single ``embeddings`` table partitioned by backbone rather than dynamic
        PostgreSQL tables.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        return self._vector_repo.find_nearest(query_vector, backbone_id=collection_name, limit=limit)

    def get_model(self, model_id: str) -> ModelRecord | None:
        """Return the ml_models record for model_id, or None if absent."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.get_model(model_id)

    def get_model_by_type(self, type_str: str) -> ModelRecord | None:
        """Return the ml_models record whose model_type matches, or None.

        Replaces the former ``get_model_by_path`` — the relational schema
        uses ``model_type`` rather than a filesystem path.
        """
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.get_model_by_type(type_str)

    def add_model(self, payload: dict[str, Any]) -> ModelRecord:
        """Upsert a model row and return the persisted ModelRecord."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.upsert_model(payload)

    def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        """Apply field updates to an existing ml_models row."""
        assert self._model_repo is not None, "ModelRepo not wired"
        self._model_repo.update_model(model_id, fields)

    def remove_model(self, model_id: str) -> None:
        """Delete one ml_models row by id."""
        assert self._model_repo is not None, "ModelRepo not wired"
        self._model_repo.delete_model(model_id)

    def list_models(self) -> list[ModelRecord]:
        """Return all ml_models records."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.list_models()

    def count_models(self) -> int:
        """Return the total number of registered ml_models rows."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.count_models()

    def list_models_by_ids(self, model_ids: list[str]) -> list[ModelRecord]:
        """Return ml_models records whose ids are in model_ids."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.get_models_by_ids(model_ids)

    def get_model_output(self, output_id: int) -> ModelOutputRecord | None:
        """Return one ml_model_outputs record by primary key, or None."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.get_output(output_id)

    def list_model_outputs(self, model_id: str) -> list[ModelOutputRecord]:
        """Return all ml_model_outputs records linked to one model, ordered by index."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.list_model_outputs(model_id)

    def get_calibration_state(self, model_id: str) -> CalibrationStateRecord | None:
        """Return the calibration state for model_id, or None if absent."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.get_state(model_id)

    def get_calibration_state_view(self, head_name: str, label: str) -> CalibrationStateRecord | None:
        """Return a calibration state by logical (head_name, label) identity.

        Scans all calibration states and filters by composite key in Python
        since CalibrationRepo indexes by model_id only.

        .. note::
           For production scaling, a dedicated DB query should be added to
           CalibrationRepo (e.g. ``get_state_by_head_and_label``) to avoid
           the full-table scan.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        states = self._calibration_repo.list_states()
        for state in states:
            sd = state["state_data"]
            if sd.get("head_name") == head_name and sd.get("label") == label:
                return state
        return None

    def list_calibration_states(self) -> list[CalibrationStateRecord]:
        """Return all calibration state records."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.list_states()

    def list_calibration_history_snapshots(self, calibration_key: str) -> list[CalibrationHistoryRecord]:
        """Return all calibration history records for one model.

        ``calibration_key`` maps to ``model_id`` in the relational schema.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.get_history(calibration_key)

    def add_calibration_history(self, payload: dict[str, Any]) -> CalibrationHistoryRecord:
        """Insert a calibration history event and return the persisted record."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.record_history(
            model_id=payload["model_id"],
            event=payload["event"],
            data=payload.get("data", {}),
        )

    def count_calibration_history(self, model_id: str) -> int:
        """Return the number of calibration history entries for one model.

        .. note::
           TODO: CalibrationRepo has no ``count_history`` method — this
           fetches all rows and counts in Python.  Add a ``COUNT(*)`` query
           to CalibrationRepo for production scaling.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        history = self._calibration_repo.get_history(model_id)
        return len(history)

    def replace_embedding_stream_for_song(
        self,
        song_id: int,
        backbone: str,
        stream_payload: dict[str, Any],
    ) -> EmbeddingStreamRecord:
        """Upsert an embedding stream for a (song, backbone) pair.

        Returns the persisted ``EmbeddingStreamRecord``.
        """
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        return self._embedding_stream_repo.upsert_stream(song_id, backbone, stream_payload)

    def get_embedding_stream_for_song(
        self,
        song_id: int,
        backbone: str,
    ) -> EmbeddingStreamRecord | None:
        """Return the embedding stream for ``(song_id, backbone)``, or ``None``."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        return self._embedding_stream_repo.get_stream(song_id, backbone)

    def list_embedding_streams_by_backbone(
        self,
        backbone: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmbeddingStreamRecord]:
        """List all embedding streams for a backbone with pagination."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        return self._embedding_stream_repo.list_by_backbone(backbone, limit=limit, offset=offset)

    def remove_embedding_streams_for_song(self, song_id: int) -> None:
        """Delete all embedding streams linked to one song."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        self._embedding_stream_repo.delete_for_song(song_id)

    # ------------------------------------------------------------------
    # Promoted intent-complete write methods
    # ------------------------------------------------------------------

    def replace_output_streams_for_song(
        self,
        song_id: int,
        stream_payloads: list[dict[str, Any]],
    ) -> None:
        """Replace all canonical output streams for one song (delete-then-insert).

        .. note::
           The delete and each insert commit independently via their repos.
           Worst case is partial completion if an insert fails after the
           delete succeeded.  Part F should add proper transaction management
           (e.g. a facade-level ``begin/commit`` wrapper) for atomicity.
        """
        assert self._output_repo is not None, "OutputRepo not wired"
        self._output_repo.delete_outputs_for_song(song_id)
        for payload in stream_payloads:
            self._output_repo.store_output_stream(
                song_id=song_id,
                model_id=payload["model_id"],
                status=payload["status"],
            )

    def remove_output_streams_for_song(self, song_id: int) -> None:
        """Delete all canonical output streams linked to one song."""
        assert self._output_repo is not None, "OutputRepo not wired"
        self._output_repo.delete_outputs_for_song(song_id)

    def replace_song_vectors(
        self,
        collection_name: str,
        song_id: int,
        vector_payloads: list[dict[str, Any]],
    ) -> None:
        """Replace all vector rows for one song (delete-then-insert).

        ``collection_name`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses a single ``embeddings`` table.

        .. note::
           The delete and each insert commit independently via their repos.
           Worst case is partial completion if an insert fails after the
           delete succeeded.  Part F should add proper transaction management
           for atomicity.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.delete_embeddings_for_song(song_id)
        for payload in vector_payloads:
            # Require embedding_vector (or fallback key 'embedding') — no silent
            # empty-list default, which would cause a confusing DB dimension error.
            embedding_vector = payload.get("embedding_vector")
            if embedding_vector is None:
                embedding_vector = payload["embedding"]
            self._vector_repo.insert_embedding(
                song_id=song_id,
                backbone_id=payload.get("backbone_id", collection_name),
                model_id=payload["model_id"],
                embedding_vector=embedding_vector,
                genres=payload.get("genres"),
            )

    def remove_song_vectors(self, _collection_name: str, song_id: int) -> None:
        """Delete all vector rows for one song.

        ``collection_name`` is accepted for backwards compatibility but ignored.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.delete_embeddings_for_song(song_id)

    def remove_vectors_for_songs(self, _collection_name: str, song_ids: list[int]) -> None:
        """Delete all vector rows for each song_id in song_ids.

        .. note::
           TODO: N+1 — loops ``delete_embeddings_for_song`` per song_id.
           VectorRepo has no batch-delete-by-song-ids method yet.  Add a
           single ``DELETE … WHERE song_id = ANY(…)`` to VectorRepo for
           production scaling.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        for sid in song_ids:
            self._vector_repo.delete_embeddings_for_song(sid)

    def replace_model_output(
        self,
        song_id: int,
        model_id: str,
        _output_key: str,
        payload: dict[str, Any],
    ) -> ModelOutputRecord:
        """Store one model output and return the persisted record.

        ``output_key`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses auto-generated integer primary keys.
        """
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.store_model_output(
            song_id=song_id,
            model_id=model_id,
            output_data=payload,
        )

    def remove_model_output(self, output_id: int) -> None:
        """Delete one model output by primary key."""
        assert self._output_repo is not None, "OutputRepo not wired"
        self._output_repo.delete_output(output_id)

    def remove_model_outputs_for_model(self, model_id: str) -> int:
        """Delete all model outputs for one model and return the count deleted."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.delete_outputs_for_model(model_id)

    def list_all_calibration_states_with_models(self) -> list[dict[str, Any]]:
        """Return all calibration states enriched with their owning model metadata."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.list_states_with_models()

    def replace_calibration_state(
        self,
        model_id: str,
        payload: dict[str, Any],
    ) -> CalibrationStateRecord:
        """Upsert calibration state for a model.

        PostgreSQL uses auto-generated integer primary keys.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return self._calibration_repo.set_state(model_id, state_data=payload)

    def remove_calibration_state(self, calibration_id: int) -> None:
        """Delete one calibration state by primary key.

        ``calibration_id`` is now an ``int`` (PostgreSQL PK).
        Edge deletion (model_has_calibration) is no longer needed.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        self._calibration_repo.delete_state(calibration_id)

    def remove_calibration_history_for_model(self, model_id: str) -> None:
        """Delete all calibration history entries for one model."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        self._calibration_repo.delete_history_for_model(model_id)

    def remove_calibration_history_entries(self, entry_ids: list[str]) -> None:
        """Delete calibration history entries by ID list.

        Entry IDs are converted from ``str`` to ``int`` for the PostgreSQL
        ``calibration_history.id`` integer primary key.
        """
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        int_ids: list[int] = [int(e) for e in entry_ids]
        self._calibration_repo.delete_history_entries(int_ids)

    def get_embedding_stats(self, backbone_id: str) -> dict[str, int]:
        """Return hot_count and cold_count for a backbone."""
        assert self._vector_repo is not None, "VectorRepo not wired"
        return self._vector_repo.get_embedding_stats(backbone_id)

    def has_embedding_index(self, _backbone_id: str) -> bool:
        """Return whether the backbone has an ANN index.

        The partial HNSW index is created once by the schema migration and
        maintained automatically by PostgreSQL — it covers all cold-tier
        rows and is updated on VACUUM.  There is no per-backbone index
        creation or teardown, so this always returns ``True``.
        """
        return True

    def index_backbone_embeddings(self, backbone_id: str, _embed_dim: int = 0, _nlists: int = 0) -> int:
        """Drain hot embeddings to cold tier for a backbone.

        ``embed_dim`` and ``nlists`` are accepted for backwards compatibility
        but ignored — PostgreSQL manages the HNSW index automatically.
        Returns the number of rows drained.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        return self._vector_repo.drain_hot_to_cold(backbone_id)

    def rebuild_backbone_embedding_index(
        self,
        backbone_id: str,
    ) -> None:
        """Rebuild the ANN index for a backbone.

        PostgreSQL manages the partial HNSW index automatically — no manual
        rebuild is needed.
        """
        logger.info(
            "PostgreSQL-managed HNSW index for backbone %s — no manual rebuild needed",
            backbone_id,
        )

    # ------------------------------------------------------------------
    # Vector index management methods (Phase 3 — consumer facade)
    # ------------------------------------------------------------------

    def has_vector_index(self, _backbone_id: str) -> bool:
        """Check if the cold HNSW index exists in the PostgreSQL catalog.

        The partial HNSW index (``ix_embeddings_cold_hnsw``) is created once
        by the schema migration and shared across all backbones.  The
        ``backbone_id`` parameter is accepted for API compatibility but is
        not used — the index covers all cold-tier rows regardless of backbone.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        result = self._vector_repo._session.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_embeddings_cold_hnsw')"),
        )
        return bool(result.scalar())

    def build_vector_index(self, _embed_dim: int) -> None:
        """No-op — PG manages the cold HNSW index automatically via schema migration.

        ``embed_dim`` is accepted for API compatibility but ignored.
        """
        logger.info("PG manages the cold HNSW index automatically via schema migration.")

    def drop_vector_index(self) -> None:
        """No-op — the partial HNSW index is managed by the schema migration."""
        logger.info(
            "PG partial HNSW index (ix_embeddings_cold_hnsw) is managed by the schema migration — drop is a no-op.",
        )

    def rebuild_vector_index(self, _embed_dim: int) -> None:
        """Rebuild the cold HNSW index via ``REINDEX INDEX CONCURRENTLY``.

        ``embed_dim`` is accepted for API compatibility but ignored — the
        index dimension is fixed at schema creation time.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        try:
            self._vector_repo._session.execute(text("REINDEX INDEX CONCURRENTLY ix_embeddings_cold_hnsw"))
            logger.info("Successfully rebuilt cold HNSW index (ix_embeddings_cold_hnsw).")
        except Exception:
            logger.exception("Failed to rebuild cold HNSW index (ix_embeddings_cold_hnsw).")
            raise

    def backfill_genres(self, backbone_id: str) -> int:
        """Count embeddings that need genre backfilling.

        Full genre backfill requires joining with the songs tag data,
        which is outside MlDb's scope.  This method counts the rows with
        ``genres IS NULL`` for the given backbone and returns the count.

        Returns:
            Number of embedding rows with NULL genres for this backbone.

        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        result = self._vector_repo._session.execute(
            text("SELECT COUNT(*) FROM embeddings WHERE backbone_id = :backbone_id AND genres IS NULL"),
            {"backbone_id": backbone_id},
        )
        count = int(result.scalar() or 0)
        if count > 0:
            logger.warning(
                "backfill_genres: %d embeddings for backbone '%s' have NULL genres. "
                "Full genre backfill requires the library facade (not available in MlDb scope).",
                count,
                backbone_id,
            )
        return count
