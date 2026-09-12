"""Static and semantic evidence for Plan F phase-4 hard-cut boundaries."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from nomarr.components.library.song_query_types import (
    HydratedSong,
    RecentSong,
    StateTaggedSong,
    TaggedSong,
    TagMatchedSong,
    TrackSong,
)
from nomarr.persistence.api.library_songs import LibrarySongsDb

ROOT = Path(__file__).parents[4]
F_FILES = (
    ROOT / "nomarr/components/library/library_song_query_comp.py",
    ROOT / "nomarr/components/library/tag_hydration_comp.py",
    ROOT / "nomarr/components/library/song_query_types.py",
)
FORBIDDEN_RESOLVER_TEXT = ("resolve_song_identity(", "resolve_song_identities(")
FORBIDDEN_ROW_TEXT = ('doc["id"]', 'doc["path"]', "Song.from_row")
FORBIDDEN_ID_FIELDS = {"song_id", "library_id", "folder_id", "file_id"}


def _without_docstrings(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        ):
            node.body[0].value = ast.Constant(value=None)
    return ast.unparse(tree)


def test_f_sources_have_no_integer_resolver_or_row_bridge() -> None:
    source = "\n".join(_without_docstrings(path.read_text()) for path in F_FILES)
    assert not any(text in source for text in FORBIDDEN_RESOLVER_TEXT)
    assert not any(text in source for text in FORBIDDEN_ROW_TEXT)
    assert "return song.to_dict()" not in source
    assert 'doc[\\"id\\"]' not in source
    assert 'doc[\\"path\\"]' not in source


def test_f_carriers_are_id_free_and_metadata_is_not_a_song_document() -> None:
    carrier_fields = {
        field
        for carrier in (HydratedSong, TaggedSong, StateTaggedSong, RecentSong, TagMatchedSong, TrackSong)
        for field in inspect.signature(carrier).parameters
    }
    assert carrier_fields.isdisjoint(FORBIDDEN_ID_FIELDS)
    assert "metadata" in inspect.signature(HydratedSong).parameters
    assert "song" in inspect.signature(HydratedSong).parameters


def test_scalar_handoff_is_locator_typed_and_non_generic() -> None:
    for method_name in ("set_modified_time", "set_last_tagged", "set_chromaprint"):
        signature = inspect.signature(getattr(LibrarySongsDb, method_name))
        assert signature.parameters["song"].annotation == "SongIdentity"
        assert signature.return_annotation == "FieldWriteResult"
    assert inspect.signature(LibrarySongsDb.set_chromaprint).parameters["value"].annotation == "ChromaprintValue"


def test_scalar_callers_are_not_owned_by_f_components() -> None:
    source = "\n".join(path.read_text() for path in F_FILES)
    scalar_names = (
        "update_library_song_modified_time",
        "set_library_song_chromaprint",
        "update_library_song_last_tagged_at",
    )
    assert not any(name in source for name in scalar_names)


def test_f_sources_do_not_construct_generic_mood_writes() -> None:
    source = "\n".join(path.read_text() for path in F_FILES)
    assert "save_mood_tags" not in source
    assert "set_song_tags_batch" not in source
