"""Track matcher for matching playlist tracks against library.

Implements tiered matching strategy:
1. ISRC exact match (highest confidence)
2. Title + Artist exact match (normalized)
3. Fuzzy match with configurable threshold
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from nomarr.components.playlist_import.metadata_normalizer_comp import (
    normalize_artist,
    normalize_title,
)
from nomarr.helpers.dto.playlist_import_dto import MatchedFileInfo, MatchResult, PlaylistTrackInput

logger = logging.getLogger(__name__)

FUZZY_HIGH_THRESHOLD = 85
FUZZY_LOW_THRESHOLD = 70


@dataclass
class LibraryTrack:
    """A track from the library database for matching purposes.

    Contains normalized versions of metadata for efficient comparison.
    """

    file_id: str
    file_path: str
    title: str
    artist: str
    album: str | None
    isrc: str | None
    # Pre-normalized versions for matching
    normalized_title: str
    normalized_artist: str

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> LibraryTrack:
        """Create LibraryTrack from database row.

        Expected row keys: _id, path, title, artist, album, isrc
        """
        return cls(
            file_id=row.get("_id", ""),
            file_path=row.get("path", ""),
            title=row.get("title", ""),
            artist=row.get("artist", ""),
            album=row.get("album"),
            isrc=row.get("isrc"),
            normalized_title=normalize_title(row.get("title", "")),
            normalized_artist=normalize_artist(row.get("artist", "")),
        )


def _to_file_info(lib_track: LibraryTrack) -> MatchedFileInfo:
    """Convert a LibraryTrack to a MatchedFileInfo for API responses."""
    return MatchedFileInfo(
        path=lib_track.file_path,
        file_id=lib_track.file_id,
        title=lib_track.title,
        artist=lib_track.artist,
        album=lib_track.album,
    )


def match_track(
    input_track: PlaylistTrackInput,
    library_tracks: list[LibraryTrack],
) -> MatchResult:
    """Match a single playlist track against library tracks.

    Tries matching in order of confidence: ISRC, exact normalized metadata,
    then fuzzy matching with artist verification.
    """
    if not library_tracks:
        return MatchResult(
            input_track=input_track,
            status="not_found",
            confidence=0.0,
        )

    input_title_norm = normalize_title(input_track.title)
    input_artist_norm = normalize_artist(input_track.artist)

    if input_track.isrc:
        for lib_track in library_tracks:
            if lib_track.isrc and lib_track.isrc.upper() == input_track.isrc.upper():
                return MatchResult(
                    input_track=input_track,
                    status="exact_isrc",
                    confidence=1.0,
                    matched_file=_to_file_info(lib_track),
                )

    for lib_track in library_tracks:
        if lib_track.normalized_title == input_title_norm and lib_track.normalized_artist == input_artist_norm:
            return MatchResult(
                input_track=input_track,
                status="exact_metadata",
                confidence=0.95,
                matched_file=_to_file_info(lib_track),
            )

    return _fuzzy_match(input_track, input_title_norm, input_artist_norm, library_tracks)


def _fuzzy_match(
    input_track: PlaylistTrackInput,
    input_title_norm: str,
    input_artist_norm: str,
    library_tracks: list[LibraryTrack],
) -> MatchResult:
    """Perform fuzzy matching when exact match fails.

    Uses token_sort_ratio with title weighted 70% and artist 30%.
    """
    candidates: list[tuple[float, LibraryTrack]] = []

    for lib_track in library_tracks:
        title_score = fuzz.token_sort_ratio(input_title_norm, lib_track.normalized_title)
        artist_score = fuzz.token_sort_ratio(input_artist_norm, lib_track.normalized_artist)
        combined_score = (title_score * 0.7) + (artist_score * 0.3)

        if combined_score >= FUZZY_LOW_THRESHOLD:
            candidates.append((combined_score, lib_track))

    if not candidates:
        return MatchResult(
            input_track=input_track,
            status="not_found",
            confidence=0.0,
        )

    candidates.sort(key=lambda x: x[0], reverse=True)

    best_score, best_match = candidates[0]

    alt_infos: list[MatchedFileInfo] = []
    if len(candidates) > 1:
        second_score = candidates[1][0]
        if best_score - second_score < 5:
            alt_infos = [_to_file_info(c[1]) for c in candidates[1:4]]

    if best_score >= FUZZY_HIGH_THRESHOLD:
        if alt_infos:
            return MatchResult(
                input_track=input_track,
                status="ambiguous",
                confidence=best_score / 100.0,
                matched_file=_to_file_info(best_match),
                alternatives=tuple(alt_infos),
            )
        return MatchResult(
            input_track=input_track,
            status="fuzzy",
            confidence=best_score / 100.0,
            matched_file=_to_file_info(best_match),
        )
    return MatchResult(
        input_track=input_track,
        status="ambiguous",
        confidence=best_score / 100.0,
        matched_file=_to_file_info(best_match),
        alternatives=tuple(alt_infos),
    )


def match_tracks(
    input_tracks: list[PlaylistTrackInput],
    library_tracks: list[LibraryTrack],
) -> list[MatchResult]:
    """Match multiple playlist tracks against library, preserving input order."""
    return [match_track(track, library_tracks) for track in input_tracks]
