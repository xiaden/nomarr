# mypy: disable-error-code=func-returns-value
"""Facade identity-boundary contract tests.

These tests cover the retained library-handle mapping used inside persistence.
Application callers use ``SongIdentity`` directly; hydration remains
locator-addressed and payload-only.

The root ``Database`` tag boundary resolver (``resolve_tag_identity`` /
``resolve_tag_identities``) was retired after the repo-wide caller migration
(the bridge-retirement contract): the zero-caller audit proved
safe deletion, the methods are gone, and no integer tag primary key may enter
the public tag contract. This module asserts their permanent absence and that
the natural ``library_tags`` surface alone carries the full tag intent surface,
taking only ``TagRef``/``SongIdentity`` and never an integer tag PK.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
)
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_songs import LibrarySongsDb
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.db import Database

_TEST_LIBRARY = LibraryIdentity(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")


def _make_songs_db() -> tuple[LibrarySongsDb, MagicMock, MagicMock]:
    song_repo = MagicMock()
    library_repo = MagicMock()
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    return songs, song_repo, library_repo


def _library_row(library_id: int, name: str, root_path: str) -> dict:
    return {
        "id": library_id,
        "library_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{name}\x00{root_path}")),
        "name": name,
        "path": root_path,
    }


@pytest.mark.unit
class TestLibraryIdentityBoundary:
    """Library identity is supplied semantically; storage IDs stay private."""

    def test_library_identity_is_a_locator_value(self) -> None:
        assert _TEST_LIBRARY.library_uuid
        assert _TEST_LIBRARY.name == "TestLib"

    def test_library_identity_requires_uuid(self) -> None:
        with pytest.raises(ValueError, match="library_uuid"):
            LibraryIdentity(library_uuid="", name="TestLib", root_path="/music")


@pytest.mark.unit
class TestRootTagBridgeRetired:
    """The root Database tag-PK resolver is deleted and stays absent.

    CONTRACTS.md "Bridge-retirement contract": ``Database.resolve_tag_identity``
    / ``resolve_tag_identities`` were lookup-only root-database conversions that
    accepted opaque integer tag PKs. After every caller migrated onto the
    natural facade (``TagRef`` / ``db.library.get_tag``), the zero-caller audit
    proved safe deletion. They must never reappear on ``Database`` or the tag
    facades, and the natural facade must carry the full tag intent surface.
    """

    def test_root_database_exposes_no_tag_resolver(self) -> None:
        assert not hasattr(Database, "resolve_tag_identity")
        assert not hasattr(Database, "resolve_tag_identities")

    def test_tag_facades_expose_no_tag_resolver(self) -> None:
        # The tag boundary conversion was never a LibraryTagsDb/LibraryDb method
        # or forwarder, and the natural facade must not re-add an ID-taking
        # resolver either.
        for cls in (LibraryTagsDb, LibraryDb):
            assert not hasattr(cls, "resolve_tag_identity")
            assert not hasattr(cls, "resolve_tag_identities")

    def test_natural_facade_carries_full_intent_surface(self) -> None:
        # Tag identity entry points live on the sealed natural facade only.
        for cls in (LibraryTagsDb, LibraryDb):
            assert hasattr(cls, "get_tag")
            assert hasattr(cls, "ensure_tag")
            assert hasattr(cls, "relink_tags")


@pytest.mark.unit
class TestNoFacadeTransactionApi:
    """The bridge adds no facade transaction context (AR-SDR-4)."""

    def test_song_bridge_exposes_no_transaction_api(self) -> None:
        songs, _, _ = _make_songs_db()
        assert not hasattr(songs, "transaction")
        assert not hasattr(songs, "_require_transaction")

    def test_root_database_exposes_no_transaction_api(self) -> None:
        assert not hasattr(Database, "transaction")
        assert not hasattr(Database, "_require_transaction")


@pytest.mark.unit
class TestSealedTagSurfaceNoIntegerParams:
    """The sealed tag surface takes no integer song/tag primary keys."""

    _SEALED = (
        "get_tag",
        "ensure_tag",
        "list_tags_for_song",
        "replace_song_tags",
        "remove_song_tags",
        "relink_tags",
    )

    def test_library_tags_db_methods_take_no_song_id_or_tag_id(self) -> None:
        for name in self._SEALED:
            params = inspect.signature(getattr(LibraryTagsDb, name)).parameters
            assert "song_id" not in params, f"{name} must not take song_id"
            assert "tag_id" not in params, f"{name} must not take tag_id"

    def test_library_db_tag_forwarders_take_no_song_id_or_tag_id(self) -> None:
        for name in self._SEALED:
            params = inspect.signature(getattr(LibraryDb, name)).parameters
            assert "song_id" not in params, f"{name} must not take song_id"
            assert "tag_id" not in params, f"{name} must not take tag_id"

    def test_no_compatibility_alias_or_dual_identity_path(self) -> None:
        # ID-returning / raw-edge names removed by the migration matrix have no
        # alias or dual-identity wrapper on the tag surface.
        for name in (
            "find_or_create_tag",
            "list_song_ids_for_tag_id",
            "list_song_tag_edges",
            "list_tags_by_name",
            "replace_tag_references",
            "replace_selected_tag_references",
            "search_songs_by_tag",
        ):
            assert not hasattr(LibraryTagsDb, name), f"deleted name {name} must not reappear on LibraryTagsDb"
            assert not hasattr(LibraryDb, name), f"deleted name {name} must not reappear on LibraryDb"
