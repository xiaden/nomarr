"""Real PostgreSQL evidence for the K1R-A public projection boundary.

These tests deliberately use only semantic facade inputs and reads.  PostgreSQL
is required because the assertions cover library-scoped predicates, independent
sessions, and the production carrier/projection path rather than a mocked
repository.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from inspect import getsource
from threading import Barrier
from typing import TYPE_CHECKING, Any

import pytest

from nomarr.components.analytics.mood_analysis_comp import compute_mood_analysis
from nomarr.components.navidrome.descriptor_match_comp import (
    descriptor_for_locator,
    resolve_seed_descriptor_to_file,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.helpers.song_locator_codec import decode_song_locator
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from collections.abc import Iterator


pytestmark = [pytest.mark.characterization, pytest.mark.requires_database]


def _identity(library: Library, path: str) -> SongIdentity:
    assert library.library_uuid is not None
    return SongIdentity(
        library=LibraryIdentity(library_uuid=library.library_uuid),
        normalized_path=path,
    )


def _upsert(db: Database, library: Library, *, title: str, artist: str) -> SongIdentity:
    identity = _identity(library, "shared/song.flac")
    result = db.library.add_song_to_library(
        SongUpsertInput(
            library=identity.library,
            path=f"{library.root_path}/shared/song.flac",
            scan=SongScanUpdate(
                normalized_path=identity.normalized_path,
                file_size=100,
                modified_time=1_000,
                duration_seconds=180.0,
            ),
        )
    )
    assert result == identity
    db.library.ensure_tag(TagRef(name="title", value=title))
    db.library.ensure_tag(TagRef(name="artist", value=artist))
    db.library.ensure_tag(TagRef(name="nom:mood-strict", value=f"{title}-strict", namespace="nom"))
    db.library.ensure_tag(TagRef(name="nom:mood-regular", value=f"{title}-regular", namespace="nom"))
    db.library.replace_song_tags(
        identity,
        [
            SongTagAssignment(name="title", value=title),
            SongTagAssignment(name="artist", value=artist),
            SongTagAssignment(name="album", value="Shared Album"),
            SongTagAssignment(name="nom:mood-strict", value=f"{title}-strict", namespace="nom"),
            SongTagAssignment(name="nom:mood-regular", value=f"{title}-regular", namespace="nom"),
        ],
    )
    return identity


def _new_library(db: Database, name: str, root: str) -> Library:
    return db.library.create_library(Library(name=name, root_path=root))


def _cleanup(db: Database, libraries: Iterator[Library] | tuple[Library, ...]) -> None:
    for library in libraries:
        db.library.remove_library(library)


@pytest.mark.integration
def test_public_facades_project_analytics_and_navidrome_by_uuid_without_leakage(db: Database) -> None:
    """Real semantic filtering keeps colliding paths and values library-local."""
    first = _new_library(db, "K1R-A2 first", "/tmp/k1r-a2-first")
    second = _new_library(db, "K1R-A2 second", "/tmp/k1r-a2-second")
    try:
        first_locator = _upsert(db, first, title="First Song", artist="First Artist")
        second_locator = _upsert(db, second, title="Second Song", artist="Second Artist")

        first_analysis = compute_mood_analysis(db, first)
        second_analysis = compute_mood_analysis(db, second)
        assert first_analysis["coverage"]["total_files"] == 1
        assert second_analysis["coverage"]["total_files"] == 1
        assert first_analysis["balance"]["strict"] == [{"mood": "First Song-strict", "count": 1}]
        assert second_analysis["balance"]["strict"] == [{"mood": "Second Song-strict", "count": 1}]
        assert "Second Song-strict" not in repr(first_analysis)
        assert "First Song-strict" not in repr(second_analysis)
        assert first_analysis["dominant_vibes"] != second_analysis["dominant_vibes"]

        first_descriptor = descriptor_for_locator(db, first_locator)
        second_descriptor = descriptor_for_locator(db, second_locator)
        assert first_descriptor is not None
        assert second_descriptor is not None
        assert first_descriptor["title"] == "First Song"
        assert second_descriptor["title"] == "Second Song"
        assert first_descriptor["nomarr_file_key"] != second_descriptor["nomarr_file_key"]
        decoded_first = decode_song_locator(first_descriptor["nomarr_file_key"] or "")
        decoded_second = decode_song_locator(second_descriptor["nomarr_file_key"] or "")
        assert decoded_first.library_uuid == first_locator.library.library_uuid
        assert decoded_second.library_uuid == second_locator.library.library_uuid
        assert decoded_first.library_uuid != decoded_second.library_uuid
        assert decoded_first.path == decoded_second.path == "shared/song.flac"

        resolved, error = resolve_seed_descriptor_to_file(db, first_descriptor)
        assert error == ""
        assert resolved == first_descriptor["nomarr_file_key"]
        assert "First Song" not in repr(second_descriptor)
    finally:
        _cleanup(db, (first, second))


def test_independent_databases_have_deterministic_interleaving_and_no_shared_projection_cache(
    db: Database, test_db_url: str
) -> None:
    """Concurrent public reads remain deterministic and scoped to each UUID."""
    first = _new_library(db, "K1R-A2 concurrent first", "/tmp/k1r-a2-concurrent-first")
    second = _new_library(db, "K1R-A2 concurrent second", "/tmp/k1r-a2-concurrent-second")
    left = Database(url=test_db_url, echo=False, pool_size=2, max_overflow=2)
    right = Database(url=test_db_url, echo=False, pool_size=2, max_overflow=2)
    barrier = Barrier(2)
    try:
        _upsert(db, first, title="Concurrent First", artist="Artist One")
        _upsert(db, second, title="Concurrent Second", artist="Artist Two")

        def read(database: Database, library: Library) -> tuple[Any, Any]:
            barrier.wait(timeout=5)
            return compute_mood_analysis(database, library), compute_mood_analysis(database, library)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(read, left, first),
                executor.submit(read, right, second),
            ]
            first_results, second_results = (future.result(timeout=20) for future in futures)

        assert first_results[0] == first_results[1]
        assert second_results[0] == second_results[1]
        assert "Concurrent Second" not in repr(first_results[0])
        assert "Concurrent First" not in repr(second_results[0])
        assert left is not right
        assert not hasattr(left, "_projection_cache")
        assert not hasattr(right, "_projection_cache")
    finally:
        left.close()
        right.close()
        _cleanup(db, (first, second))


def test_public_projection_ownership_is_semantic_and_consume_only() -> None:
    """Executable source rejects row/identity/ownership escape hatches."""
    sources = [
        getsource(compute_mood_analysis),
        getsource(descriptor_for_locator),
        getsource(resolve_seed_descriptor_to_file),
    ]
    executable_tokens: set[str] = set()
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                continue
            if isinstance(node, ast.Name):
                executable_tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                executable_tokens.add(node.attr)

    forbidden = {
        "SongRow",
        "song_id",
        "file_id",
        "library_id",
        "generated_id",
        "resolve_song_identity",
        "resolve_song_identities",
        "begin",
        "transaction",
        "session",
        "MlDb",
        "SongUpsertInput",
        "TagRepository",
        "replace_mood_tags",
        "replace_mood_tags_batch",
    }
    assert executable_tokens.isdisjoint(forbidden)
    assert "locators_for_carriers" in executable_tokens
    assert "TagRef(" not in "".join(sources)


def test_ownership_boundaries_are_not_reimplemented_by_public_projection() -> None:
    """TagRef/ML/SongUpsert/mood APIs remain external consume-only boundaries."""
    source = getsource(resolve_seed_descriptor_to_file) + getsource(descriptor_for_locator)
    assert "TagRef(" not in source
    assert "replace_song_tags" not in source
    assert "replace_mood_tags" not in source
    assert "SongUpsertInput" not in source
    assert "MlDb" not in source
    assert "execute(" not in source
    assert "SELECT " not in source
