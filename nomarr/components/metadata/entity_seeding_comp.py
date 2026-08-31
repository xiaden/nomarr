"""Entity seeding component - derive entities from raw metadata tags.

Derives entity/tag relationship mappings (artist, artists, album, title, label,
genre, year) from raw extraction metadata for callers that need
pre-prepared entity tags — e.g. the hydration intent via
:func:`extract_entity_tag_mapping`, and manual sync workflows.  This module
is compute-only: it never writes to the database.
"""

from typing import Any

from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment

_ENTITY_TAG_KEYS = ("artist", "artists", "album", "title", "label", "genre", "year")


def _extract_entity_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract entity-relevant tag keys from scan metadata.

    Args:
        metadata: Raw file metadata dict (from mutagen)

    Returns:
        Dict with only the entity tag keys

    """
    return {k: metadata.get(k) for k in _ENTITY_TAG_KEYS}


def _build_song_tag_entries(song_id: int, tags: dict[str, Any]) -> list[dict[str, Any]]:
    """Build song-tag entries from raw entity tags.

    Returns a list with zero or one entry. Each entry has ``"song_id"``
    and ``"tags"`` keys, where ``"tags"`` is a list of flat
    ``{name, value}`` payloads derived from the entity tag mappings:
    artist (primary) + artists (multi), album, title, label, genre, and
    year (coerced to int).

    Returns an empty list when the raw tags contain no entity fields.

    """
    tag_payloads: list[dict[str, Any]] = []

    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")

    # — artist (singular) —
    primary_artist: str | None = None
    if artist_raw:
        primary_artist = (artist_raw[0] if artist_raw else None) if isinstance(artist_raw, list) else artist_raw
    elif artists_raw:
        primary_artist = (artists_raw[0] if artists_raw else None) if isinstance(artists_raw, list) else artists_raw

    if primary_artist:
        tag_payloads.append({"name": "artist", "value": primary_artist})

    # — artists (multi) —
    all_artists: list[str] = []
    if artists_raw:
        all_artists = [str(a) for a in artists_raw if a] if isinstance(artists_raw, list) else [str(artists_raw)]
    elif primary_artist:
        all_artists = [str(primary_artist)]

    tag_payloads.extend({"name": "artists", "value": a} for a in all_artists)

    # — album (singular) —
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        tag_payloads.append({"name": "album", "value": album_str})

    # — title (singular) —
    title_raw = tags.get("title")
    if title_raw:
        title_str = title_raw[0] if isinstance(title_raw, list) else title_raw
        tag_payloads.append({"name": "title", "value": title_str})

    # — label (multi) —
    label_raw = tags.get("label")
    if label_raw:
        labels = [str(lbl) for lbl in label_raw if lbl] if isinstance(label_raw, list) else [str(label_raw)]
        tag_payloads.extend({"name": "label", "value": lbl} for lbl in labels)

    # — genre (multi) —
    genre_raw = tags.get("genre")
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]
        tag_payloads.extend({"name": "genre", "value": g} for g in genres)

    # — year (singular) —
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        tag_payloads.append({"name": "year", "value": year_int})

    if not tag_payloads:
        return []

    return [{"song_id": song_id, "tags": tag_payloads}]


def build_song_tag_assignments(song_id: int, tags: dict[str, Any]) -> list[SongTagAssignment]:
    """Map raw entity tags to domain assignment commands for one song.

    Compute-only: resolves nothing against the database. The caller resolves
    the song's :class:`SongIdentity` and persists through the sealed facade, so
    no raw tag payload dict ever crosses into the facade.

    Returns an empty list when the raw tags contain no entity fields.
    """
    entries = _build_song_tag_entries(song_id, tags)
    if not entries:
        return []
    return [SongTagAssignment(name=str(tag["name"]), value=tag["value"]) for entry in entries for tag in entry["tags"]]


def extract_entity_tag_mapping(metadata: dict[str, Any]) -> dict[str, list[str | int | float]]:
    """Return entity tag name → value-list mapping derived from raw metadata.

    Produces the shape expected by the hydration intent's ``entity_tags``
    member (``Mapping[str, Sequence[str | int | float]]``): keys are entity tag
    names (artist, artists, album, title, label, genre, year) and values are
    the corresponding lists of tag values. Includes the canonical title tag
    used by read-side metadata hydration. Reuses the canonical entity-tag
    derivation from :func:`_build_song_tag_entries`; does not touch the DB.

    Returns an empty dict when the metadata carries no entity fields.

    """
    entity_tags = _extract_entity_tags(metadata)
    entries = _build_song_tag_entries(0, entity_tags)
    if not entries:
        return {}
    mapping: dict[str, list[str | int | float]] = {}
    for entry in entries:
        for tag in entry["tags"]:
            mapping.setdefault(str(tag["name"]), []).append(tag["value"])
    return mapping
