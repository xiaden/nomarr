"""MlInferenceRepo — repository-owned aggregate for atomic ML inference persistence.

Per AR-SDR-4, caller-managed transactions are not a domain contract: no facade
or caller opens transactions for ordinary writes. Instead, this repository owns
the single short internal transaction (``begin_nested`` SAVEPOINT + one
``commit``) that atomically replaces a song's canonical output streams and a
backbone's vectors.

The repository is the sole owner of persistence mapping: it resolves a semantic
:class:`SongIdentity` to the storage song row, maps typed
:class:`BackboneVectorWrite` / :class:`OutputStreamWrite` commands onto the
existing ``embeddings`` / ``ml_output_streams`` rows, derives ``embed_dim`` from
the vector, and keeps table names, SQL, and row dictionaries private.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, cast

from sqlalchemy import Table, delete, insert, select

from nomarr.helpers.exceptions import EntityNotFoundError
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.models.song import Song
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStreamWrite
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite

_T_VECTOR = cast("Table", Embedding.__table__)
_T_STREAM = cast("Table", MlOutputStream.__table__)
_T_SONG = cast("Table", Song.__table__)
_T_LIBRARY = cast("Table", Library.__table__)


class MlInferenceRepo:
    """Repository owning the atomic song-inference replacement aggregate."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def replace_song_inference_results(
        self,
        song: SongIdentity,
        backbone: str,
        *,
        vectors: Sequence[BackboneVectorWrite],
        output_streams: Sequence[OutputStreamWrite],
    ) -> None:
        """Atomically replace a song's output streams and a backbone's vectors.

        Resolves *song* to its storage row, then performs both table
        replacements through no-commit internal SQL helpers inside one
        repository-owned ``begin_nested`` boundary, then commits once. Deletes
        only ``(song, backbone)`` vectors and the song's output streams, so
        sequentially-persisted backbones preserve one another's vectors.

        ``output_streams`` are de-duplicated here by ``output_id`` (last
        occurrence within the batch wins, first-appearance order preserved);
        stream rows keep the caller-supplied stable ``output_id`` verbatim. When
        *vectors* is empty and *backbone* is ``""`` the call is a streams-only
        sentinel: it replaces the song's streams but never touches vectors. An
        empty non-``""`` *backbone* with empty vectors clears only that
        backbone's vectors. ``output_streams=[]`` clears the song's streams.

        Args:
            song: Song whose output streams are replaced and whose vectors
                (scoped to *backbone*) are replaced.
            backbone: Authoritative backbone identifier scoping vector
                deletion and insertion.
            vectors: Typed :class:`BackboneVectorWrite` commands; persistence
                derives ``embed_dim`` from ``len(vector)``, maps
                ``model_suite_hash`` to the persisted ``model_id`` column (the
                ``model_suite_hash`` column stays ``""``), and always writes
                ``segmentation_hash=NULL``.
            output_streams: Typed :class:`OutputStreamWrite` commands describing
                the streams to replace.

        Raises:
            EntityNotFoundError: If *song* cannot be resolved to a storage row.
        """
        try:
            with map_persistence_exceptions():
                song_id = self._resolve_song_id(song)
                with self._session.begin_nested():
                    self._delete_vectors_for_song_backbone(song_id, backbone)
                    self._delete_output_streams_for_song(song_id)
                    for stream in self._dedupe_output_streams(output_streams):
                        self._insert_output_stream(song_id, stream)
                    for cmd in vectors:
                        self._insert_vector(song_id, backbone, cmd)
                self._session.commit()
        except BaseException:
            # Neutralize the shared scoped session on ANY failure -- including
            # from _resolve_song_id (the resolve SELECT autobegins the outer
            # transaction), the interior statement helpers, and commit() itself
            # (deferred constraint / connection error). A savepoint-only
            # recovery leaves the autobegun outer transaction open, which can
            # poison this same session for the worker's subsequent
            # errored-transition/release calls. Mirrors the repo_helpers
            # atomic_unit_of_work pattern: roll back the whole unit, then
            # re-raise. The success path still commits exactly once.
            with suppress(BaseException):
                # A rollback that itself fails must not mask the original cause.
                self._session.rollback()
            raise

    # ── no-commit internal SQL helpers ─────────────────────────

    def _resolve_song_id(self, song: SongIdentity) -> int:
        """Resolve a UUID ``SongIdentity`` to its storage song id.

        Matches ``libraries.library_uuid`` (ADR-049) and the song's
        ``normalized_path`` against the storage tables. Persistence-internal:
        never calls the ``db.library`` facade and never exposes the integer id
        upward. Raises :class:`EntityNotFoundError` when the library or song is
        absent.
        """
        library_stmt = select(_T_LIBRARY.c.id).where(
            _T_LIBRARY.c.library_uuid == song.library.library_uuid,
        )
        library_id = self._session.execute(library_stmt).scalar_one_or_none()
        if library_id is None:
            raise EntityNotFoundError(f"Library {song.library.library_uuid!r} not found")
        song_stmt = select(_T_SONG.c.id).where(
            _T_SONG.c.library_id == library_id,
            _T_SONG.c.normalized_path == song.normalized_path,
        )
        song_id = self._session.execute(song_stmt).scalar_one_or_none()
        if song_id is None:
            raise EntityNotFoundError(
                f"Song {song.normalized_path!r} not found in library {song.library.library_uuid!r}"
            )
        return int(song_id)

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

    @staticmethod
    def _dedupe_output_streams(
        streams: Sequence[OutputStreamWrite],
    ) -> list[OutputStreamWrite]:
        """Collapse duplicate ``output_id`` within one batch (last wins, order kept).

        Mirrors the caller-side ``_normalize_streams`` semantics that previously
        de-duplicated before the aggregate reached the repository: the last
        occurrence per ``output_id`` wins and first-appearance batch order is
        preserved, so no batch boundary changes.
        """
        deduped: dict[str, OutputStreamWrite] = {}
        for stream in streams:
            deduped[stream.output_id] = stream
        return list(deduped.values())

    def _insert_output_stream(self, song_id: int, stream: OutputStreamWrite) -> None:
        """Insert one output stream row from a typed command (no commit)."""
        stmt = insert(_T_STREAM).values(
            song_id=song_id,
            output_id=stream.output_id,
            output_index=stream.output_index,
            values=list(stream.values),
            created_at=now_ms().value,
        )
        self._session.execute(stmt)

    def _insert_vector(self, song_id: int, backbone: str, cmd: BackboneVectorWrite) -> None:
        """Insert one embedding row from a typed command (no commit)."""
        now = now_ms().value
        embedding = list(cmd.vector)
        stmt = insert(_T_VECTOR).values(
            song_id=song_id,
            backbone_id=backbone,
            # The semantic suite hash (model_suite_hash) is mapped to the
            # persisted model_id column (preservation oracle); the persisted
            # model_suite_hash column stays "" exactly as the legacy path wrote it.
            model_id=cmd.model_suite_hash,
            embed_dim=len(cmd.vector),
            model_suite_hash="",
            num_segments=cmd.num_segments,
            segmentation_hash=None,
            embedding=embedding,
            genres=list(cmd.genres) if cmd.genres is not None else None,
            tier="hot",
            created_at=now,
            updated_at=now,
        )
        self._session.execute(stmt)
