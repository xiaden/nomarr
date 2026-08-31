"""MlInferenceRepo — repository-owned aggregate for atomic ML inference persistence.

Per AR-SDR-4, caller-managed transactions are not a domain contract: no facade
or caller opens transactions for ordinary writes. Instead, this repository owns
the single short internal transaction (``begin_nested`` SAVEPOINT + one
``commit``) that atomically replaces a song's canonical output streams and a
backbone's vectors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, insert

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

_T_VECTOR = cast("Table", Embedding.__table__)
_T_STREAM = cast("Table", MlOutputStream.__table__)


class MlInferenceRepo:
    """Repository owning the atomic song-inference replacement aggregate."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def replace_song_inference_results(
        self,
        song_id: int,
        backbone: str,
        *,
        vectors: list[dict[str, Any]],
        output_streams: list[dict[str, Any]],
    ) -> None:
        """Atomically replace a song's output streams and a backbone's vectors.

        Performs both table replacements through no-commit internal SQL helpers
        inside one repository-owned ``begin_nested`` boundary, then commits
        once. Deletes only ``(song_id, backbone)`` vectors and ``song_id``
        output streams, so sequentially-persisted backbones preserve one
        another's vectors.

        Args:
            song_id: Song whose output streams are replaced and whose vectors
                (scoped to *backbone*) are replaced.
            backbone: Authoritative backbone identifier scoping vector
                deletion and insertion.
            vectors: Canonical vector payloads
                ``{embedding_vector | embedding, model_id, backbone_id?, genres?}``.
                If ``backbone_id`` is present, it must match ``backbone``;
                otherwise this method raises ``ValueError`` before mutation.
            output_streams: Canonical stream payloads
                ``{output_id, values, output_index?}``.

        """
        self._validate_vector_backbones(backbone, vectors)
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._delete_vectors_for_song_backbone(song_id, backbone)
                self._delete_output_streams_for_song(song_id)
                for payload in output_streams:
                    self._insert_output_stream(song_id, payload)
                for payload in vectors:
                    self._insert_vector(song_id, backbone, payload)
            self._session.commit()

    @staticmethod
    def _validate_vector_backbones(backbone: str, vectors: list[dict[str, Any]]) -> None:
        """Reject vector payloads that contradict the aggregate backbone scope."""
        for payload in vectors:
            if "backbone_id" in payload and payload["backbone_id"] != backbone:
                raise ValueError(
                    "Vector payload backbone_id does not match aggregate backbone: "
                    f"{payload['backbone_id']!r} != {backbone!r}"
                )

    # ── no-commit internal SQL helpers ─────────────────────────

    def _delete_vectors_for_song_backbone(self, song_id: int, backbone: str) -> None:
        """Delete only the ``(song_id, backbone)`` vector scope (no commit)."""
        stmt = delete(_T_VECTOR).where(
            _T_VECTOR.c.song_id == song_id,
            _T_VECTOR.c.backbone_id == backbone,
        )
        self._session.execute(stmt)

    def _delete_output_streams_for_song(self, song_id: int) -> None:
        """Delete all output streams for one song (no commit)."""
        stmt = delete(_T_STREAM).where(_T_STREAM.c.song_id == song_id)
        self._session.execute(stmt)

    def _insert_output_stream(self, song_id: int, payload: dict[str, Any]) -> None:
        """Insert one canonical output stream row (no commit)."""
        stmt = insert(_T_STREAM).values(
            song_id=song_id,
            output_id=payload["output_id"],
            output_index=payload.get("output_index"),
            values=payload["values"],
            created_at=now_ms().value,
        )
        self._session.execute(stmt)

    def _insert_vector(self, song_id: int, backbone: str, payload: dict[str, Any]) -> None:
        """Insert one embedding row scoped to ``(song_id, backbone)`` (no commit)."""
        embedding_vector = payload.get("embedding_vector")
        if embedding_vector is None:
            embedding_vector = payload["embedding"]
        now = now_ms().value
        stmt = insert(_T_VECTOR).values(
            song_id=song_id,
            backbone_id=backbone,
            model_id=payload["model_id"],
            embed_dim=len(embedding_vector),
            # The canonical vector payload carries the model suite hash in
            # ``model_id`` (see ml_vector_persist_comp.build_backbone_vector_payload),
            # so ``model_suite_hash`` stays empty unless a payload supplies the key.
            model_suite_hash=payload.get("model_suite_hash", ""),
            num_segments=payload.get("num_segments"),
            segmentation_hash=None,
            embedding=embedding_vector,
            genres=payload.get("genres"),
            tier="hot",
            created_at=now,
            updated_at=now,
        )
        self._session.execute(stmt)
