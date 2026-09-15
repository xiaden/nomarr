"""RED tests for the Part-B resolution migration in ``path_comp``.

These tests are authored against the DD contract (``DD-canonical-filesystem-access-contract``
§8.2, ADR-050 items 1 and 4) before the production migration lands. Resolution is
config/semantic-only: the builders must drop ``check_disk``, never return ``not_found``,
and surface every filesystem-derived failure as ``status="unknown"`` with an ``FsFact``
instead of leaking a bare ``OSError``.

The tests fail on the Part-A-only tree by assertion (a missing file resolves to ``valid``
only when no disk probe happens; the ``check_disk`` parameter must be gone).
"""

from __future__ import annotations

import errno
import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.components.infrastructure import path_comp as path_comp_module
from nomarr.components.infrastructure.path_comp import (
    build_library_path_from_db,
    build_library_path_from_input,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.fs_contract import FsFact

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _library(root: Path, name: str = "lib1") -> Library:
    """Build a domain library rooted at ``root``."""
    return Library(name=name, root_path=str(root), is_enabled=True)


def _mock_db(library: Library | None, libraries: list[Library] | None = None) -> MagicMock:
    """Mock only the persistence facade used by path resolution."""
    db = MagicMock()
    db.library.get_library_by_name.return_value = library
    if libraries is None:
        libraries = [library] if library is not None else []
    db.library.list_libraries.return_value = libraries
    return db


def test_build_library_path_from_db_accepts_only_the_new_call_shape(tmp_path: Path) -> None:
    """``check_disk`` is removed from the builder; resolution no longer takes a probe flag."""
    library = _library(tmp_path)
    db = _mock_db(library)

    parameters = inspect.signature(build_library_path_from_db).parameters
    assert "check_disk" not in parameters, (
        "build_library_path_from_db must no longer accept check_disk; resolution is config-only"
    )

    result = build_library_path_from_db(stored_path="song.mp3", db=db, library_id=library.name)
    assert result.library_id == library.name


def test_build_library_path_from_db_missing_file_is_valid_without_disk_probe(tmp_path: Path) -> None:
    """A config-resolvable missing file is ``valid`` — proof that no existence probe ran."""
    library = _library(tmp_path)
    db = _mock_db(library)

    result = build_library_path_from_db(stored_path="gone.mp3", db=db, library_id=library.name)

    assert result.status != "not_found"
    assert result.status == "valid"
    assert result.is_valid() is True


def test_build_library_path_from_input_missing_file_is_valid_without_disk_probe(tmp_path: Path) -> None:
    """``build_library_path_from_input`` must not preflight ``Path.exists()``/``is_file()``."""
    library = _library(tmp_path)
    db = _mock_db(library, [library])

    result = build_library_path_from_input(str(tmp_path / "gone.mp3"), db)

    assert result.status != "not_found"
    assert result.status == "valid"
    assert result.is_valid() is True


def test_resolution_canonicalisation_failure_returns_unknown_with_fs_fact(tmp_path: Path) -> None:
    """A symlink loop is a filesystem-derived failure: ``unknown`` + ``invalid_path`` fact."""
    library = _library(tmp_path)
    db = _mock_db(library, [library])
    loop = tmp_path / "loop.mp3"
    loop.symlink_to(loop)

    try:
        result = build_library_path_from_input(str(loop), db)
    except (OSError, RuntimeError) as exc:  # pragma: no cover - RED on the Part-A-only tree
        pytest.fail(f"canonicalisation failure must be a typed fact, not {type(exc).__name__}: {exc}")

    assert result.status == "unknown"
    assert result.fs_fact is not None
    assert result.fs_fact.kind == "invalid_path"


def test_resolution_never_returns_not_found(tmp_path: Path) -> None:
    """Neither builder may produce ``not_found`` (D-B2)."""
    library = _library(tmp_path)
    db = _mock_db(library, [library])

    from_db = build_library_path_from_db(stored_path="gone.mp3", db=db, library_id=library.name)
    assert from_db.status != "not_found"

    from_input = build_library_path_from_input(str(tmp_path / "gone.mp3"), db)
    assert from_input.status != "not_found"


def test_resolution_does_not_escape_bare_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient ``OSError`` during canonicalisation is classified, never propagated raw."""
    library = _library(tmp_path)
    db = _mock_db(library)

    def _stale(path: object, *, strict: bool) -> Path:
        raise OSError(errno.ESTALE, "Stale file handle")

    # Cover both ``from ... import canonicalize`` and ``fs_contract.canonicalize`` call styles.
    monkeypatch.setattr(path_comp_module, "canonicalize", _stale, raising=False)
    monkeypatch.setattr("nomarr.helpers.fs_contract.canonicalize", _stale, raising=False)

    try:
        result = build_library_path_from_db(stored_path="song.mp3", db=db, library_id=library.name)
    except OSError as exc:  # pragma: no cover - RED on the Part-A-only tree
        pytest.fail(f"a bare OSError escaped resolution: {exc!r}")

    assert result.status == "unknown"
    assert result.fs_fact is not None
    assert result.fs_fact.kind == "storage_unavailable"


_PRODUCTION_DB_SHAPES = [
    ("reconcile_paths_comp", {"stored_path": "gone.mp3", "library_id": "lib1"}),
    ("process_file_wf", {"stored_path": "gone.mp3", "library_id": None}),
    ("write_file_tags_wf", {"stored_path": "gone.mp3", "library_id": "lib1"}),
    ("generate_static_playlist_wf", {"stored_path": "gone.mp3"}),
]


@pytest.mark.parametrize(
    ("caller", "kwargs"),
    _PRODUCTION_DB_SHAPES,
    ids=[caller for caller, _ in _PRODUCTION_DB_SHAPES],
)
def test_all_production_call_shapes_resolve_without_check_disk(
    tmp_path: Path,
    caller: str,
    kwargs: dict[str, object],
) -> None:
    """Drive the real builder with each production caller's shape (only persistence mocked).

    ``caller`` is documentation for which call site the shape mirrors; the assertion guards
    that the in-place ``check_disk`` removal happened for every production argument shape.
    """
    del caller
    library = _library(tmp_path)
    db = _mock_db(library, [library])

    parameters = inspect.signature(build_library_path_from_db).parameters
    assert "check_disk" not in parameters

    # The ``library_id=None`` shapes mirror callers that pass an absolute physical
    # path (``process_file_wf`` / ``generate_static_playlist_wf``). The shared
    # relative placeholder ``gone.mp3`` resolves against the process CWD and can
    # never be contained by the mock root, so materialise the real absolute shape.
    if kwargs.get("library_id") is None:
        kwargs = {**kwargs, "stored_path": str(tmp_path / "gone.mp3")}

    result = build_library_path_from_db(db=db, **kwargs)  # type: ignore[arg-type]
    assert result.status != "not_found"
    assert result.status == "valid"


def test_fs_fact_is_a_frozen_contract_value() -> None:
    """Sanity guard that the new field type is the Part-A contract value (D-B3)."""
    fact = FsFact(presence="unknown", kind="invalid_path", errno=None)
    assert fact.kind == "invalid_path"
    assert FilesystemError("boom", fact=fact).fact is fact
