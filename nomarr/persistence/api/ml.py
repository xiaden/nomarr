"""ML persistence sub-facade (``MlDb``).

Groups model, output-stream, vector, and calibration persistence into a single
intent facade wired as ``db.ml``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.ml_embedding_stream_dataclass import EmbeddingStream
from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStream, OutputStreamWrite
from nomarr.helpers.time_helper import now_ms

# This mapper edit accompanies the concurrent ML facade migration: keeping the
# conversion here makes the table repository's storage DTOs unable to escape.
from nomarr.persistence.mappers.calibration_mapper import (
    calibration_state_from_joined_record,
    calibration_state_from_record,
    calibration_state_payload,
)
from nomarr.persistence.mappers.model_mapper import (
    registered_model_from_record,
    registered_model_insert_payload,
)
from nomarr.persistence.mappers.output_mapper import model_output_from_record

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
    from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel
    from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput
    from nomarr.helpers.dto.calibration_repo_dto import CalibrationHistoryRecord
    from nomarr.helpers.dto.vector_repo_dto import EmbeddingRecord, SimilarResult
    from nomarr.persistence.database.calibration_repo import CalibrationRepo
    from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
    from nomarr.persistence.database.ml_inference_repo import MlInferenceRepo
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
        ml_inference_repo: MlInferenceRepo | None = None,
    ) -> None:
        """Initialise the ML persistence facade.

        All repository parameters are ``Optional`` to support the phased
        migration to PostgreSQL — ``db.py`` wires SQL repos
        incrementally.  ``vector_repo``, ``model_repo``, and ``calibration_repo``
        are required by the routine top-level API and are validated during
        construction.

        Destructive maintenance operations (``truncate_vectors_in_collection``,
        ``truncate_calibration_states``, ``truncate_calibration_history``) are
        exposed directly on this facade.
        """
        self._vector_repo = vector_repo
        self._model_repo = model_repo
        self._output_repo = output_repo
        self._calibration_repo = calibration_repo
        self._embedding_stream_repo = embedding_stream_repo
        self._ml_inference_repo = ml_inference_repo
        self._session = session
        if vector_repo is None:
            raise ValueError("VectorRepo is required")
        if model_repo is None:
            raise ValueError("ModelRepo is required")
        if calibration_repo is None:
            raise ValueError("CalibrationRepo is required")

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
        """Return registered backbone identifiers used by vector storage.

        PostgreSQL stores all vectors in one table, so these are logical
        collection names rather than table names. Model registrations are the
        authoritative source for available backbone identifiers.
        """
        assert self._model_repo is not None, "ModelRepo not wired"
        return sorted({model.backbone_id for model in self.list_models()})

    def clear_vector_collection(self, _collection_name: str) -> None:
        """Remove all vectors from the embeddings table.

        ``collection_name`` is accepted for backwards compatibility but ignored —
        PostgreSQL uses a single ``embeddings`` table.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.delete_all_embeddings()

    def list_output_streams_for_song(self, song_id: int) -> list[OutputStream]:
        """Return output streams for a song without exposing persistence row fields."""
        assert self._output_repo is not None, "OutputRepo not wired"
        # Concurrent ML output-stream work also touches this boundary; this mapper
        # is intentionally kept here so callers never depend on repository rows.
        return [
            OutputStream(
                output_id=record["output_id"],
                output_index=record["output_index"],
                values=record["values"],
            )
            for record in self._output_repo.list_output_streams_for_song(song_id)
        ]

    def list_song_vectors(self, collection_name: str, song_id: int, *, tier: str = "cold") -> list[EmbeddingRecord]:
        """Return embedding records for one song, backbone, and tier.

        ``collection_name`` is the backbone identifier. PostgreSQL uses a single
        ``embeddings`` table with a ``backbone_id`` column.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        return self._vector_repo.get_embeddings_for_song(song_id, collection_name, tier)

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

    def get_model(self, model_id: str) -> RegisteredModel | None:
        """Return the registered model for ``model_id``, or None if absent."""
        assert self._model_repo is not None, "ModelRepo not wired"
        record = self._model_repo.get_model(model_id)
        return registered_model_from_record(record) if record else None

    def get_model_by_path(self, path: str) -> RegisteredModel | None:
        """Return the registered model for ``path``, or None if absent."""
        assert self._model_repo is not None, "ModelRepo not wired"
        record = self._model_repo.get_model_by_path(path)
        return registered_model_from_record(record) if record else None

    def get_model_by_type(self, model_type: str) -> RegisteredModel | None:
        """Return the registered model whose ``model_type`` matches."""
        assert self._model_repo is not None, "ModelRepo not wired"
        record = self._model_repo.get_model_by_type(model_type)
        return registered_model_from_record(record) if record else None

    def register_model(
        self,
        *,
        path: str,
        backbone: str,
        head_type: str,
        model_stem: str,
        output_count: int,
        source: str = "discovered",
        head_release_date: str = "",
        embedder_release_date: str = "",
    ) -> RegisteredModel:
        """Insert or update one registered model and return its domain object.

        The model's stable identity is derived from ``path``.  User-state flags
        (``fully_configured``/``is_known``) are preserved across re-registration.
        """
        assert self._model_repo is not None, "ModelRepo not wired"
        timestamp = now_ms().value
        existing = self._model_repo.get_model_by_path(path)
        if existing is None:
            fully_configured = False
            is_known = False
            registered_at: int | None = timestamp
        else:
            fully_configured = bool(existing.get("fully_configured", False))
            is_known = bool(existing.get("is_known", False))
            registered_at = existing.get("registered_at", timestamp)
        payload = registered_model_insert_payload(
            path=path,
            model_id=existing.get("id") if existing is not None else None,
            backbone=backbone,
            head_type=head_type,
            model_stem=model_stem,
            output_count=output_count,
            source=source,
            head_release_date=head_release_date,
            embedder_release_date=embedder_release_date,
            fully_configured=fully_configured,
            is_known=is_known,
            registered_at=registered_at,
        )
        record = self._model_repo.upsert_model(payload)
        return registered_model_from_record(record)

    def mark_model_fully_configured(self, model_id: str, value: bool) -> None:
        """Set the ``fully_configured`` flag on one registered model.

        Silently no-ops when the model is absent (preserves prior behaviour).
        """
        assert self._model_repo is not None, "ModelRepo not wired"
        if self._model_repo.get_model(model_id) is None:
            return
        self._model_repo.update_model(model_id, {"fully_configured": int(value)})

    def mark_model_known(self, model_id: str, value: bool) -> None:
        """Set the ``is_known`` flag on one registered model.

        Silently no-ops when the model is absent (preserves prior behaviour).
        """
        assert self._model_repo is not None, "ModelRepo not wired"
        if self._model_repo.get_model(model_id) is None:
            return
        self._model_repo.update_model(model_id, {"is_known": int(value)})

    def remove_model(self, model_id: str) -> None:
        """Delete one registered model by id."""
        assert self._model_repo is not None, "ModelRepo not wired"
        self._model_repo.delete_model(model_id)

    def list_models(self) -> list[RegisteredModel]:
        """Return all registered models as domain objects."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return [registered_model_from_record(r) for r in self._model_repo.list_models()]

    def build_model_output_index_map(self) -> dict[str, dict[int, str]]:
        """Return ``{model_path: {output_index: output_id}}`` across registered models."""
        result: dict[str, dict[int, str]] = {}
        for model in self.list_models():
            for output in self.list_model_outputs(model.id):
                if output.output_index is not None:
                    result.setdefault(model.path, {})[output.output_index] = output.output_id
        return result

    def count_models(self) -> int:
        """Return the total number of registered models."""
        assert self._model_repo is not None, "ModelRepo not wired"
        return self._model_repo.count_models()

    def get_model_output(self, output_id: str) -> ModelOutput | None:
        """Return one model output by stable output identity, or None.

        Maps the repository row to a domain :class:`ModelOutput` so callers never
        depend on storage row fields (integer PK, raw JSONB blob, timestamps).
        """
        assert self._output_repo is not None, "OutputRepo not wired"
        record = self._output_repo.get_output(output_id)
        return model_output_from_record(record) if record else None

    def list_model_outputs(self, model_id: str) -> list[ModelOutput]:
        """Return all model outputs linked to one model, ordered by index, as domain objects."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return [model_output_from_record(record) for record in self._output_repo.list_model_outputs(model_id)]

    def get_calibration_state(self, model_id: str) -> CalibrationState | None:
        """Return the calibration state owned by a stable model identity."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        record = self._calibration_repo.get_state(model_id)
        return calibration_state_from_record(record) if record else None

    def get_calibration_state_view(self, head_name: str, label: str) -> CalibrationState | None:
        """Return a calibration state by logical head and label identity."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        record = self._calibration_repo.get_state_by_head_label(head_name, label)
        return calibration_state_from_record(record) if record else None

    def list_calibration_states(self) -> list[CalibrationState]:
        """Return calibration states as domain objects."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return [calibration_state_from_record(r) for r in self._calibration_repo.list_states()]

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
        patches_emb: bytes,
    ) -> EmbeddingStream:
        """Upsert an embedding stream for a (song, backbone) pair.

        Returns the persisted stream without exposing persistence row fields.
        """
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        record = self._embedding_stream_repo.upsert_stream(song_id, backbone, patches_emb)
        return EmbeddingStream(backbone=record["backbone"], patches_emb=record["patches_emb"])

    def get_embedding_stream_for_song(
        self,
        song_id: int,
        backbone: str,
    ) -> EmbeddingStream | None:
        """Return the embedding stream for ``(song_id, backbone)``, or ``None``."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        record = self._embedding_stream_repo.get_stream(song_id, backbone)
        if record is None:
            return None
        return EmbeddingStream(backbone=record["backbone"], patches_emb=record["patches_emb"])

    def list_embedding_streams_by_backbone(
        self,
        backbone: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmbeddingStream]:
        """List all embedding streams for a backbone with pagination."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        return [
            EmbeddingStream(backbone=record["backbone"], patches_emb=record["patches_emb"])
            for record in self._embedding_stream_repo.list_by_backbone(backbone, limit=limit, offset=offset)
        ]

    def remove_embedding_streams_for_song(self, song_id: int) -> None:
        """Delete all embedding streams linked to one song."""
        assert self._embedding_stream_repo is not None, "EmbeddingStreamRepository not wired"
        self._embedding_stream_repo.delete_for_song(song_id)

    # ------------------------------------------------------------------
    # Promoted intent-complete write methods
    # ------------------------------------------------------------------

    def replace_song_inference_results(
        self,
        song_id: int,
        backbone: str,
        *,
        vectors: list[dict[str, Any]],
        output_streams: list[OutputStreamWrite],
    ) -> None:
        """Atomically replace a song's output streams and a backbone's vectors.

        Sole live aggregate intent for ML inference persistence. Delegates the
        whole replacement to :class:`MlInferenceRepo`, which owns the transaction.
        No facade-level transaction wrapper is used (AR-SDR-4).

        Output streams are domain commands; row identifiers, song foreign keys,
        timestamps, and table names remain inside persistence. Vector replacement
        is scoped to ``(song_id, backbone)`` so sequentially-persisted backbones
        preserve one another's vectors.

        Args:
            song_id: Song whose output streams are replaced and whose vectors
                (scoped to *backbone*) are replaced.
            backbone: Authoritative backbone identifier scoping vector
                deletion and insertion.
            vectors: Canonical vector payloads
                ``{embedding_vector | embedding, model_id, backbone_id?, genres?}``.
                If ``backbone_id`` is present, it must match ``backbone``;
                otherwise the repository raises ``ValueError`` before mutation.
            output_streams: Domain commands describing the output streams to
                replace.
        """
        assert self._ml_inference_repo is not None, "MlInferenceRepo not wired"
        self._ml_inference_repo.replace_song_inference_results(
            song_id=song_id,
            backbone=backbone,
            vectors=vectors,
            output_streams=[
                {
                    "output_id": stream.output_id,
                    "values": stream.values,
                    "output_index": stream.output_index,
                }
                for stream in output_streams
            ],
        )

    def remove_output_streams_for_song(self, song_id: int) -> int:
        """Delete a song's output streams and return the number removed."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.delete_output_streams_for_song(song_id)

    def remove_song_vectors(self, collection_name: str, song_id: int) -> None:
        """Delete one song's vectors for the requested backbone."""
        assert self._vector_repo is not None, "VectorRepo not wired"
        self._vector_repo.delete_embeddings_for_song(song_id, collection_name)

    def remove_vectors_for_songs(self, collection_name: str, song_ids: list[int]) -> None:
        """Delete each song's vectors for the requested backbone.

        .. note::
           TODO: N+1 — loops ``delete_embeddings_for_song`` per song_id.
           VectorRepo has no batch-delete-by-song-ids method yet.  Add a
           single ``DELETE … WHERE song_id = ANY(…)`` to VectorRepo for
           production scaling.
        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        for sid in song_ids:
            self._vector_repo.delete_embeddings_for_song(sid, collection_name)

    def replace_model_output(
        self,
        model_id: str,
        output_id: str,
        *,
        output_index: int | None = None,
        label: str | None = None,
        fully_labeled: bool = False,
    ) -> ModelOutput:
        """Store one model output vertex and return its domain representation.

        ``output_id`` is the stable output identity from the model registry.
        The caller supplies domain metadata only; the raw ``output_data`` JSONB
        blob, integer primary key, and timestamps stay inside persistence.
        """
        assert self._output_repo is not None, "OutputRepo not wired"
        record = self._output_repo.store_model_output(
            model_id=model_id,
            output_id=output_id,
            # output_data is a legacy JSONB column with no domain meaning; the
            # typed metadata lives in the dedicated output_index/label/fully_labeled columns.
            output_data={},
            output_index=output_index,
            label=label,
            fully_labeled=fully_labeled,
        )
        return model_output_from_record(record)

    def remove_model_output(self, output_id: str) -> None:
        """Delete one model output by stable output identity."""
        assert self._output_repo is not None, "OutputRepo not wired"
        self._output_repo.delete_output(output_id)

    def remove_model_outputs_for_model(self, model_id: str) -> list[str]:
        """Delete all model outputs for one model and return their stable output_ids."""
        assert self._output_repo is not None, "OutputRepo not wired"
        return self._output_repo.delete_outputs_for_model(model_id)

    def list_all_calibration_states_with_models(self) -> list[CalibrationState]:
        """Return calibration states with available owning-model metadata."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        return [calibration_state_from_joined_record(r) for r in self._calibration_repo.list_states_with_models()]

    def replace_calibration_state(self, state: CalibrationState) -> CalibrationState:
        """Create or replace a calibration state using domain semantics."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        record = self._calibration_repo.set_state(state.model_id, state_data=calibration_state_payload(state))
        return calibration_state_from_record(record)

    def remove_calibration_state(self, state: CalibrationState) -> None:
        """Delete a calibration state by stable model/head/label identity."""
        assert self._calibration_repo is not None, "CalibrationRepo not wired"
        self._calibration_repo.delete_state(state.model_id, state.head_name, state.label)

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

    def get_embedding_stats(self, backbone_id: str, library_id: int | None = None) -> dict[str, int]:
        """Return hot_count and cold_count for a backbone, optionally by library."""
        assert self._vector_repo is not None, "VectorRepo not wired"
        if library_id is None:
            return self._vector_repo.get_embedding_stats(backbone_id)
        return self._vector_repo.get_embedding_stats(backbone_id, library_id=library_id)

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
        return self._vector_repo.has_cold_hnsw_index()

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
        self._vector_repo.rebuild_cold_hnsw_index()
        logger.info("Successfully rebuilt cold HNSW index (ix_embeddings_cold_hnsw).")

    def backfill_genres(self, backbone_id: str) -> int:
        """Backfill missing genres on cold embeddings for a backbone.

        Returns:
            Number of embedding rows updated with genre data.

        """
        assert self._vector_repo is not None, "VectorRepo not wired"
        count = self._vector_repo.backfill_genres(backbone_id)
        if count > 0:
            logger.info(
                "backfill_genres: updated %d embeddings for backbone '%s'.",
                count,
                backbone_id,
            )
        return count
