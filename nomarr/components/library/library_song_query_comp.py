"""Library song query helpers (semantic boundary).

Multi-hop reads routed through the intent-level persistence facades. The public
surface returns only typed semantic values (``Song``, ``SongStateCandidate``),
scalar/aggregate values, or the typed metadata/tag carriers from
:mod:`nomarr.components.library.song_query_types`. No function here reconstructs a
row-shaped song document, reads ``doc[\"id\"]``/``doc[\"path\"]``, calls
``Song.to_dict()``/``Song.from_row``, or imports a persistence mapper — see
CONTRACTS §1/§3/§7 and plan F (binding per-function output table).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from nomarr.components.library.library_song_state_comp import count_untagged_files
from nomarr.components.library.song_query_types import (
    HydratedSong,
    RecentSong,
    StateTaggedSong,
    TaggedSong,
    TagMatchedSong,
    TrackSong,
)
from nomarr.components.library.tag_hydration_comp import (
    extract_canonical_metadata,
    hydrate_songs_with_metadata,
)
from nomarr.components.library.tag_mapping_comp import is_numeric_tag_value
from nomarr.helpers.constants.file_states import STATE_PROCESSED
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dto.library_dto import FileTag
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.persistence.db import Database

DEFAULT_LIMIT = 1000

_ACTIVITY_EVENT = Literal["scanned", "tagged"]

type Carrier = HydratedSong | TaggedSong | StateTaggedSong | RecentSong | TagMatchedSong | TrackSong


def locators_for_carriers(db: Database, carriers: Sequence[Carrier]) -> list[SongIdentity | None]:
    """Project typed song carriers to UUID-addressed locators in input order.

    A carrier is resolved only when the persistence facade returns a semantically
    equal ``Song`` for a locator built from a UUID-bearing ``LibraryIdentity``.
    Missing carriers remain ``None``; no row, generated ID, physical-path
    heuristic, or caller-managed transaction participates in this projection.
    Empty input is an empty result without touching the library facade, and any
    non-carrier or malformed carrier is rejected deterministically before facade
    work.
    """
    if not carriers:
        return []
    songs: list[Song] = []
    for carrier in carriers:
        if isinstance(carrier, (HydratedSong, TaggedSong, TagMatchedSong, TrackSong)):
            song = carrier.song
        elif isinstance(carrier, (StateTaggedSong, RecentSong)) and isinstance(carrier.candidate, SongStateCandidate):
            song = carrier.candidate.song
        else:
            raise TypeError("locators_for_carriers accepts only typed song carriers")
        if not isinstance(song, Song):
            raise TypeError("locators_for_carriers accepts only typed song carriers")
        songs.append(song)

    locators: list[SongIdentity | None] = [None] * len(songs)
    remaining = set(range(len(songs)))
    for library in db.library.list_libraries():
        if not remaining:
            break
        if library.library_uuid is None:
            continue
        library_identity = _library_identity(library)
        indices = sorted(remaining)
        requested = [_song_identity(songs[i], library_identity) for i in indices]
        resolved = db.library.list_songs_by_identity(requested)
        resolved_by_path = {candidate.normalized_path: candidate for candidate in resolved}
        for index in indices:
            candidate = resolved_by_path.get(songs[index].normalized_path)
            if candidate is not None and candidate == songs[index]:
                locators[index] = _song_identity(candidate, library_identity)
                remaining.discard(index)
    return locators


# ─────────────────────────────────────────────────────────────────────────
# Identity / locator helpers
# ─────────────────────────────────────────────────────────────────────────


def _library_identity(library: Library) -> LibraryIdentity:
    """Resolve a domain ``Library`` value to its immutable ``LibraryIdentity`` locator."""
    if library.library_uuid is None:
        raise ValueError(f"Library {library.name!r} has no library_uuid")
    return LibraryIdentity(
        library_uuid=library.library_uuid,
        name=library.name,
        root_path=library.root_path,
    )


def _song_identity(song: Song, library_identity: LibraryIdentity) -> SongIdentity:
    """Pair a semantic song with its mutable ``SongIdentity`` locator (ADR-048)."""
    return SongIdentity(library=library_identity, normalized_path=song.normalized_path)


def _all_songs_with_libraries(db: Database) -> list[tuple[Song, LibraryIdentity]]:
    """Return every semantic song paired with its owning library locator.

    Cross-library aggregation is the approved iteration pattern: there is no
    global listing primitive, so the full set is materialized by iterating
    ``list_libraries()`` and collecting each library-scoped listing with
    ``limit=None`` (no per-library default cap) before any caller-side
    filter/sort/page.
    """
    result: list[tuple[Song, LibraryIdentity]] = []
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        result.extend((song, library_identity) for song in db.library.list_songs(library_identity, limit=None))
    return result


def _locators_for_songs(db: Database, songs: Sequence[Song]) -> list[SongIdentity | None]:
    """Resolve the owning ``SongIdentity`` locator for each semantic song.

    ``find_songs_with_*`` tag reads return bare ``Song`` values without their
    owning library, so the library must be recovered to re-address each song for
    hydration. For each library this issues one order-preserving batch
    ``list_songs_by_identity`` over the still-unresolved songs and accepts a
    locator only when the resolved value equals the candidate ``Song`` (never a
    physical-path-prefix heuristic). Returns one locator per input song in the
    same order; ``None`` when no owning library resolves. An empty input is an
    empty result without touching the library facade.
    """
    if not songs:
        return []
    locators: list[SongIdentity | None] = [None] * len(songs)
    remaining = set(range(len(songs)))
    for library in db.library.list_libraries():
        if not remaining:
            break
        library_identity = _library_identity(library)
        indices = sorted(remaining)
        unresolved = [songs[i] for i in indices]
        resolved = db.library.list_songs_by_identity([_song_identity(song, library_identity) for song in unresolved])
        # list_songs_by_identity omits unresolvable locators but each returned
        # value is the owning song at its own normalized_path within this
        # library, so keying by normalized_path is robust regardless of order.
        song_by_normalized = {song.normalized_path: song for song in resolved}
        for i in indices:
            candidate = songs[i]
            if song_by_normalized.get(candidate.normalized_path) == candidate:
                locators[i] = SongIdentity(library=library_identity, normalized_path=candidate.normalized_path)
                remaining.discard(i)
    return locators


# ─────────────────────────────────────────────────────────────────────────
# Tag → FileTag / metadata helpers
# ─────────────────────────────────────────────────────────────────────────


def _file_tag_from_assignment(assignment: SongTagAssignment) -> FileTag:
    value = assignment.value
    return FileTag(
        key=assignment.name,
        value=str(value),
        tag_type="float" if is_numeric_tag_value(value) else "string",
        is_nomarr=assignment.namespace == "nom",
    )


def _file_tags(assignments: Sequence[SongTagAssignment]) -> tuple[FileTag, ...]:
    """Project sealed tag assignments into ``FileTag`` values sorted by key."""
    return tuple(sorted((_file_tag_from_assignment(a) for a in assignments), key=lambda tag: _sort_key(tag.key)))


def _derive_metadata(assignments: Sequence[SongTagAssignment]) -> Mapping[str, object]:
    """Derive the ADR-045 metadata mapping, omitting absent (None) values."""
    raw = extract_canonical_metadata(assignments)
    return {key: value for key, value in raw.items() if value is not None}


def _tag_assignments(
    db: Database,
    identities: Sequence[SongIdentity],
) -> dict[SongIdentity, tuple[SongTagAssignment, ...]]:
    """Batch-read tag assignments for many locators (single facade call)."""
    if not identities:
        return {}
    return dict(db.library.list_song_tags_for_songs(list(identities)))


def _hydrate_metadata(
    db: Database,
    songs: Sequence[Song],
    locators: Sequence[SongIdentity | None],
) -> list[Mapping[str, object]]:
    """Derive ADR-045 metadata for songs, preserving order and pass-through empties."""
    resolvable = [(song, locator) for song, locator in zip(songs, locators, strict=True) if locator is not None]
    metadata_by_song: dict[Song, Mapping[str, object]] = {}
    if resolvable:
        hydrated = hydrate_songs_with_metadata(db, [s for s, _ in resolvable], [locator for _, locator in resolvable])
        for hyd in hydrated:
            metadata_by_song[hyd.song] = hyd.metadata
    return [metadata_by_song.get(song, {}) for song in songs]


# ─────────────────────────────────────────────────────────────────────────
# Path / numeric / sort / pagination helpers
# ─────────────────────────────────────────────────────────────────────────


def _normalize_path(path: str) -> str:
    """Normalize a caller path for the song identity lookup."""
    return Path(path).as_posix().lstrip("./")


def _matches_folder_rel_path(normalized_path: str, folder_rel_path: str) -> bool:
    if folder_rel_path == "":
        return "/" not in normalized_path
    return normalized_path.startswith(f"{folder_rel_path}/")


def _sort_key(value: object) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.casefold())
    return (0, value)


def _metadata_sort_key(metadata: Mapping[str, object]) -> tuple[tuple[int, Any], tuple[int, Any], tuple[int, Any]]:
    """Casefolded ``(artist, album, title)`` ordering with missing values last."""
    return (
        _sort_key(metadata.get("artist")),
        _sort_key(metadata.get("album")),
        _sort_key(metadata.get("title")),
    )


def _numeric_value(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _path_parent(path_value: str) -> str | None:
    return path_value.rsplit("/", 1)[0] if "/" in path_value else ""


def _is_numeric_target_value(value: float | str) -> bool:
    """Whether a curated tag target value is numeric (int/float, non-bool)."""
    return is_numeric_tag_value(value)


def _tag_key_namespace(tag_key: str) -> str:
    """Return the persistence namespace for a search tag key.

    Nomarr ML keys carry a ``nom:`` prefix in their stored ``name`` and live in
    the ``nom`` namespace (see song_hydration_repo ``_expand_tag_rows``); every
    other key is an ordinary tag in the ``default`` namespace.
    """
    return "nom" if tag_key.startswith("nom:") else "default"


def _tags_by_name(db: Database, name: str) -> list[TagRef]:
    return list(db.library.list_tags(name=name, limit=None))


def _tags_by_name_value(db: Database, name: str, value: str) -> list[TagRef]:
    return [identity for identity in _tags_by_name(db, name) if identity.value == value]


def _activity_event(song: Song) -> tuple[int, _ACTIVITY_EVENT]:
    """Derive the most-recent activity timestamp and its event for a song."""
    scanned_at = song.scanned_at or 0
    last_tagged_at = song.last_tagged_at or 0
    if scanned_at == 0 and last_tagged_at == 0:
        return 0, "scanned"
    if scanned_at >= last_tagged_at:
        return scanned_at, "scanned"
    return last_tagged_at, "tagged"


# ─────────────────────────────────────────────────────────────────────────
# Scalar / aggregate helpers (unchanged contracts)
# ─────────────────────────────────────────────────────────────────────────


def count_recently_tagged(db: Database, window_seconds: int = 300) -> int:
    """Count songs tagged within the recent window (default 5 minutes)."""
    cutoff_ms = now_ms().value - window_seconds * 1000
    return db.library.count_recently_tagged(cutoff_ms)


def get_existing_file_paths(db: Database, library: Library, paths: list[str]) -> set[str]:
    """Return paths that already exist in the target library's songs table."""
    if not paths:
        return set()
    return set(db.library.list_existing_song_paths(library, paths))


def get_song_modified_times(db: Database) -> dict[str, int]:
    """Return absolute path to modified-time mapping for all files."""
    pairs = _all_songs_with_libraries(db)
    return {song.path: song.modified_time for song, _library_identity in pairs if isinstance(song.path, str)}


def get_all_library_paths(db: Database) -> list[str]:
    """Return all absolute library-file paths."""
    paths: list[str] = []
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        paths.extend(
            song.path
            for song in db.library.list_songs(library_identity, limit=DEFAULT_LIMIT)
            if isinstance(song.path, str)
        )
    return paths


def get_sample_normalized_path(db: Database) -> str | None:
    """Return one normalized_path from the library for diagnostic purposes."""
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        for song in db.library.list_songs(library_identity, limit=1):
            if isinstance(song.normalized_path, str) and song.normalized_path:
                return song.normalized_path
    return None


def detect_nd_path_prefix(db: Database, nd_path: str) -> str | None:
    """Detect the Navidrome prefix that should be stripped from absolute paths."""
    normalized_paths: list[str] = []
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        normalized_paths.extend(
            song.normalized_path
            for song in db.library.list_songs(library_identity, limit=DEFAULT_LIMIT)
            if isinstance(song.normalized_path, str) and song.normalized_path
        )
    best_match = next(
        (
            normalized_path
            for normalized_path in sorted(normalized_paths, key=len, reverse=True)
            if nd_path.endswith(normalized_path)
        ),
        None,
    )
    if best_match is None:
        return None
    return nd_path[: len(nd_path) - len(best_match)]


def get_folder_rel_paths(db: Database, library: Library) -> set[str]:
    """Get cached folder relative paths for one library."""
    return {folder.path for folder in db.library.list_folders_for_library(library) if isinstance(folder.path, str)}


# ─────────────────────────────────────────────────────────────────────────
# Single-song semantic lookups
# ─────────────────────────────────────────────────────────────────────────


def get_library_song(db: Database, path: str, library: Library | None = None) -> Song | None:
    """Get a semantic song by normalized or absolute path within an optional scope.

    Scoped lookups use the canonical normalized-path identity in the facade
    (``get_song_by_normalized_path``); unscoped lookups search all libraries by
    physical path. Returns a semantic ``Song`` or ``None`` — never a row.
    """
    if library is not None:
        normalized_path = _normalize_path(path)
        return db.library.get_song_by_normalized_path(_library_identity(library), normalized_path)
    return db.library.find_song_by_path_any_library(path)


def get_songs_by_paths_bulk(db: Database, paths: list[str]) -> dict[str, Song]:
    """Get multiple semantic songs keyed only by the original input path."""
    if not paths:
        return {}
    result: dict[str, Song] = {}
    for path in paths:
        song = get_library_song(db, path)
        if song is not None:
            result[path] = song
    return result


def find_move_candidate_by_chromaprint(db: Database, library: Library, chromaprint: str) -> Song | None:
    """Return the semantic song matching ``chromaprint``, or ``None`` (DB move detection)."""
    return db.library.find_library_song_by_chromaprint(library, chromaprint)


# ─────────────────────────────────────────────────────────────────────────
# Listing / filtering / paging (metadata-bearing carriers)
# ─────────────────────────────────────────────────────────────────────────


def list_songs(
    db: Database,
    limit: int = 100,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    library: Library | None = None,
) -> tuple[list[HydratedSong], int]:
    """List library songs with optional derived-metadata filters; returns (rows, total)."""
    if library is not None:
        library_identity = _library_identity(library)
        songs = db.library.list_songs(library_identity, limit=None)
        identities = [_song_identity(song, library_identity) for song in songs]
    else:
        # Materialize the complete cross-library set before filtering/paging.
        pairs = _all_songs_with_libraries(db)
        songs = [song for song, _ in pairs]
        identities = [_song_identity(song, library_identity) for song, library_identity in pairs]

    hydrated = hydrate_songs_with_metadata(db, songs, identities)

    def _matches(hydrated_song: HydratedSong) -> bool:
        if artist is not None and hydrated_song.metadata.get("artist") != artist:
            return False
        return not (album is not None and hydrated_song.metadata.get("album") != album)

    hydrated = [row for row in hydrated if _matches(row)]
    hydrated.sort(key=lambda row: _metadata_sort_key(row.metadata))
    total = len(hydrated)
    page = hydrated[offset : offset + limit]
    return page, total


def get_tagged_file_paths(db: Database) -> list[str]:
    """Return absolute physical paths for songs currently in the processed state."""
    candidates = db.library.list_songs_with_state(STATE_PROCESSED)
    return [candidate.song.path for candidate in candidates]


def search_songs_with_tags(
    db: Database,
    query_text: str = "",
    artist: str | None = None,
    album: str | None = None,
    tag_key: str | None = None,
    tag_value: str | None = None,
    tagged_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[TaggedSong], int]:
    """Search songs with tag/text filters; returns (songs, total_count).

    Candidate narrowing reproduces the previous set-intersection semantics over
    semantic ``Song`` values (equal ``Song`` dataclass values denote the same
    underlying row, so intersection is exact — no generated id is used).
    """
    candidate_songs: set[Song] | None = None

    def _intersect(new_songs: set[Song]) -> None:
        nonlocal candidate_songs
        candidate_songs = new_songs if candidate_songs is None else candidate_songs & new_songs

    if artist:
        _intersect(set(db.library.find_songs_with_tag_pattern("artist", f"%{artist}%")))
    if album:
        _intersect(set(db.library.find_songs_with_tag_pattern("album", f"%{album}%")))
    if query_text:
        q_pattern = f"%{query_text}%"
        if artist or album:
            _intersect(set(db.library.find_songs_with_tag_pattern("title", q_pattern)))
        else:
            matched: set[Song] = set()
            matched.update(db.library.find_songs_with_tag_pattern("title", q_pattern))
            for tag_name in ("artist", "album"):
                matched.update(db.library.find_songs_with_tag_pattern(tag_name, q_pattern))
            _intersect(matched)
    if tag_key:
        matching_tags = (
            _tags_by_name_value(db, tag_key, str(tag_value)) if tag_value is not None else _tags_by_name(db, tag_key)
        )
        tag_matched: set[Song] = set()
        for identity in matching_tags:
            tag_matched.update(db.library.find_songs_with_tag(identity, limit=None))
        _intersect(tag_matched)
    if tagged_only:
        processed = {candidate.song for candidate in db.library.list_songs_with_state(STATE_PROCESSED)}
        _intersect(processed)

    locators: list[SongIdentity | None]
    if candidate_songs is None:
        # No filters active — load the complete universe before pagination.
        songs = [song for song, _ in _all_songs_with_libraries(db)]
        locators = [_song_identity(song, library_identity) for song, library_identity in _all_songs_with_libraries(db)]
    elif not candidate_songs:
        return [], 0
    else:
        songs = list(candidate_songs)
        locators = _locators_for_songs(db, songs)

    metadata_by_song = dict(zip(songs, _hydrate_metadata(db, songs, locators), strict=True))
    ordered = sorted(songs, key=lambda song: _metadata_sort_key(metadata_by_song[song]))
    total = len(ordered)
    page_songs = ordered[offset : offset + limit]

    page_locators = [locators[songs.index(song)] for song in page_songs]
    assignments = _tag_assignments(db, [locator for locator in page_locators if locator is not None])
    page: list[TaggedSong] = []
    for song in page_songs:
        locator = page_locators[songs.index(song)]
        song_assignments = assignments.get(locator, ()) if locator is not None else ()
        page.append(
            TaggedSong(
                song=song,
                metadata=metadata_by_song[song],
                tags=_file_tags(song_assignments),
            )
        )
    return page, total


def get_recently_processed(
    db: Database,
    limit: int = 20,
    library: Library | None = None,
) -> list[RecentSong]:
    """Return recently processed songs ordered by activity descending as typed carriers."""
    library_identity = _library_identity(library) if library is not None else None
    candidates = db.library.list_songs_with_state(
        STATE_PROCESSED,
        library=library_identity,
        order_by_activity=True,
        limit=DEFAULT_LIMIT,
    )
    if not candidates:
        return []
    songs = [candidate.song for candidate in candidates]
    identities = [candidate.identity for candidate in candidates]
    metadata = [hyd.metadata for hyd in hydrate_songs_with_metadata(db, songs, identities)]
    result: list[RecentSong] = []
    for candidate, song_metadata in zip(candidates, metadata, strict=True):
        activity_at, activity_event = _activity_event(candidate.song)
        result.append(
            RecentSong(
                candidate=candidate,
                metadata=song_metadata,
                activity_at=activity_at,
                activity_event=activity_event,
            )
        )
    return result[:limit]


# ─────────────────────────────────────────────────────────────────────────
# Tag search / match carriers
# ─────────────────────────────────────────────────────────────────────────


def search_songs_by_tag(
    db: Database,
    tag_key: str,
    target_value: float | str,
    limit: int = 100,
    offset: int = 0,
) -> list[TagMatchedSong]:
    """Search songs by tag value with numeric-distance or exact-match semantics."""
    namespace = _tag_key_namespace(tag_key)
    if _is_numeric_target_value(target_value):
        identity = TagRef(name=tag_key, value=float(target_value), namespace=namespace)
        rows = db.library.find_songs_with_numeric_tag(identity, limit=limit, offset=offset)
        if not rows:
            return []
        songs = [match.song for match in rows]
        metadata = _hydrate_metadata(db, songs, _locators_for_songs(db, songs))
        result: list[TagMatchedSong] = []
        for match, song_metadata in zip(rows, metadata, strict=True):
            result.append(
                TagMatchedSong(
                    song=match.song,
                    metadata=song_metadata,
                    matched_tag=TagRef(name=tag_key, value=float(match.matched_tag), namespace=namespace),
                    distance=match.distance,
                )
            )
        return result

    identity = TagRef(name=tag_key, value=str(target_value), namespace=namespace)
    songs = list(db.library.find_songs_with_tag(identity, limit=None))
    if not songs:
        return []
    metadata = _hydrate_metadata(db, songs, _locators_for_songs(db, songs))
    ordered = sorted(range(len(songs)), key=lambda i: _metadata_sort_key(metadata[i]))
    page = ordered[offset : offset + limit]
    return [
        TagMatchedSong(
            song=songs[i],
            metadata=metadata[i],
            matched_tag=TagRef(name=tag_key, value=str(target_value), namespace=namespace),
            distance=0.0,
        )
        for i in page
    ]


def count_songs_by_tag(db: Database, tag_key: str, target_value: float | str) -> int:
    """Count songs matching a tag-value filter, scoped to the key's namespace."""
    namespace = _tag_key_namespace(tag_key)
    if _is_numeric_target_value(target_value):
        return db.library.count_songs_by_numeric_tag(tag_key, float(target_value), namespace=namespace)
    return db.library.count_songs_by_tag(tag_key, str(target_value), namespace=namespace)


def get_songs_by_chromaprint(db: Database, chromaprint: str, library: Library | None = None) -> list[Song]:
    """Return semantic songs matching a chromaprint fingerprint."""
    if library is not None:
        library_identity = _library_identity(library)
        return [song for song in db.library.list_songs(library_identity, limit=None) if song.chromaprint == chromaprint]
    matches: list[Song] = []
    for library in db.library.list_libraries():
        match = db.library.find_library_song_by_chromaprint(library, chromaprint)
        if match is not None:
            matches.append(match)
    return matches


def get_tracks_for_matching(db: Database, library: Library | None = None) -> list[TrackSong]:
    """Get typed track carriers for fuzzy playlist matching, optionally scoped."""
    pairs: list[tuple[Song, LibraryIdentity]] = []
    if library is not None:
        library_identity = _library_identity(library)
        pairs.extend(
            (song, library_identity) for song in db.library.list_tracks_for_matching(library, limit=DEFAULT_LIMIT)
        )
    else:
        for library in db.library.list_libraries():
            library_identity = _library_identity(library)
            pairs.extend(
                (song, library_identity) for song in db.library.list_tracks_for_matching(library, limit=DEFAULT_LIMIT)
            )
    if not pairs:
        return []
    songs = [song for song, _ in pairs]
    identities = [_song_identity(song, library_identity) for song, library_identity in pairs]
    metadata = [hyd.metadata for hyd in hydrate_songs_with_metadata(db, songs, identities)]
    assignments = _tag_assignments(db, identities)
    result: list[TrackSong] = []
    for (song, library_identity), song_metadata in zip(pairs, metadata, strict=True):
        identity = _song_identity(song, library_identity)
        song_assignments = assignments.get(identity, ())
        isrc = next((str(a.value) for a in song_assignments if a.name == "nom:isrc"), None)
        result.append(TrackSong(song=song, metadata=song_metadata, isrc=isrc))
    return result


# ─────────────────────────────────────────────────────────────────────────
# Folder / state-annotation helpers
# ─────────────────────────────────────────────────────────────────────────


def _state_tagged_songs(
    db: Database,
    songs: Sequence[Song],
    library_identity: LibraryIdentity,
) -> list[StateTaggedSong]:
    """Annotate semantic songs with their processed-state candidate membership."""
    if not songs:
        return []
    processed_candidates = {
        candidate.song.normalized_path: candidate
        for candidate in db.library.list_songs_with_state(STATE_PROCESSED, library=library_identity)
    }
    result: list[StateTaggedSong] = []
    for song in songs:
        candidate = processed_candidates.get(song.normalized_path)
        if candidate is not None:
            result.append(StateTaggedSong(candidate=candidate, has_tagged_state=True))
        else:
            identity = _song_identity(song, library_identity)
            result.append(
                StateTaggedSong(
                    candidate=SongStateCandidate(
                        identity=identity,
                        song=song,
                        states=(),
                    ),
                    has_tagged_state=False,
                )
            )
    return result


def get_songs_for_folder(db: Database, library: Library, folder_rel_path: str) -> dict[str, StateTaggedSong]:
    """Get ``StateTaggedSong`` values for a single folder, keyed by physical path."""
    library_identity = _library_identity(library)
    songs = db.library.list_songs_for_folder(library, folder_rel_path)
    return {
        state_tagged.candidate.song.path: state_tagged
        for state_tagged in _state_tagged_songs(db, songs, library_identity)
        if isinstance(state_tagged.candidate.song.path, str)
    }


def get_songs_for_folders(
    db: Database,
    library: Library,
    folder_rel_paths: list[str],
) -> dict[str, StateTaggedSong]:
    """Batch-fetch ``StateTaggedSong`` values for multiple folders keyed by physical path."""
    if not folder_rel_paths:
        return {}
    library_identity = _library_identity(library)
    songs = db.library.list_songs(library_identity, limit=None)
    folder_songs = [
        song
        for song in songs
        if any(_matches_folder_rel_path(song.normalized_path, folder_rel_path) for folder_rel_path in folder_rel_paths)
    ]
    return {
        state_tagged.candidate.song.path: state_tagged
        for state_tagged in _state_tagged_songs(db, folder_songs, library_identity)
        if isinstance(state_tagged.candidate.song.path, str)
    }


# ─────────────────────────────────────────────────────────────────────────
# Aggregate statistics / maintenance
# ─────────────────────────────────────────────────────────────────────────


def get_library_stats(db: Database, library: Library | None = None) -> dict[str, Any]:
    """Get aggregate library-song statistics (not a song document)."""
    if library is not None:
        library_identity = _library_identity(library)
        songs = db.library.list_songs(library_identity, limit=None)
        total_files = db.library.count_songs_for_library(library)
        identities = [_song_identity(song, library_identity) for song in songs]
        assignments = _tag_assignments(db, identities) if identities else {}
        artist_values: set[object] = set()
        album_values: set[object] = set()
        for song_assignments in assignments.values():
            artist_values.update(a.value for a in song_assignments if a.name == "artist")
            album_values.update(a.value for a in song_assignments if a.name == "album")
        total_artists = len(artist_values)
        total_albums = len(album_values)
    else:
        pairs = _all_songs_with_libraries(db)
        songs = [song for song, _ in pairs]
        total_files = len(songs)
        total_artists = len(_tags_by_name(db, "artist"))
        total_albums = len(_tags_by_name(db, "album"))

    result: dict[str, Any] = {
        "total_files": total_files,
        "total_artists": total_artists,
        "total_albums": total_albums,
        "total_duration": sum(_numeric_value(song.duration_seconds) for song in songs),
        "total_size": int(sum(_numeric_value(song.file_size) for song in songs)),
    }
    result["needs_tagging_count"] = count_untagged_files(db, library)
    return result


def get_library_counts(db: Database) -> dict[str, dict[str, int]]:
    """Return song and folder counts for all libraries, keyed by natural library name."""
    result: dict[str, dict[str, int]] = {}
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        songs = db.library.list_songs(library_identity, limit=None)
        folder_paths = {parent for song in songs if (parent := _path_parent(song.path)) is not None}
        result[library.name] = {
            "file_count": len(songs),
            "folder_count": len(folder_paths),
        }
    return result


def get_artist_album_frequencies(db: Database, limit: int) -> dict[str, list[tuple[str, int]]]:
    """Get artist/album frequency rows for analytics views."""
    frequencies = db.library.list_tag_value_frequencies(["artist", "album"], limit)
    return {
        "artist_rows": frequencies.get("artist", []),
        "album_rows": frequencies.get("album", []),
    }


def clear_library_data(db: Database) -> None:
    """Perform a destructive full reset, delegated to the single maintenance intent."""
    db.library.maintenance.reset_library_data()
