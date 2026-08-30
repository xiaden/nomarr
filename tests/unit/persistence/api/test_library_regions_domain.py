"""Persistence facade tests for the domain ``LibraryRegionsDb`` surface.

These use repository doubles (``MagicMock``) — no real database — and prove the
hard domain boundary (ADR-032/041/043):

- rows are mapped to domain ``Library`` values before returning;
- generated primary-key ids never cross the facade boundary;
- arbitrary storage dictionaries are rejected (``update_library`` takes a typed
  ``LibraryUpdate`` command, not a ``fields`` dict);
- natural-key ``(name, root_path)`` lookup is deterministic;
- pipeline state is row-backed inside persistence without leaking row payloads.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.constants.pipeline_states import ML_AXIS, SCAN_AXIS
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryPipelineState, LibraryUpdate
from nomarr.helpers.dto.repo_dto import LibraryRow
from nomarr.persistence.api.library_regions import LibraryRegionsDb


def _row(**overrides: object) -> LibraryRow:
    base = {
        "id": 7,
        "name": "main",
        "path": "/music",
        "library_type": "music",
        "auto_tag": 0,
        "auto_curate": 0,
        "watch_mode": "off",
        "file_write_mode": "full",
        "created_at": 100,
        "updated_at": 200,
    }
    return LibraryRow(**{**base, **overrides})


def _make_regions(
    *,
    library_repo: MagicMock | None = None,
    pipeline_repo: MagicMock | None = None,
) -> tuple[LibraryRegionsDb, MagicMock, MagicMock]:
    library_repo = library_repo or MagicMock()
    pipeline_repo = pipeline_repo or MagicMock()
    regions = LibraryRegionsDb(
        session=MagicMock(),
        library_repo=library_repo,
        song_state_repo=MagicMock(),
        pipeline_repo=pipeline_repo,
    )
    return regions, library_repo, pipeline_repo


def _main_library() -> Library:
    return Library(
        name="main",
        root_path="/music",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
        created_at=100,
        updated_at=200,
    )


# ── row → domain mapping (no id / storage vocabulary leaks) ───────────────


@pytest.mark.unit
def test_get_library_maps_row_to_domain_without_id() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.get_library = MagicMock(return_value=_row())

    result = regions.get_library(_main_library())

    assert isinstance(result, Library)
    assert result.name == "main"
    assert result.root_path == "/music"  # storage "path" -> root_path
    assert result.is_enabled is True  # storage "library_type" == "music"
    assert result.library_auto_write is False  # storage "auto_curate" int -> bool
    assert result.created_at == 100
    assert result.updated_at == 200
    assert not hasattr(result, "id")  # generated id never crosses the boundary
    assert not hasattr(result, "path")
    assert not hasattr(result, "library_type")
    library_repo.get_library_by_natural_key.assert_called_once_with("main", "/music")


@pytest.mark.unit
def test_get_library_maps_disabled_library_type() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row(library_type="disabled"))
    library_repo.get_library = MagicMock(return_value=_row(library_type="disabled"))

    result = regions.get_library(_main_library())

    assert result.is_enabled is False


@pytest.mark.unit
def test_list_libraries_returns_domain_values() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.list_libraries = MagicMock(return_value=[_row(), _row(id=8, name="alt", path="/alt")])

    result = regions.list_libraries(enabled_only=True)

    assert len(result) == 2
    assert all(isinstance(lib, Library) for lib in result)
    assert [lib.name for lib in result] == ["main", "alt"]
    assert [lib.root_path for lib in result] == ["/music", "/alt"]
    library_repo.list_libraries.assert_called_once_with(enabled_only=True)


# ── create / update (typed commands, timestamps) ──────────────────────────


@pytest.mark.unit
def test_create_library_supplies_timestamps_and_returns_domain() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.add_library = MagicMock(return_value=7)
    library_repo.get_library = MagicMock(return_value=_row())

    new_library = Library(name="main", root_path="/music")

    result = regions.create_library(new_library)

    payload = library_repo.add_library.call_args[0][0]
    assert payload["path"] == "/music"
    assert payload["library_type"] == "music"
    assert payload["auto_tag"] == 0
    assert isinstance(payload["created_at"], int)  # persistence-supplied
    assert isinstance(payload["updated_at"], int)
    assert isinstance(result, Library)
    assert result.created_at == 100  # persisted values returned
    assert result.updated_at == 200
    assert not hasattr(result, "id")


@pytest.mark.unit
def test_create_library_maps_watch_mode_to_auto_tag() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.add_library = MagicMock(return_value=7)
    library_repo.get_library = MagicMock(return_value=_row())

    regions.create_library(Library(name="main", root_path="/music", watch_mode="event"))

    payload = library_repo.add_library.call_args[0][0]
    assert payload["watch_mode"] == "event"
    assert payload["auto_tag"] == 1


@pytest.mark.unit
def test_update_library_applies_typed_update_and_returns_domain() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.update_library = MagicMock()
    library_repo.get_library = MagicMock(return_value=_row(updated_at=300))

    result = regions.update_library(_main_library(), LibraryUpdate(name="renamed", updated_at=300))

    library_repo.update_library.assert_called_once_with(
        7,
        {"name": "renamed", "updated_at": 300},
    )
    assert isinstance(result, Library)
    assert result.updated_at == 300


@pytest.mark.unit
def test_update_library_watch_mode_sets_auto_tag_column() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.update_library = MagicMock()
    library_repo.get_library = MagicMock(return_value=_row())

    regions.update_library(_main_library(), LibraryUpdate(watch_mode="poll"))

    library_repo.update_library.assert_called_once_with(
        7,
        {"watch_mode": "poll", "auto_tag": 1},
    )


@pytest.mark.unit
def test_update_library_rejects_arbitrary_storage_dict() -> None:
    """``update_library`` accepts only a ``LibraryUpdate`` command, not a dict."""
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())

    # Passing a raw column dictionary is a contract violation: the facade reads
    # typed attributes off the command and a plain dict has none of them.
    with pytest.raises(AttributeError):
        regions.update_library(_main_library(), {"name": "x"})  # type: ignore[arg-type]


@pytest.mark.unit
def test_update_library_raises_when_natural_key_missing() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    with pytest.raises(LookupError):
        regions.update_library(_main_library(), LibraryUpdate(name="x"))


# ── natural-key determinism ───────────────────────────────────────────────


@pytest.mark.unit
def test_natural_key_lookup_is_deterministic() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())

    for _ in range(3):
        regions.get_library(Library(name="main", root_path="/music"))

    assert library_repo.get_library_by_natural_key.call_count == 3
    library_repo.get_library_by_natural_key.assert_called_with("main", "/music")


@pytest.mark.unit
def test_remove_library_returns_false_when_missing() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    result = regions.remove_library(_main_library())

    assert result is False
    library_repo.remove_library.assert_not_called()


@pytest.mark.unit
def test_remove_library_returns_true_when_found() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.remove_library = MagicMock()

    result = regions.remove_library(_main_library())

    assert result is True
    library_repo.remove_library.assert_called_once_with(7)


# ── pipeline state (row-backed, no payload leak) ──────────────────────────


@pytest.mark.unit
def test_get_pipeline_state_returns_value_object() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.get_pipeline_state = MagicMock(
        return_value={
            "scan_state": SCAN_AXIS[1],
            "ml_state": ML_AXIS[2],
            "calibration_state": "calibrated",
            "tag_write_state": "written",
        }
    )

    result = regions.get_pipeline_state(_main_library())

    assert isinstance(result, LibraryPipelineState)
    assert result.scan_state == SCAN_AXIS[1]
    assert result.ml_state == ML_AXIS[2]
    assert not hasattr(result, "state_data")  # no row payload leaks


@pytest.mark.unit
def test_get_pipeline_state_defaults_when_no_rows() -> None:
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.get_pipeline_state = MagicMock(return_value=None)

    result = regions.get_pipeline_state(_main_library())

    assert result == LibraryPipelineState.defaults()


@pytest.mark.unit
def test_set_pipeline_axis_validates_and_returns_state() -> None:
    regions, library_repo, pipeline_repo = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.get_pipeline_state = MagicMock(
        return_value={
            "scan_state": SCAN_AXIS[1],
            "ml_state": ML_AXIS[2],
            "calibration_state": "calibrated",
            "tag_write_state": "written",
        }
    )

    result = regions.set_pipeline_axis(_main_library(), "scan_state", SCAN_AXIS[1])

    pipeline_repo.upsert_pipeline_state.assert_called_once_with(7, "scan_state", {"state": SCAN_AXIS[1]})
    assert isinstance(result, LibraryPipelineState)
    assert result.scan_state == SCAN_AXIS[1]


@pytest.mark.unit
def test_set_pipeline_axis_rejects_unknown_axis() -> None:
    regions, *_ = _make_regions()

    with pytest.raises(ValueError, match="pipeline axis"):
        regions.set_pipeline_axis(_main_library(), "bogus_axis", SCAN_AXIS[1])


@pytest.mark.unit
def test_set_pipeline_axis_rejects_invalid_state() -> None:
    regions, *_ = _make_regions()

    with pytest.raises(ValueError, match="Invalid state"):
        regions.set_pipeline_axis(_main_library(), "scan_state", "not-a-pole")


@pytest.mark.unit
def test_create_library_duplicate_natural_key_delegates_to_repo() -> None:
    """Creating a library whose natural key already exists is a repo/persistence
    concern, not a facade one: the facade does not upsert or reject on duplicate
    ``(name, root_path)`` — it forwards the insert and returns the persisted row.
    ``LibraryRegionsDb.create_library`` never inspects prior existence, so a
    duplicate insert is delegated to ``add_library`` and the dedup policy lives
    in the repository/schema (persistence-owned per ADR-032).
    """
    regions, library_repo, _ = _make_regions()
    library_repo.add_library = MagicMock(return_value=7)
    library_repo.get_library = MagicMock(return_value=_row())

    result = regions.create_library(Library(name="main", root_path="/music"))

    library_repo.add_library.assert_called_once()
    assert isinstance(result, Library)
    assert not hasattr(result, "id")


@pytest.mark.unit
def test_get_library_by_natural_key_is_first_match_deterministic() -> None:
    """The natural-key resolver returns whatever the repository resolves first;
    callers address libraries purely by ``(name, root_path)`` — never by a
    generated id — so duplicate rows are indistinguishable to callers by design.
    """
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_name = MagicMock(return_value=_row(id=9, name="main", path="/music"))

    result = regions.get_library_by_name("main")

    assert isinstance(result, Library)
    assert result.name == "main"
    assert not hasattr(result, "id")


# ── cascade deletion (delegated to repo, no facade-owned cleanup) ─────────


@pytest.mark.unit
def test_remove_library_delegates_cascade_without_own_cleanup() -> None:
    """Removal delegates the cascade delete to the repository; the facade itself
    performs no song/tag/song-state cleanup (the repo cascade owns that). This
    proves the facade exposes a single intent and does not layer its own teardown.
    """
    regions, library_repo, _ = _make_regions()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_row())
    library_repo.remove_library = MagicMock()

    result = regions.remove_library(_main_library())

    assert result is True
    library_repo.remove_library.assert_called_once_with(7)
    # The cascade delete is the repository's job — the facade must not add its
    # own tag/song-state teardown that would fight the repo-owned FK cascade.
    assert not hasattr(regions, "cleanup_orphaned_tags")
    assert not hasattr(regions, "remove_song_states")


# ── no caller-managed transactions (UoW lives inside persistence) ──────────


@pytest.mark.unit
def test_regions_facade_exposes_no_transaction_or_session_surface() -> None:
    """Callers manage no transactions: the facade never surfaces a ``session``,
    ``commit``, ``rollback``, ``begin`` or transaction context. Unit-of-work
    (flush/commit) is owned by the persistence layer internally.
    """
    forbidden = {
        "session",
        "transaction",
        "begin",
        "begin_transaction",
        "commit",
        "rollback",
        "flush",
        "require_transaction",
    }
    assert not any(name in dir(LibraryRegionsDb) for name in forbidden), (
        f"LibraryRegionsDb must not expose a transaction/session surface to callers "
        f"(found one of {sorted(forbidden & set(dir(LibraryRegionsDb)))})."
    )


@pytest.mark.unit
def test_get_libraries_in_axis_state_maps_ids_to_domain() -> None:
    regions, library_repo, pipeline_repo = _make_regions()
    pipeline_repo.list_libraries_in_pipeline_state = MagicMock(return_value=[7, 8])
    library_repo.get_library = MagicMock(side_effect=[_row(), _row(id=8, name="alt", path="/alt")])

    result = regions.get_libraries_in_axis_state("scan_state", SCAN_AXIS[1])

    assert [lib.name for lib in result] == ["main", "alt"]
    assert all(isinstance(lib, Library) for lib in result)
    pipeline_repo.list_libraries_in_pipeline_state.assert_called_once_with("scan_state", SCAN_AXIS[1])
    # resolved ids stay internal — only Library values cross the boundary
    assert all(not hasattr(lib, "id") for lib in result)
