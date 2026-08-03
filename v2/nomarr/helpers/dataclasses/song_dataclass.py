"""Song dataclass used across Nomarr.

This module defines:
- Song: Canonical music file data container with internal representation of
  all fields stored on a song/track record.

The Song dataclass is the single source of truth for song data flowing
between layers. It contains:
- Identity and path fields (id, path, normalized_path, library_id, library_key)
- File attributes (file_size, modified_time, duration_seconds, chromaprint)
- Processing state (is_valid, tagged, scanned_at, last_tagged_at, etc.)
- Metadata cache fields derived from tags (artist, album, title, etc.)
- Tags via the canonical Tags container from tags_dataclass

Usage:
    from v2.nomarr.helpers.dataclasses.song_dataclass import Song
    from v2.nomarr.helpers.dataclasses.tags_dataclass import Tags, Tag
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dc_fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tags_dataclass import Tags

# ── DB field → Song field mapping ────────────────────────────────────────
# Maps data-store document keys to Song field names used by ``from_db_doc``.
# Every key on the left MUST have a corresponding Song field on the right.
# The import-time assertion at the bottom of this file enforces this.
_DOC_FIELD_MAP: dict[str, str] = {
    # Location
    "path": "path",
    "normalized_path": "normalized_path",
    "library": "library",  # set by hydration pass
    # File attributes
    "file_size": "file_size",
    "modified_time": "modified_time",
    "duration_seconds": "duration_seconds",
    "chromaprint": "chromaprint",
    # Timestamps (epoch ms)
    "scanned_at": "scanned_at",
    "last_tagged_at": "last_tagged_at",
    # Processing state
    "is_valid": "is_valid",
    "tagged": "tagged",
    "calibration_hash": "calibration_hash",
    "write_claimed_by": "write_claimed_by",
    "status": "status",
}

# Fields that require bool coercion from int (0/1).
# ``bool()`` is deliberately NOT used — the data-store contract is integer
# 0 or 1.  Any other value is a data-integrity violation and must raise.
_BOOL_DOC_FIELDS: frozenset[str] = frozenset({"is_valid", "tagged"})

# Fields that require ``_tuple_from_doc`` normalisation (list-of-values → sorted tuple).
_TUPLE_DOC_FIELDS: frozenset[str] = frozenset({"artists", "labels", "genres"})


@dataclass(frozen=True, slots=True, kw_only=True)
class Song:
    """Canonical music file (song/track) data container.

    Represents a single audio file with all its metadata, processing state,
    and associated nom: tags. Every field stored on the song data record
    is represented.

    The dataclass is frozen and slots-based: create a new ``Song`` instead
    of mutating an existing one. Use ``copy_with(...)`` for targeted updates.

    ``tags`` uses the ``Tags`` container from ``tags_dataclass``. When
    ``tags`` is ``None``, tags have not been loaded. A non-``None``
    ``Tags`` instance is always non-empty (enforced by ``Tags.__post_init__``).
    """

    # ── Location ──────────────────────────────────────────────────────
    path: str
    """Absolute filesystem path to the audio file."""

    normalized_path: str | None = None
    """Relative path used for folder hierarchy (e.g. ``"Artist/Album"``)."""

    library: str | None = None
    """Resolved owning library identifier (populated by hydration)."""

    # ── File attributes ───────────────────────────────────────────────
    file_size: int | None = None
    """File size in bytes.  Must be >= 0 when set."""

    modified_time: int | None = None
    """Filesystem modification time as epoch milliseconds.  Must be >= 0 when set."""

    duration_seconds: float | None = None
    """Audio duration in seconds (fractional).  Must be >= 0 when set."""

    chromaprint: str | None = None
    """AcoustID chromaprint fingerprint, or ``None`` if not computed."""

    # ── Processing state ──────────────────────────────────────────────
    is_valid: bool = False
    """Whether the file passed filesystem validation during scan."""

    tagged: bool = False
    """Whether the file has been tagged by the ML pipeline."""

    status: str | None = None
    """General file status string (rarely populated)."""

    scanned_at: int | None = None
    """Epoch milliseconds of the last scan that touched this file.  Must be >= 0 when set."""

    last_tagged_at: int | None = None
    """Epoch milliseconds when the file was last tagged.  Must be >= 0 when set."""

    calibration_hash: str | None = None
    """Hash of the calibration definition applied to this file, if any."""

    write_claimed_by: str | None = None
    """Worker ID that has claimed this file for tag writeback."""

    # ── Tags ──────────────────────────────────────────────────────────
    tags: Tags | None = None
    """Canonical tag container.

    ``None`` means tags have not been loaded (unloaded, unreadable, or
    missing).  A non-``None`` value is always non-empty — the ``Tags``
    constructor rejects empty collections.
    """

    def __post_init__(self) -> None:
        """Validate invariants on construction.

        Validation mirrors the rigour of ``tags_dataclass.Tag.__post_init__``:
        every invalid input raises ``ValueError`` or ``TypeError`` with a
        specific message.
        """
        # ── Identity / path ───────────────────────────────────────────

        if not self.path:
            raise ValueError("Song.path must not be empty")
        if not self.path.strip():
            raise ValueError("Song.path must not be blank")

    # ── Convenience ───────────────────────────────────────────────────

    @property
    def has_tags(self) -> bool:
        """``True`` when tags are loaded and non-empty."""
        return self.tags is not None

    @property
    def has_calibration(self) -> bool:
        """``True`` when a calibration hash has been applied to this file."""
        return self.calibration_hash is not None

    # ── Factory: from a raw DB document ────────────────────────────────
    # The field mapping between data-store document keys and Song fields is
    # defined in ``_DOC_FIELD_MAP`` at module level.  Two special cases
    # require extra handling:
    #   1. ``_BOOL_DOC_FIELDS`` — int (0/1) → bool coercion
    #   2. ``_TUPLE_DOC_FIELDS`` — list-of-values → sorted tuple

    @classmethod
    def from_db_doc(cls, doc: dict[str, Any], *, tags: Tags | None = None) -> Song:
        """Construct a ``Song`` from a raw data-store document.

        The mapping from document keys to ``Song`` fields is defined in
        ``_DOC_FIELD_MAP``.  New fields added to the data store must be
        added to that map for ``from_db_doc`` to surface them.

        Args:
            doc: Raw document dict from the data store.
            tags: Optional ``Tags`` instance (fetched separately).
                Pass ``None`` (the default) to leave tags unloaded.

        Returns:
            A fully populated ``Song`` instance.
        """
        kwargs: dict[str, Any] = {}

        for doc_key, song_field in _DOC_FIELD_MAP.items():
            value = doc.get(doc_key)
            if value is None:
                continue
            if song_field in _BOOL_DOC_FIELDS:
                if not isinstance(value, int) or value not in (0, 1):
                    raise TypeError(f"{doc_key!r} must be int 0 or 1 for bool coercion, got {type(value).__name__}")
                kwargs[song_field] = bool(value)
            elif song_field in _TUPLE_DOC_FIELDS:
                kwargs[song_field] = _tuple_from_doc(value)
            else:
                kwargs[song_field] = value

        kwargs["tags"] = tags
        return cls(**kwargs)

    # ── Factory: minimal construction ──────────────────────────────────

    @classmethod
    def from_path(cls, path: str, *, file_id: str | None = None, **kwargs: Any) -> Song:
        """Construct a minimal ``Song`` from a filesystem path.

        Args:
            path: Absolute path to the audio file.
            file_id: Optional record identifier (defaults to ``path`` when
                ``None``).  Pass the empty string ``""`` to explicitly
                leave the id unset.
            **kwargs: Any additional fields to set on the Song.

        Returns:
            A ``Song`` with only identity/location populated.
        """
        return cls(
            id=path if file_id is None else file_id,
            path=path,
            **kwargs,
        )

    # ── Targeted copy ──────────────────────────────────────────────────

    def copy_with(self, **overrides: Any) -> Song:
        """Return a new ``Song`` with the given fields replaced.

        All other fields are copied unchanged from this instance.

        Args:
            **overrides: Keyword arguments matching ``Song`` field names.

        Returns:
            A new frozen ``Song`` instance.

        Example:
            >>> updated = song.copy_with(tagged=True, artist="New Artist")
        """
        current = {f.name: getattr(self, f.name) for f in dc_fields(self)}
        current.update(overrides)
        return Song(**current)


# ── Internal helpers ────────────────────────────────────────────────────


def _tuple_from_doc(value: Any) -> tuple[str, ...]:
    """Normalise a list- or tuple-like value to a sorted tuple.

    Only ``list`` and ``tuple`` inputs are accepted.  Each contained value
    must be ``str``, ``int``, ``float``, or ``bool``.  Unexpected types
    raise ``TypeError`` with the offending type name — matching the rigour
    of ``tags_dataclass.Tag.__post_init__``.

    An empty list/tuple produces an empty tuple ``()``, preserving the
    distinction between "data was loaded and found nothing" and "data was
    never loaded" (``None``).  This matches ``Tags``'s rigour: empty data
    is still data.
    """
    if not isinstance(value, list | tuple):
        raise TypeError(f"_tuple_from_doc expects list or tuple, got {type(value).__name__}")
    result: list[str] = []
    for v in value:
        if not isinstance(v, str | int | float | bool):
            raise TypeError(f"_tuple_from_doc value must be str, int, float, or bool, got {type(v).__name__}")
        result.append(str(v))
    return tuple(sorted(result))


# ── Drift detection: _DOC_FIELD_MAP must stay in sync with Song ──────────
# Runs at import time.  If this assertion fires, a field was added to or
# removed from ``Song`` without updating ``_DOC_FIELD_MAP``.
_song_fields = {f.name for f in dc_fields(Song)}
_doc_to_song = set(_DOC_FIELD_MAP.values()) | {"tags"}
_assert_msg = (
    f"_DOC_FIELD_MAP drift: Song has {sorted(_song_fields - _doc_to_song)}, "
    f"map has extra {sorted(_doc_to_song - _song_fields)}"
)
assert _song_fields == _doc_to_song, _assert_msg
