"""Static contract checks for Plan E's scalar metadata handoff."""

from __future__ import annotations

import inspect
from pathlib import Path

from nomarr.helpers.dataclasses.song_command_dataclass import (
    ChromaprintValue,
    FieldWriteResult,
    SongIdentity,
)
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.persistence.api.library_songs import LibrarySongsDb

ROOT = Path(__file__).parents[3]


def test_scalar_facade_uses_locator_and_typed_results() -> None:
    assert inspect.signature(LibrarySongsDb.set_modified_time).parameters["song"].annotation == "SongIdentity"
    assert inspect.signature(LibrarySongsDb.set_last_tagged).parameters["song"].annotation == "SongIdentity"
    assert inspect.signature(LibrarySongsDb.set_chromaprint).parameters["song"].annotation == "SongIdentity"
    assert FieldWriteResult("MISSING_LOCATOR").status == "MISSING_LOCATOR"


def test_chromaprint_value_is_immutable_and_provenanced() -> None:
    value = ChromaprintValue("abc", "decoder:v1")
    assert value.provenance == "decoder:v1"
    assert "frozen=True" in inspect.getsource(ChromaprintValue)


def test_hydration_input_is_payload_only_and_identity_is_locator_addressed() -> None:
    assert "song_id" not in inspect.signature(HydrateSongInput).parameters
    assert "song_id" not in inspect.signature(SongIdentity).parameters


def test_deferred_carriers_are_immutable_and_storage_free() -> None:
    from dataclasses import fields, is_dataclass

    from nomarr.helpers.dto.processing_dto import (
        DeferredBackboneVectorWrite,
        DeferredFileWrites,
        DeferredOutputStreamWrite,
    )

    for carrier in (DeferredOutputStreamWrite, DeferredBackboneVectorWrite, DeferredFileWrites):
        assert is_dataclass(carrier)
        assert getattr(carrier, "__dataclass_params__", None) is not None
        names = {field.name for field in fields(carrier)}
        assert not names & {"song_id", "file_id", "library_id", "embed_dim", "model_id"}


def test_hydration_boundary_does_not_disclose_integer_handle() -> None:
    source = (ROOT / "nomarr/persistence/database/song_hydration_repo.py").read_text()
    assert '"Song not found: {input.song_id}"' not in source
    assert '"song_ids": [input.song_id for input in chunk]' not in source


def test_query_component_has_no_raw_song_document_conversion() -> None:
    source = (ROOT / "nomarr/components/library/library_song_query_comp.py").read_text()
    assert 'doc["id"]' not in source
    assert 'doc["path"]' not in source
    assert "return song.to_dict()" not in source
