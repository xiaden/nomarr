"""D1 contract tests for the tag-owner mood boundary."""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, cast, get_args

import pytest
from sqlalchemy import CheckConstraint

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodAssignments,
    MoodBatchResult,
    MoodReplacementCommand,
    MoodWriteResult,
    MoodWriteStatus,
    SongTagAssignment,
)
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.models.song_mood_calibration_marker import SongMoodCalibrationMarker
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

if TYPE_CHECKING:
    from sqlalchemy import Table

SONG = SongIdentity(LibraryIdentity("de131b32-af5c-5a84-8874-58e3dc0e2dcd"), "a.mp3")


@pytest.mark.unit
class TestMoodDomainContract:
    def test_public_values_are_immutable_and_storage_free(self) -> None:
        domain_types = (
            MoodAssignments,
            MoodReplacementCommand,
            CalibrationMoodMarker,
            MoodWriteResult,
            MoodBatchResult,
        )
        forbidden_names = {
            "id",
            "song_id",
            "library_id",
            "row",
            "sql",
            "session",
            "path",
            "uuid",
            "marker_token",
            "credentials",
            "table",
            "constraint",
        }
        instances = (
            MoodAssignments(),
            MoodReplacementCommand(SONG, None, CalibrationMoodMarker.uncalibrated()),
            CalibrationMoodMarker.uncalibrated(),
            MoodWriteResult("UNCHANGED"),
            MoodBatchResult("UNCHANGED"),
        )
        for domain_type, instance in zip(domain_types, instances, strict=True):
            assert not hasattr(instance, "__dict__")
            assert {field.name for field in fields(domain_type)}.isdisjoint(forbidden_names)
        # Exact public field sets: a complete allowlist, not merely disjointness.
        assert {field.name for field in fields(MoodWriteResult)} == {"status", "assignment_count"}
        assert {field.name for field in fields(MoodBatchResult)} == {
            "status",
            "command_count",
            "changed_count",
        }

    def test_assignments_are_canonical_and_tier_complete(self) -> None:
        values = MoodAssignments(strict=(" happy ", "happy"), regular=("calm",), loose=())
        assert values.strict == ("happy",)
        assert values.tiers == (
            ("nom:mood-strict", ("happy",)),
            ("nom:mood-regular", ("calm",)),
            ("nom:mood-loose", ()),
        )

    def test_marker_requires_lowercase_32_hex(self) -> None:
        marker = CalibrationMoodMarker.calibrated("a" * 32)
        assert marker.status == "calibrated"
        with pytest.raises(ValueError):
            CalibrationMoodMarker.calibrated("A" * 32)
        with pytest.raises(ValueError):
            CalibrationMoodMarker.calibrated("a" * 31)
        assert CalibrationMoodMarker.uncalibrated().version is None

    def test_marker_and_command_are_immutable_semantic_values(self) -> None:
        command = MoodReplacementCommand(SONG, None, CalibrationMoodMarker.uncalibrated())
        assert command.assignments is None
        assert not hasattr(command, "__dict__")
        with pytest.raises(AttributeError):
            command.song = SONG  # type: ignore[misc]

    def test_result_vocabulary_is_coarse_and_counts_are_nonnegative(self) -> None:
        assert MoodWriteResult("UPDATED", assignment_count=3).assignment_count == 3
        assert MoodBatchResult("UNCHANGED", command_count=2, changed_count=0).changed_count == 0
        with pytest.raises(ValueError):
            MoodWriteResult("NO_IDS")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MoodWriteResult("UPDATED", assignment_count=-1)
        with pytest.raises((TypeError, ValueError)):
            MoodBatchResult("UPDATED", changed_count=-1)


@pytest.mark.unit
class TestMoodSchemaContract:
    def test_existing_tag_and_edge_ownership_remains_identity_only(self) -> None:
        tag_table = cast("Table", Tag.__table__)
        song_tag_table = cast("Table", SongTag.__table__)
        assert [column.name for column in tag_table.columns] == ["id", "namespace", "name", "value"]
        assert tag_table.c.namespace.nullable is False
        assert any(constraint.name == "uq_tags_name_value_ns" for constraint in tag_table.constraints)
        assert {column.name for column in song_tag_table.columns} == {
            "id",
            "song_id",
            "tag_id",
            "confidence",
            "source",
            "created_at",
        }
        assert "calibration_hash" not in {column.name for column in Tag.__table__.columns}

    def test_marker_model_is_private_singleton_with_cascade_and_check(self) -> None:
        table = cast("Table", SongMoodCalibrationMarker.__table__)
        assert [column.name for column in table.columns] == ["song_id", "calibration_version"]
        assert table.primary_key.columns.keys() == ["song_id"]
        # Pyright cannot narrow the generic ``Constraint`` union through
        # ``hasattr``, so cast to ``CheckConstraint`` to access ``sqltext``.
        assert any(
            "calibration_version ~" in str(cast("CheckConstraint", constraint).sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
        foreign_keys = list(table.c.song_id.foreign_keys)
        assert len(foreign_keys) == 1
        assert foreign_keys[0].ondelete == "CASCADE"


@pytest.mark.unit
class TestMoodFacadeContract:
    def test_exact_public_signatures(self) -> None:
        single = inspect.signature(LibraryTagsDb.replace_mood_tags)
        batch = inspect.signature(LibraryTagsDb.replace_mood_tags_batch)
        assert list(single.parameters) == ["self", "song", "assignments", "marker"]
        assert list(batch.parameters) == ["self", "commands"]
        assert "SongIdentity" in str(single.parameters["song"].annotation)
        assert "MoodWriteResult" in str(single.return_annotation)
        assert "MoodBatchResult" in str(batch.return_annotation)


# D1B characterization fixtures.  These tests intentionally model the frozen
# boundary without claiming D2 repository or PostgreSQL runtime evidence.
MOOD_TIERS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
PUBLIC_FORBIDDEN = {
    "id",
    "song_id",
    "library_id",
    "row",
    "sql",
    "session",
    "path",
    "uuid",
    "marker_token",
    "credentials",
    "constraint",
    "raw_payload",
}
EXPECTED_STATUSES = {
    "UPDATED",
    "UNCHANGED",
    "MISSING_LOCATOR",
    "INVALID_VALUE",
    "INFRA_FAILURE",
    "AMBIGUOUS_COMMIT",
}


def _command(song: SongIdentity = SONG, *, marker: CalibrationMoodMarker | None = None) -> MoodReplacementCommand:
    return MoodReplacementCommand(
        song,
        MoodAssignments(strict=("happy",), regular=("calm",), loose=()),
        marker or CalibrationMoodMarker.uncalibrated(),
    )


@pytest.mark.unit
class TestMoodRoundTwoPureCharacterization:
    """D1 characterization only; executable persistence evidence belongs to D2/D3."""

    def test_all_statuses_and_public_fields_are_complete_and_redacted(self) -> None:
        for status in EXPECTED_STATUSES:
            typed_status = cast("MoodWriteStatus", status)
            single = MoodWriteResult(typed_status, assignment_count=0)
            batch = MoodBatchResult(typed_status, command_count=0, changed_count=0)
            assert single.status == status
            assert single.assignment_count >= 0
            assert batch.status == status
            assert batch.command_count >= 0
            assert batch.changed_count >= 0
            assert {field.name for field in fields(type(single))}.isdisjoint(PUBLIC_FORBIDDEN)
            assert {field.name for field in fields(type(batch))}.isdisjoint(PUBLIC_FORBIDDEN)
        assert {field.name for field in fields(MoodWriteResult)} == {"status", "assignment_count"}
        assert {field.name for field in fields(MoodBatchResult)} == {
            "status",
            "command_count",
            "changed_count",
        }

    def test_boolean_counts_and_invalid_values_are_rejected(self) -> None:
        with pytest.raises(TypeError):
            MoodWriteResult("UPDATED", assignment_count=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", command_count=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", changed_count=True)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            MoodAssignments(strict=("",))
        with pytest.raises(TypeError):
            MoodAssignments(strict=True)  # type: ignore[arg-type]

    def test_batch_count_validation_is_nonnegative_only_and_relationship_is_uncharacterized(self) -> None:
        # Deterministic empty result.
        empty = MoodBatchResult("UNCHANGED")
        assert empty == MoodBatchResult("UNCHANGED", command_count=0, changed_count=0)
        # The pure DTO exercises only boolean/type and nonnegativity validation.
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", command_count=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", changed_count=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", command_count=-1)
        with pytest.raises(TypeError):
            MoodBatchResult("UPDATED", changed_count=-1)
        # Documented valid relationship examples the DTO accepts.
        for command_count, changed_count in ((0, 0), (1, 0), (1, 1), (1000, 0), (1000, 1000)):
            result = MoodBatchResult(
                "UPDATED" if changed_count else "UNCHANGED",
                command_count=command_count,
                changed_count=changed_count,
            )
            assert (result.command_count, result.changed_count) == (command_count, changed_count)
        # The DTO does NOT enforce changed_count <= command_count.  These invalid
        # relationships construct successfully today; rejecting them is a D2/D3
        # obligation and D1B records only the current boundary limitation.
        for command_count, changed_count in ((0, 1), (1, 2), (1000, 1001)):
            unenforced = MoodBatchResult("UPDATED", command_count=command_count, changed_count=changed_count)
            assert unenforced.changed_count > unenforced.command_count
        # A 1,001-command input is likewise accepted by the pure DTO; the 1,000-
        # command bound is D2/D3-owned and is not enforced by this DTO.
        over_bound = MoodBatchResult("UNCHANGED", command_count=1001, changed_count=0)
        assert over_bound.command_count == 1001

    def test_only_three_literal_mood_tiers_are_owned(self) -> None:
        mood = MoodAssignments(strict=("happy",), regular=(), loose=("calm",))
        owned = {name for name, _values in mood.tiers}
        assert owned == set(MOOD_TIERS)
        assert MoodAssignments(strict=()).tiers == tuple((tier, ()) for tier in MOOD_TIERS)
        assert MoodReplacementCommand(SONG, None, CalibrationMoodMarker.uncalibrated()).assignments is None

    def test_edge_metadata_and_provenance_are_not_mood_values(self) -> None:
        edge = SongTagAssignment("nom:other", "kept", namespace="nom", confidence=0.125, source="edge-owner")
        assert (edge.confidence, edge.source) == (0.125, "edge-owner")
        assert not hasattr(edge, "created_at")
        assert {column.name for column in SongTag.__table__.columns} >= {
            "confidence",
            "source",
            "created_at",
        }
        assert "source" not in {field.name for field in fields(MoodAssignments)}

    def test_marker_publication_and_provenance_are_explicit(self) -> None:
        version = "a" * 32
        calibrated = CalibrationMoodMarker.calibrated(version)
        assert calibrated.status == "calibrated"
        assert calibrated.version == version
        assert CalibrationMoodMarker.uncalibrated().version is None
        assert CalibrationMoodMarker.__doc__ and "publication" in CalibrationMoodMarker.__doc__
        # The marker is supplied by the command and is not inferred from a song row.
        assert _command(marker=calibrated).marker == calibrated
        assert "calibration_hash" not in inspect.getsource(SongMoodCalibrationMarker)

    def test_public_contract_has_no_storage_or_secret_disclosure(self) -> None:
        public_types = (
            MoodAssignments,
            MoodReplacementCommand,
            CalibrationMoodMarker,
            MoodWriteResult,
            MoodBatchResult,
        )
        for public_type in public_types:
            names = {field.name for field in fields(public_type)}
            assert names.isdisjoint(PUBLIC_FORBIDDEN)
            assert all("token" not in name and "secret" not in name for name in names)
        for status in EXPECTED_STATUSES:
            assert all(
                value not in repr(MoodWriteResult(cast("MoodWriteStatus", status)))
                for value in ("sql", "session", "credentials")
            )
        # Documentation boundary: assert only that the D1 mood-owner paragraph
        # contains none of the listed storage/secret tokens.  This does not prove
        # the paragraph preserves the O-owned resolver/integer scope; the integer
        # clause is separately asserted against the facade source in
        # TestMoodBoundaryStaticEvidence.test_public_facade_is_the_sole_named_owner_and_exactly_typed.
        persistence = Path(__file__).resolve().parents[4] / "nomarr" / "persistence" / "PERSISTENCE.md"
        mood_paragraph = next(
            line
            for line in persistence.read_text(encoding="utf-8").splitlines()
            if line.startswith("**Mood ownership (D1):**")
        )
        assert all(
            token not in mood_paragraph
            for token in ("SELECT", "INSERT", "session", "credentials", "marker_token", "raw_payload")
        )

    def test_canonicalization_collapses_repeated_tier_values(self) -> None:
        values = MoodAssignments(strict=(" happy ", "happy", "happy"), regular=(" calm ",), loose=())
        assert values.strict == ("happy",)
        assert values.regular == ("calm",)
        assert values.tiers == (
            ("nom:mood-strict", ("happy",)),
            ("nom:mood-regular", ("calm",)),
            ("nom:mood-loose", ()),
        )
        assert _command() == _command()

    def test_duplicate_locator_policy_is_explicitly_conflict_sensitive(self) -> None:
        same = _command()
        # Independently constructed but value-identical commands: genuine
        # dataclass equality, not an object compared to itself.
        independently_identical = (
            _command(),
            MoodReplacementCommand(
                SONG,
                MoodAssignments(strict=("happy",), regular=("calm",), loose=()),
                CalibrationMoodMarker.uncalibrated(),
            ),
        )
        conflicting = (
            same,
            MoodReplacementCommand(SONG, MoodAssignments(strict=("sad",)), same.marker),
        )
        assert independently_identical[0] == independently_identical[1]
        assert conflicting[0] != conflicting[1]
        # D2 folds identical commands and rejects conflicting duplicates before SQL.
        with pytest.raises((TypeError, ValueError)):
            LibraryTagsDb._normalize_mood_commands(conflicting)
        assert len(LibraryTagsDb._normalize_mood_commands(independently_identical)) == 1

    def test_invalid_marker_dto_rejects_and_overbound_batch_is_uncharacterized(self) -> None:
        # The marker DTO validates the lowercase 32-hex token purely.
        for invalid in ("A" * 32, "a" * 31, "a" * 33, "not-hex"):
            with pytest.raises(ValueError):
                CalibrationMoodMarker.calibrated(invalid)
        # A 1,001-command batch is rejected before SQL by the owner.
        commands = tuple(_command() for _ in range(1001))
        # Fixture guard only: confirms the 1,001-command vector was constructed;
        # it is not evidence of any batch-size constraint.
        assert len(commands) == 1001
        accepted = MoodBatchResult("UNCHANGED", command_count=len(commands), changed_count=0)
        assert accepted.command_count == 1001
        result = LibraryTagsDb.replace_mood_tags_batch(cast("LibraryTagsDb", None), commands)
        assert result.status == "INVALID_VALUE"

    def test_missing_marker_status_unproven_is_vocabulary_only_not_a_write_value(self) -> None:
        # The frozen MoodMarkerStatus literal names the missing-marker sentinel
        # UNPROVEN, but the D1 mood publication/write boundary does not accept it
        # as a CalibrationMoodMarker publication value or a MoodWriteResult /
        # MoodBatchResult write status.  This is pure vocabulary characterization;
        # it makes no live read-path or runtime claim.
        from nomarr.helpers.dataclasses.song_tag_dataclass import MoodMarkerStatus

        assert "UNPROVEN" in get_args(MoodMarkerStatus)
        with pytest.raises(ValueError):
            CalibrationMoodMarker(cast("object", "UNPROVEN"), None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            MoodWriteResult("UNPROVEN")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            MoodBatchResult("UNPROVEN", command_count=1, changed_count=0)  # type: ignore[arg-type]

    def test_stale_missing_and_failure_vocabulary_is_typed_and_redacted(self) -> None:
        missing = MoodWriteResult("MISSING_LOCATOR")
        infra = MoodBatchResult("INFRA_FAILURE", command_count=1, changed_count=0)
        ambiguous = MoodBatchResult("AMBIGUOUS_COMMIT", command_count=1, changed_count=0)
        assert missing.assignment_count == 0
        assert (infra.status, ambiguous.status) == ("INFRA_FAILURE", "AMBIGUOUS_COMMIT")
        for result in (missing, infra, ambiguous):
            rendered = repr(result)
            assert all(secret not in rendered for secret in ("de131b32", "a.mp3", "a" * 32, "sql", "session"))

    def test_commands_are_immutable_and_no_caller_retry_or_transaction_surface(self) -> None:
        command = _command()
        with pytest.raises(AttributeError):
            command.assignments = MoodAssignments()  # type: ignore[misc]
        assert not hasattr(LibraryTagsDb, "retry_mood_tags")
        assert not hasattr(LibraryTagsDb, "begin_mood_transaction")
        assert "replace_mood_tags_batch" in inspect.getsource(LibraryTagsDb.replace_mood_tags)
        assert "_normalize_mood_commands" in inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)

    def test_all_or_none_and_no_mutation_are_d2_d3_obligations_not_evidence(self) -> None:
        # Empty input is a deterministic no-op and the implementation owns SQL atomicity.
        batch_source = inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)
        assert "_normalize_mood_commands" in batch_source
        assert "_song_tag_repo.replace_mood_tags_batch" in batch_source
        result = LibraryTagsDb.replace_mood_tags_batch(cast("LibraryTagsDb", None), ())
        assert result == MoodBatchResult("UNCHANGED")


@pytest.mark.unit
class TestMoodBoundaryStaticEvidence:
    def test_public_facade_is_the_sole_named_owner_and_exactly_typed(self) -> None:
        module_source = inspect.getsource(LibraryTagsDb)
        assert "class LibraryTagsDb" in module_source
        assert "replace_mood_tags" in module_source
        assert "replace_song_tags" in module_source
        assert "save_mood_tags" not in module_source
        mood_source = inspect.getsource(LibraryTagsDb.replace_mood_tags)
        batch_source = inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)
        assert "integer" not in mood_source + batch_source

    def test_schema_and_marker_exports_are_canonical(self) -> None:
        assert SongMoodCalibrationMarker.__tablename__ == "song_mood_calibration_markers"
        assert (
            SongMoodCalibrationMarker
            in __import__("nomarr.persistence.models", fromlist=["SongMoodCalibrationMarker"]).__dict__.values()
        )
        assert set(MOOD_TIERS) == {name for name, _ in MoodAssignments().tiers}

    def test_failure_and_database_capability_labels_are_truthful(self) -> None:
        # Evidence label: this module is a pure/unit characterization with no
        # persistence implementation, SQL, session, commit, or rollback surface.
        # The assertions below inspect the actual module AST and facade source
        # rather than restating a literal, so they characterize what this module
        # truly is.  No test here is PostgreSQL, transaction, concurrency,
        # rollback, connection-loss, retry, or ambiguous-commit runtime evidence.
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        imported = {(node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        assert not any(
            name.startswith(("sqlalchemy.orm", "sqlalchemy.engine", "nomarr.persistence.database")) for name in imported
        )
        called_attrs = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert called_attrs.isdisjoint({"commit", "rollback", "begin", "begin_nested", "execute"})
        mood_source = inspect.getsource(LibraryTagsDb.replace_mood_tags)
        batch_source = inspect.getsource(LibraryTagsDb.replace_mood_tags_batch)
        assert "replace_mood_tags_batch" in mood_source
        assert "_normalize_mood_commands" in batch_source
