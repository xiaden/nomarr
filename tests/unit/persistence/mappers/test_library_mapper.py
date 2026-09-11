"""Contract tests for the persistence-private library row mappers.

``TASK-song-row-mirror-leaks-into-domain-G`` P1-S1/P1-S2/P1-S6. ADR-049 makes
``libraries.library_uuid`` the immutable Nomarr-minted library application
identity. These tests prove:

- every insert mints a UUID when the domain value does not carry one, and a
  delete/recreate cycle (a fresh domain value) mints a new distinct value;
- ``library_update_payload`` never includes ``library_uuid``, so rename and
  root-path changes preserve the immutable identity;
- the row→domain mapper carries the UUID for the owning ``Library``.
"""

from __future__ import annotations

import uuid

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryUpdate
from nomarr.persistence.mappers.library_mapper import (
    library_from_row,
    library_insert_payload,
    library_update_payload,
)

_EXISTING_UUID = "de131b32-af5c-5a84-8874-58e3dc0e2dcd"


def _library(**overrides: object) -> Library:
    values: dict[str, object] = {"name": "TestLib", "root_path": "/music"}
    values.update(overrides)
    return Library(**values)  # type: ignore[arg-type]


@pytest.mark.unit
class TestLibraryInsertPayload:
    def test_mints_uuid_when_absent(self) -> None:
        payload = library_insert_payload(_library())
        minted = payload["library_uuid"]
        assert isinstance(minted, str) and minted
        uuid.UUID(minted)

    def test_mint_on_create_is_fresh_per_library(self) -> None:
        first = library_insert_payload(_library(name="First"))
        second = library_insert_payload(_library(name="Second"))
        assert first["library_uuid"] != second["library_uuid"]

    def test_preserves_supplied_identity(self) -> None:
        payload = library_insert_payload(_library(library_uuid=_EXISTING_UUID))
        assert payload["library_uuid"] == _EXISTING_UUID

    def test_records_do_not_share_a_minted_identity(self) -> None:
        # Delete/recreate passes a freshly constructed domain value each time;
        # each insert therefore mints a distinct identity (no reuse).
        first = library_insert_payload(_library())
        recreated = library_insert_payload(_library())
        assert first["library_uuid"] != recreated["library_uuid"]


@pytest.mark.unit
class TestLibraryUpdatePayload:
    def test_rename_never_touches_library_uuid(self) -> None:
        payload = library_update_payload(LibraryUpdate(name="Renamed"))
        assert "library_uuid" not in payload
        assert payload["name"] == "Renamed"

    def test_root_path_change_never_touches_library_uuid(self) -> None:
        payload = library_update_payload(LibraryUpdate(root_path="/music/new"))
        assert "library_uuid" not in payload
        assert payload["path"] == "/music/new"

    def test_empty_update_is_identity_free(self) -> None:
        assert library_update_payload(LibraryUpdate()) == {}


@pytest.mark.unit
class TestLibraryFromRow:
    def test_reads_library_uuid_into_domain(self) -> None:
        library = library_from_row(
            {
                "name": "TestLib",
                "path": "/music",
                "library_uuid": _EXISTING_UUID,
                "library_type": "music",
            }
        )
        assert library.library_uuid == _EXISTING_UUID
        assert library.name == "TestLib"
        assert library.root_path == "/music"

    def test_round_trips_identity_through_insert_payload(self) -> None:
        library = _library(library_uuid=_EXISTING_UUID)
        row = library_insert_payload(library)
        row["library_type"] = "music"
        assert library_from_row(row).library_uuid == _EXISTING_UUID
