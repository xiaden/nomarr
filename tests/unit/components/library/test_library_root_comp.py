"""RED tests for the Part-B ``library_root_comp`` migration.

Authored against DD §8.2 / ADR-050 items 1 and 4: ``get_base_library_root`` classifies the
OSError before rewrapping so a transient ``ESTALE`` stays ``storage_unavailable`` (never
relabelled as a permanent config error); ``normalize_library_root`` re-raises the typed
``FilesystemError`` unchanged; ``validate_library_root`` keeps its ``OSError`` raise type
but preserves the classified errno (SEAM-1, D-B5); and ``ensure_no_overlapping_library_root``
decides containment structurally, not by matching a human-readable message (G3, D-B7).
"""

from __future__ import annotations

import errno
import inspect
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.components.library import library_root_comp as root_comp_module
from nomarr.components.library.library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
    validate_library_root,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.fs_contract import fact_from_error

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_get_base_library_root_missing_raises_filesystem_error_with_fact(tmp_path: Path) -> None:
    """A missing base root raises the typed error carrying a classified fact."""
    with pytest.raises(ValueError) as exc_info:
        get_base_library_root(str(tmp_path / "nope"))

    error = exc_info.value
    assert isinstance(error, FilesystemError)
    assert error.fact.presence == "unknown"
    assert error.fact.kind == "unconfirmed_missing"


def test_get_base_library_root_transient_estale_stays_storage_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient NAS error must not be flattened into a permanent missing/config error."""
    stale = fact_from_error(OSError(errno.ESTALE, "Stale file handle"), path="/vol")
    monkeypatch.setattr(root_comp_module, "probe_fact", lambda _path: stale, raising=False)
    monkeypatch.setattr("nomarr.helpers.fs_contract.probe_fact", lambda _path: stale, raising=False)

    with pytest.raises(ValueError) as exc_info:
        get_base_library_root(str(tmp_path / "nope"))

    error = exc_info.value
    assert isinstance(error, FilesystemError)
    assert error.fact.kind == "storage_unavailable"
    assert error.fact.kind != "invalid_config"


def test_get_base_library_root_not_a_directory_is_wrong_resource_type(tmp_path: Path) -> None:
    """A file passed as the base root is a type error, classified by ``os.stat``."""
    file_root = tmp_path / "not_a_dir"
    file_root.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        get_base_library_root(str(file_root))

    error = exc_info.value
    assert isinstance(error, FilesystemError)
    assert error.fact.kind == "wrong_resource_type"


def test_get_base_library_root_never_relabels_as_invalid_config(tmp_path: Path) -> None:
    """A filesystem-derived failure keeps its kind; it is never an ``invalid_config`` label."""
    with pytest.raises(ValueError) as exc_info:
        get_base_library_root(str(tmp_path / "nope"))

    error = exc_info.value
    assert isinstance(error, FilesystemError)
    assert error.fact.kind in {"unconfirmed_missing", "resource_missing"}
    assert error.fact.kind != "invalid_config"


def test_normalize_library_root_reraises_filesystem_error_unchanged(tmp_path: Path) -> None:
    """The typed error and its generic ``Access denied`` message pass through unwrapped."""
    with pytest.raises(ValueError) as exc_info:
        normalize_library_root(tmp_path, "missing_dir")

    error = exc_info.value
    assert isinstance(error, FilesystemError)
    assert error.fact.kind == "unconfirmed_missing"
    assert str(error) == "Access denied"


def test_validate_library_root_classifies_before_composing_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEAM-1: the raised ``OSError`` carries the real errno so Part C can classify it."""
    missing = tmp_path / "nope"

    with pytest.raises(OSError) as missing_info:
        validate_library_root(missing)
    assert missing_info.value.errno == errno.ENOENT

    stale = fact_from_error(OSError(errno.ESTALE, "Stale file handle"), path=str(missing))
    monkeypatch.setattr(root_comp_module, "probe_fact", lambda _path: stale, raising=False)
    monkeypatch.setattr("nomarr.helpers.fs_contract.probe_fact", lambda _path: stale, raising=False)

    with pytest.raises(OSError) as stale_info:
        validate_library_root(missing)
    assert stale_info.value.errno == errno.ESTALE


def test_overlapping_library_root_raises_without_string_matching(tmp_path: Path) -> None:
    """G3/D-B7: containment is structural; the decision never matches a message substring."""
    db = MagicMock()
    existing = Library(name="existing", root_path=str(tmp_path))
    db.library.list_libraries.return_value = [existing]

    with pytest.raises(ValueError):
        ensure_no_overlapping_library_root(db, str(tmp_path / "nested"))

    source = inspect.getsource(ensure_no_overlapping_library_root)
    assert "is nested inside" not in source, (
        "ensure_no_overlapping_library_root must decide containment with is_relative_to, "
        "not by string-matching a ValueError message"
    )
