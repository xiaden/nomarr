"""Phase-2 ownership tests for the relocated mood persistence path.

These are static/source architecture tests. They fail if the Tier-3
``LibraryTagsDb`` facade regains mood table/SQL access or transaction control,
if a second mood repository/alias/shim appears, or if the existing Tier-2
``SongTagRepository`` mood intent loses the single marker+mood transaction
guarantee. They also pin the unchanged D3-facing public symbols.

No live PostgreSQL evidence is claimed here; behavioral fault coverage lives in
``test_mood_owner_d2.py`` and real-driver capability evidence is owned by D3.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.database.song_tag_repo import SongTagRepository

_DATABASE_DIR = Path(__file__).resolve().parents[4] / "nomarr" / "persistence" / "database"


def _defines_mood_batch(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == "replace_mood_tags_batch" for node in ast.walk(tree))


def _module_imported_names(module: object) -> set[str]:
    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            imported.add(module_name)
            imported.update(f"{module_name}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


@pytest.mark.unit
class TestFacadeHasNoMoodSqlOrTransactionOwnership:
    def test_facade_mood_methods_contain_no_sql_table_or_transaction_tokens(self) -> None:
        mood_source = inspect.getsource(LibraryTagsDb.replace_mood_tags) + inspect.getsource(
            LibraryTagsDb.replace_mood_tags_batch
        )
        forbidden = (
            "Table",
            "delete(",
            "select(",
            "tuple_(",
            "pg_insert",
            "map_persistence_exceptions",
            "SongMoodCalibrationMarker",
            "SongTag",
            "Tag.__table__",
            ".commit(",
            ".rollback(",
            ".remove(",
            "_replace_mood_batch_once",
            "_commit_mood_batch",
            "_discard_session",
        )
        for token in forbidden:
            assert token not in mood_source, f"facade mood methods must not contain {token!r}"

    def test_facade_module_imports_no_mood_table_or_sql_surface(self) -> None:
        imported = _module_imported_names(inspect.getmodule(LibraryTagsDb))
        forbidden_modules = {
            "nomarr.persistence.models.song_mood_calibration_marker",
            "nomarr.persistence.models.song_tag",
            "nomarr.persistence.models.tag",
            "nomarr.persistence.sql.exceptions",
        }
        assert imported.isdisjoint(forbidden_modules)
        assert not any(name.startswith("sqlalchemy.dialects.postgresql") for name in imported)
        # Generic Core SQL expressions must not be re-imported by the facade.
        assert imported.isdisjoint({"sqlalchemy.Table", "sqlalchemy.delete", "sqlalchemy.select", "sqlalchemy.tuple_"})

    def test_facade_no_longer_owns_private_mood_transaction_internals(self) -> None:
        for name in ("_replace_mood_batch_once", "_commit_mood_batch", "_discard_session"):
            assert not hasattr(LibraryTagsDb, name)

    def test_facade_delegates_the_complete_batch_intent_exactly_once(self) -> None:
        batch_source = inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)
        assert batch_source.count("self._song_tag_repo.replace_mood_tags_batch(") == 1
        assert "_normalize_mood_commands" in batch_source
        assert "_replace_mood_batch_once" not in batch_source
        # No caller-owned transaction or retry surface on the public boundary.
        assert "_discard_session" not in batch_source
        assert "RetryableDatabaseError" not in batch_source
        assert "for attempt" not in batch_source


@pytest.mark.unit
class TestExistingRepositoryOwnsMoodPersistence:
    def test_owner_symbols_live_on_the_existing_song_tag_repository(self) -> None:
        assert inspect.isfunction(SongTagRepository.replace_mood_tags_batch)
        assert inspect.isfunction(SongTagRepository._replace_mood_batch_once)
        assert inspect.isfunction(SongTagRepository._commit_mood_batch)
        assert inspect.isfunction(SongTagRepository._discard_session)
        assert inspect.isfunction(SongTagRepository._resolve_mood_song_ids_map)

    def test_owner_owns_marker_and_mood_sql_in_one_transaction(self) -> None:
        owner = inspect.getsource(SongTagRepository._replace_mood_batch_once)
        # Marker, mood-edge, and tag tables are all reached from the owner.
        assert "_MM" in owner
        assert "_ST" in owner
        assert "_T" in owner
        # Existing UoW-safe tag identity primitive is composed (never a commit).
        assert "self._tag_repo.get_or_create_tags_batch" in owner
        # Exactly one commit point, and it is delegated to the commit-phase method.
        assert owner.count("self._commit_mood_batch()") == 1
        assert "self._session.commit()" not in owner

    def test_commit_phase_classification_is_owned_by_the_repository(self) -> None:
        commit = inspect.getsource(SongTagRepository._commit_mood_batch)
        for token in ('"40001"', '"40P01"', '"55P03"', '"40003"', "AmbiguousCommitError", "DBAPIError"):
            assert token in commit
        retry = inspect.getsource(SongTagRepository.replace_mood_tags_batch)
        assert "range(_MAX_MOOD_TRANSACTION_ATTEMPTS)" in retry
        assert "_discard_session" in retry

    def test_no_second_mood_repository_alias_or_shim(self) -> None:
        assert not (_DATABASE_DIR / "mood_repo.py").exists()
        owners = [path.name for path in sorted(_DATABASE_DIR.glob("*.py")) if _defines_mood_batch(path)]
        assert owners == ["song_tag_repo.py"]


@pytest.mark.unit
class TestUnchangedD3FacingPublicSymbols:
    def test_exact_public_signatures_are_unchanged(self) -> None:
        single = inspect.signature(LibraryTagsDb.replace_mood_tags)
        batch = inspect.signature(LibraryTagsDb.replace_mood_tags_batch)
        assert tuple(single.parameters) == ("self", "song", "assignments", "marker")
        assert tuple(batch.parameters) == ("self", "commands")
        assert "MoodWriteResult" in str(single.return_annotation)
        assert "MoodBatchResult" in str(batch.return_annotation)

    def test_d3_can_exercise_public_apis_without_bypassing_the_repository(self) -> None:
        # The only public mood mutation path delegates to the repository owner,
        # and the facade exposes no session/transaction/retry entry point.
        assert "self._song_tag_repo.replace_mood_tags_batch" in inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)
        for forbidden in ("retry_mood_tags", "begin_mood_transaction", "mood_session"):
            assert not hasattr(LibraryTagsDb, forbidden)


def _executable_source(path: Path) -> str:
    """Return a module's executable tokens with docstrings removed.

    Docstrings are allowed to NAME forbidden mechanisms (to document their
    absence), so a raw substring scan of the file would be self-defeating. This
    collects identifiers, attribute names, function names, and non-docstring
    string constants -- i.e. everything that could actually implement a
    mechanism -- and joins them for a substring check.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstring_values: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_values.add(id(body[0].value))
    parts: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_values:
                parts.append(node.value)
        elif isinstance(node, ast.Name):
            parts.append(node.id)
        elif isinstance(node, ast.Attribute):
            parts.append(node.attr)
        elif isinstance(node, ast.FunctionDef):
            parts.append(node.name)
    return " ".join(parts)


@pytest.mark.unit
class TestSameLocatorSerializationMechanism:
    def test_owner_locks_resolved_songs_rows_for_update(self) -> None:
        owner = inspect.getsource(SongTagRepository._replace_mood_batch_once)
        assert "_lock_mood_song_rows" in owner
        lock = inspect.getsource(SongTagRepository._lock_mood_song_rows)
        assert "with_for_update(key_share=True)" in lock, (
            "row lock must be FOR NO KEY UPDATE (self-conflicting; FK-safe)"
        )
        assert "_S.c.id" in lock
        assert "order_by(" in lock
        assert "sorted(" in lock, "batch lock order must be deterministic (ascending private ids)"

    def test_serialization_uses_row_locks_only(self) -> None:
        executable = _executable_source(_DATABASE_DIR / "song_tag_repo.py")
        assert executable.count("with_for_update") == 1, "the only locking construct is SELECT ... FOR UPDATE"
        for token in (
            "pg_advisory",
            "advisory_lock",
            "lock_table",
            "idempotency",
            "publication_envelope",
            "require_library_song_id",
            "path_to_song_id",
            "resolve_song_identity",
            "resolve_song_identities",
            "mood_repo",
        ):
            assert token not in executable, f"forbidden serialization mechanism {token!r}"

    def test_still_one_owner_and_no_second_mood_module(self) -> None:
        assert not (_DATABASE_DIR / "mood_repo.py").exists()
        owners = [path.name for path in sorted(_DATABASE_DIR.glob("*.py")) if _defines_mood_batch(path)]
        assert owners == ["song_tag_repo.py"]
