"""Tests for library path reconciliation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.reconcile_paths_comp import reconcile_library_paths
from nomarr.components.library.song_query_types import HydratedSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_dataclass import Song


def _hydrated(path: str) -> HydratedSong:
    """Build the semantic ``HydratedSong`` a paged library read returns."""
    return HydratedSong(
        song=Song(
            path=path,
            normalized_path=path.lstrip("/"),
            file_size=0,
            modified_time=0,
            duration_seconds=None,
            chromaprint=None,
            needs_tagging=False,
            is_valid=True,
            tagged=False,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=None,
            created_at=0,
        ),
        metadata={},
    )


@pytest.mark.unit
def test_delete_policy_deletes_only_config_semantic_invalid_rows() -> None:
    """Rows shifted into a page by deletion must still be reconciled."""
    db = MagicMock()
    library = Library(name="Test Library", root_path="/music")
    rows = [
        _hydrated("/invalid/one"),
        _hydrated("/invalid/two"),
        _hydrated("/valid"),
    ]
    offsets: list[int] = []

    def list_rows(_db: object, *, library: Library, limit: int, offset: int) -> tuple[list[HydratedSong], int]:
        del library, limit
        offsets.append(offset)
        return rows[offset : offset + 2], len(rows)

    def remove_song(path: str, _library: Library) -> None:
        rows[:] = [row for row in rows if row.song.path != path]

    db.library.remove_song_by_path.side_effect = remove_song

    def build_path(*, stored_path: str, **_kwargs: object) -> SimpleNamespace:
        if stored_path.startswith("/invalid"):
            return SimpleNamespace(
                status="invalid_config", reason="invalid config", fs_fact=None, is_valid=lambda: False
            )
        return SimpleNamespace(status="valid", reason=None, fs_fact=None, is_valid=lambda: True)

    with (
        patch(
            "nomarr.components.library.reconcile_paths_comp.get_library_stats",
            return_value={"total_files": 3},
        ),
        patch(
            "nomarr.components.library.reconcile_paths_comp.list_songs",
            side_effect=list_rows,
        ),
        patch(
            "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
            side_effect=build_path,
        ),
    ):
        result = reconcile_library_paths(db, library=library, policy="delete_invalid", batch_size=2)

    assert result["total_files"] == 3
    assert result["invalid_config"] == 2
    assert result["deleted_files"] == 2
    assert result["valid_files"] == 1
    assert offsets == [0, 0, 1]
    assert [row.song.path for row in rows] == ["/valid"]


@pytest.mark.unit
@pytest.mark.mocked
@pytest.mark.parametrize(
    "library_path",
    [
        *[
            SimpleNamespace(
                status="unknown",
                reason=kind,
                fs_fact=SimpleNamespace(kind=kind, presence="unknown"),
                is_valid=lambda: False,
            )
            for kind in (
                "resource_missing",
                "unconfirmed_missing",
                "permission_denied",
                "storage_unavailable",
                "transient_io",
                "storage_full",
                "read_only_fs",
                "invalid_path",
                "wrong_resource_type",
                "unknown",
            )
        ],
        SimpleNamespace(status="not_found", reason="missing", fs_fact=None, is_valid=lambda: False),
        SimpleNamespace(
            status="unknown",
            reason="absent",
            fs_fact=SimpleNamespace(kind="resource_missing", presence="absent"),
            is_valid=lambda: False,
        ),
        SimpleNamespace(
            status="invalid_config",
            reason="not a supported audio file format",
            fs_fact=SimpleNamespace(kind="resource_missing", presence="absent"),
            is_valid=lambda: False,
        ),
        SimpleNamespace(
            status="invalid_config",
            reason="path no longer within library root",
            fs_fact=SimpleNamespace(kind=None, presence="present"),
            is_valid=lambda: False,
        ),
        SimpleNamespace(
            status="valid", reason=None, fs_fact=SimpleNamespace(kind=None, presence="present"), is_valid=lambda: True
        ),
    ],
)
def test_delete_invalid_refuses_every_filesystem_derived_or_inconclusive_fact(library_path: SimpleNamespace) -> None:
    """Filesystem facts and legacy not-found statuses never authorize deletion.

    The destructive gate is the conjunction ``status == "invalid_config"`` **and**
    ``fs_fact is None``: a config/semantic classification that carries any filesystem
    fact (a probe or an error, absent or present) must be preserved too.
    """
    db = MagicMock()
    library = Library(name="Test Library", root_path="/music")
    row = _hydrated("/candidate")
    rows = [row]
    db.library.remove_song_by_path.side_effect = AssertionError("must not delete")

    calls = 0

    def list_rows(_db: object, *, library: Library, limit: int, offset: int) -> tuple[list[HydratedSong], int]:
        nonlocal calls
        del _db, library, limit, offset
        calls += 1
        return (rows, len(rows)) if calls == 1 else ([], 0)

    with (
        patch("nomarr.components.library.reconcile_paths_comp.get_library_stats", return_value={"total_files": 1}),
        patch("nomarr.components.library.reconcile_paths_comp.list_songs", side_effect=list_rows),
        patch("nomarr.components.library.reconcile_paths_comp.build_library_path_from_db", return_value=library_path),
    ):
        result = reconcile_library_paths(db, library=library, policy="delete_invalid", batch_size=2)

    assert result["deleted_files"] == 0
    db.library.remove_song_by_path.assert_not_called()
    assert rows == [row]
    key = (
        "not_found"
        if library_path.status == "not_found"
        else "invalid_config"
        if library_path.status == "invalid_config"
        else "valid_files"
        if library_path.is_valid()
        else "unknown_status"
    )
    assert result[key] == 1


@pytest.mark.unit
@pytest.mark.mocked
@pytest.mark.parametrize("policy", ["dry_run", "mark_invalid"])
def test_non_destructive_policies_never_delete_invalid_rows(policy: str) -> None:
    """``dry_run`` and ``mark_invalid`` report invalid paths without ever deleting them.

    These are the non-destructive policies on the narrowed deletion-authority surface:
    regardless of the invalid status, neither policy may reach ``remove_song_by_path``,
    and the rows and class counters are preserved.
    """
    db = MagicMock()
    library = Library(name="Test Library", root_path="/music")
    rows = [_hydrated("/invalid/config"), _hydrated("/missing/file")]
    db.library.remove_song_by_path.side_effect = AssertionError("must not delete")

    calls = 0

    def list_rows(_db: object, *, library: Library, limit: int, offset: int) -> tuple[list[HydratedSong], int]:
        nonlocal calls
        del _db, library, limit, offset
        calls += 1
        return (rows, len(rows)) if calls == 1 else ([], 0)

    def build_path(*, stored_path: str, **_kwargs: object) -> SimpleNamespace:
        if stored_path == "/invalid/config":
            return SimpleNamespace(
                status="invalid_config", reason="invalid config", fs_fact=None, is_valid=lambda: False
            )
        return SimpleNamespace(status="not_found", reason="file missing", fs_fact=None, is_valid=lambda: False)

    with (
        patch("nomarr.components.library.reconcile_paths_comp.get_library_stats", return_value={"total_files": 2}),
        patch("nomarr.components.library.reconcile_paths_comp.list_songs", side_effect=list_rows),
        patch(
            "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
            side_effect=build_path,
        ),
    ):
        result = reconcile_library_paths(db, library=library, policy=policy, batch_size=2)

    assert result["deleted_files"] == 0
    assert result["invalid_config"] == 1
    assert result["not_found"] == 1
    assert [row.song.path for row in rows] == ["/invalid/config", "/missing/file"]
    db.library.remove_song_by_path.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_delete_invalid_delete_failure_increments_errors_without_counting_deletion() -> None:
    """A failed guarded delete counts one error, no deletion, and does not propagate.

    The component swallows the delete ``RuntimeError`` itself, so the outer per-file
    handler must not also count it: a regression that counted a deletion after a failed
    delete, or that let the exception escape to the outer handler (``errors == 2``),
    fails here.
    """
    db = MagicMock()
    library = Library(name="Test Library", root_path="/music")
    row = _hydrated("/invalid/config")
    rows = [row]
    db.library.remove_song_by_path.side_effect = RuntimeError("db unavailable")

    calls = 0

    def list_rows(_db: object, *, library: Library, limit: int, offset: int) -> tuple[list[HydratedSong], int]:
        nonlocal calls
        del _db, library, limit, offset
        calls += 1
        return (rows, len(rows)) if calls == 1 else ([], 0)

    library_path = SimpleNamespace(
        status="invalid_config",
        reason="invalid config",
        fs_fact=None,
        is_valid=lambda: False,
    )

    with (
        patch("nomarr.components.library.reconcile_paths_comp.get_library_stats", return_value={"total_files": 1}),
        patch("nomarr.components.library.reconcile_paths_comp.list_songs", side_effect=list_rows),
        patch(
            "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
            return_value=library_path,
        ),
    ):
        result = reconcile_library_paths(db, library=library, policy="delete_invalid", batch_size=2)

    assert result["deleted_files"] == 0
    assert result["errors"] == 1
    assert result["invalid_config"] == 1
    assert rows == [row]
    db.library.remove_song_by_path.assert_called_once_with("/invalid/config", library)
