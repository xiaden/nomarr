"""Unit tests for the vector backbone scope invariant (typed aggregate).

P5-S4 repair: the Phase-2 typed migration (TASK-ml-write-boundary-leaks-storage-
representation-A) removed the per-command ``backbone_id`` from vector payloads and
made ``MlInferenceRepo.replace_song_inference_results`` take a semantic
``SongIdentity`` plus typed ``BackboneVectorWrite`` commands. Under that contract
the aggregate's single ``backbone`` argument is the SOLE vector scope: commands
carry no per-command backbone to match or mismatch, so the legacy "mismatched
backbone is rejected before mutation" path no longer exists. Its coverage is
superseded by (a) the typed facade/worker unit tests that dispatch typed commands
per backbone and (b) real-PostgreSQL backbone-scoped replacement in
``tests/characterization/test_ml_write_typed_aggregate.py``.

Identity resolution (``_resolve_song_id``) is real-DB (characterization scope); it
is stubbed here so the repo-level backbone-scope assertion stays unit-runnable.

QA Round-2 additions drive the REAL ``_resolve_song_id`` negative branches and the
DB-error mapping at the aggregate on a controlled fake session (Findings 2 and 4).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
from nomarr.helpers.exceptions import DatabaseStateError, EntityNotFoundError
from nomarr.persistence.database.ml_inference_repo import MlInferenceRepo

pytestmark = pytest.mark.unit

_SONG = SongIdentity(
    library=LibraryIdentity(library_uuid="2b202d70-24f8-5ecc-8ec9-be6a83da5fd7", name="lib", root_path="/lib"),
    normalized_path="a.mp3",
)


def _repo() -> tuple[MlInferenceRepo, MagicMock]:
    """Build an inference repository with a session that records SQL calls."""
    session = MagicMock()
    session.begin_nested.return_value.__enter__.return_value = session
    repo = MlInferenceRepo(session)
    # Identity resolution needs a real DB; stub it so the scope invariant below is
    # unit-testable (real-PG resolution is exercised in the characterization module).
    repo._resolve_song_id = lambda _song: 1  # type: ignore[method-assign]
    return repo, session


@pytest.mark.parametrize("backbone", ["effnet", "musicnn"])
def test_typed_vector_commands_persist_under_aggregate_backbone_scope(backbone: str) -> None:
    """Typed commands (no per-command backbone) persist under the aggregate's backbone arg."""
    repo, session = _repo()
    command = BackboneVectorWrite(vector=(0.1, 0.2), model_suite_hash="model-1", num_segments=None, genres=None)

    repo.replace_song_inference_results(
        song=_SONG,
        backbone=backbone,
        vectors=[command],
        output_streams=[],
    )

    statement = session.execute.call_args_list[-1].args[0]
    assert statement.compile().params["backbone_id"] == backbone
    session.commit.assert_called_once_with()


def test_typed_vector_commands_carry_no_per_command_backbone() -> None:
    """BackboneVectorWrite exposes no backbone_id, so no mismatch path can be expressed."""
    command = BackboneVectorWrite(vector=(0.1, 0.2), model_suite_hash="model-1", num_segments=None, genres=None)
    # Storage-key absence is pinned by test_vector_dataclass; here it documents that
    # the legacy "declared backbone contradicts aggregate backbone" ValueError is gone.
    assert not hasattr(command, "backbone_id")
    assert not hasattr(command, "embedding_vector")


# ---------------------------------------------------------------------------
# QA Round-2 Findings 2 & 4: real _resolve_song_id branch coverage and DB-error
# translation at the aggregate. These drive the REAL _resolve_song_id against a
# controlled fake session whose execute() returns fixed row sequences, through
# the real aggregate public path so that EntityNotFoundError (deliberate,
# domain-level) is proven to pass through the map_persistence_exceptions context
# unchanged while DB-level OperationalError/ProgrammingError map to
# DatabaseStateError (never propagate raw to callers).
# ---------------------------------------------------------------------------


def _real_resolve_repo() -> tuple[MlInferenceRepo, MagicMock]:
    """Build MlInferenceRepo over a fake session WITHOUT stubbing _resolve_song_id."""
    session = MagicMock()
    session.begin_nested.return_value.__enter__.return_value = session
    session.begin_nested.return_value.__exit__.return_value = False
    return MlInferenceRepo(session), session


def _scalar(value: object) -> MagicMock:
    """A fake execute() result whose scalar_one_or_none() returns *value*."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _replace(repo: MlInferenceRepo, song: SongIdentity) -> None:
    repo.replace_song_inference_results(song=song, backbone="effnet", vectors=[], output_streams=[])


@pytest.mark.unit
class TestResolveSongIdNegativeBranches:
    """Real _resolve_song_id branch coverage (QA Round-2 Finding 4)."""

    def test_unknown_library_uuid_raises_entity_not_found(self) -> None:
        repo, session = _real_resolve_repo()
        # The library UUID does not resolve: SELECT libraries.id returns no row.
        session.execute.side_effect = [_scalar(None)]
        with pytest.raises(EntityNotFoundError, match=r"Library .* not found"):
            _replace(repo, _SONG)

    def test_absent_library_raises_entity_not_found(self) -> None:
        repo, session = _real_resolve_repo()
        # First execute (SELECT libraries.id) returns no library row.
        session.execute.side_effect = [_scalar(None)]
        with pytest.raises(EntityNotFoundError, match=r"Library .* not found"):
            _replace(repo, _SONG)

    def test_absent_song_raises_entity_not_found(self) -> None:
        repo, session = _real_resolve_repo()
        # Library present (id 5), then SELECT songs.id returns no song row.
        session.execute.side_effect = [_scalar(5), _scalar(None)]
        with pytest.raises(EntityNotFoundError, match=r"Song 'a\.mp3' not found"):
            _replace(repo, _SONG)


@pytest.mark.unit
class TestResolveDbErrorMapping:
    """DB-level failures during identity resolution map like the rest of the aggregate.

    QA Round-2 Finding 2 moved _resolve_song_id INSIDE the
    map_persistence_exceptions context in replace_song_inference_results; these
    tests pin that OperationalError/ProgrammingError raised by the resolve
    SELECTs surface as DatabaseStateError (never raw) while the deliberate
    EntityNotFoundError negatives in TestResolveSongIdNegativeBranches above pass
    through unchanged (map_persistence_exceptions only translates DB exceptions).
    """

    def test_operational_error_during_library_resolve_maps_to_database_state_error(self) -> None:
        repo, _ = _real_resolve_repo()
        repo._session.execute.side_effect = OperationalError("select libraries", params=None, orig=MagicMock())
        with pytest.raises(DatabaseStateError, match="Database operational error"):
            repo.replace_song_inference_results(song=_SONG, backbone="effnet", vectors=[], output_streams=[])

    def test_operational_error_during_song_resolve_maps_to_database_state_error(self) -> None:
        repo, session = _real_resolve_repo()
        # Library SELECT succeeds (id 5); song SELECT hits a connection loss.
        session.execute.side_effect = [_scalar(5), OperationalError("select songs", params=None, orig=MagicMock())]
        with pytest.raises(DatabaseStateError, match="Database operational error"):
            repo.replace_song_inference_results(song=_SONG, backbone="effnet", vectors=[], output_streams=[])

    def test_programming_error_during_resolve_maps_to_database_state_error(self) -> None:
        repo, _ = _real_resolve_repo()
        repo._session.execute.side_effect = ProgrammingError("bad identifier", params=None, orig=MagicMock())
        with pytest.raises(DatabaseStateError, match="Database programming error"):
            repo.replace_song_inference_results(song=_SONG, backbone="effnet", vectors=[], output_streams=[])

    def test_entity_not_found_is_not_replaced_by_database_state_error(self) -> None:
        # Guards the Finding-2 placement invariant from the opposite direction:
        # the deliberate EntityNotFoundError from _resolve_song_id must surface as
        # itself (EntityNotFoundError) — never as a mapped DatabaseStateError —
        # even though resolve now runs inside the exception-mapping context.
        repo, session = _real_resolve_repo()
        session.execute.side_effect = [_scalar(None)]  # absent library
        with pytest.raises(EntityNotFoundError):
            repo.replace_song_inference_results(song=_SONG, backbone="effnet", vectors=[], output_streams=[])


# ---------------------------------------------------------------------------
# QA Round-3 Finding: outer rollback guard on a mutation-block failure. The
# aggregate wraps identity resolution + the begin_nested() mutation block + the
# commit() inside map_persistence_exceptions and, on ANY failure, rolls back the
# WHOLE outer session (mirroring the repo_helpers atomic_unit_of_work pattern)
# then re-raises. Existing scope tests pin the success path (commit exactly
# once) and resolve-phase DB-error mapping; this pins that a failure INSIDE the
# mutation block (after resolve succeeds) rolls back the outer session exactly
# once and never commits — so a mutable failure cannot leave the shared scoped
# session in a poisoned open transaction.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMutationBlockErrorRollsBackOuterSession:
    def test_db_error_inside_mutation_rolls_back_outer_and_never_commits(self) -> None:
        # The real aggregate runs through self._session.execute for both the two
        # resolve SELECTs and the no-commit interior SQL helpers (delete/insert).
        # Resolve succeeds (library id 5, song id 1); the FIRST mutation
        # statement (_delete_vectors_for_song_backbone) raises a DB error, so the
        # failure is inside the begin_nested() block, after commit() was not yet
        # reached. The aggregate must map it to DatabaseStateError, roll back the
        # outer session once, and never commit.
        repo, session = _real_resolve_repo()
        session.execute.side_effect = [
            _scalar(5),
            _scalar(1),
            OperationalError("delete embeddings", params=None, orig=MagicMock()),
        ]
        with pytest.raises(DatabaseStateError, match="Database operational error"):
            repo.replace_song_inference_results(song=_SONG, backbone="effnet", vectors=[], output_streams=[])
        session.rollback.assert_called_once_with()
        session.commit.assert_not_called()
