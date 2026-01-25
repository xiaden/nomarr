#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Writers (fixed)
#  MP3 (ID3 TXXX) and MP4/M4A (iTunes freeform) tag writer
#  - Removes misuse of flatten_json (was a JSON string, not a mapping)
#  - Avoids calling util.namespaced(key, ns) (util only accepts key)
#  - Adds local, safe namespacing helper with double-namespace guard
#  - Preserves full-precision numeric string writes
# ======================================================================

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mutagen import MutagenError

from nomarr.helpers.dto.tags_dto import Tags

if TYPE_CHECKING:
    from nomarr.components.tagging.safe_write_comp import SafeWriteResult
    from nomarr.helpers.dto.path_dto import LibraryPath
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis


def _to_text_value(v: Any) -> str:
    """
    Convert a value to a text representation without losing numeric precision.
    - Numbers: write via JSON to keep a stable, locale-independent representation
    - Dict/List: JSON encode compactly
    - Everything else: str()
    """
    if isinstance(v, int | float):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _ns_key(key: str, ns_prefix: str) -> str:
    """
    Ensure 'key' is namespaced with 'ns_prefix' exactly once.

    Examples:
      _ns_key("yamnet_happy", "essentia")         -> "essentia:yamnet_happy"
      _ns_key("essentia:yamnet_happy", "essentia") -> "essentia:yamnet_happy" (unchanged)
      _ns_key("otherns:key", "essentia")           -> "essentia:otherns:key" (do not strip)
    """
    if not ns_prefix:
        return key
    prefix = f"{ns_prefix}:"
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"


# ----------------------------------------------------------------------
# MP3 (ID3 v2.x) writer
# ----------------------------------------------------------------------
class _MP3Writer:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom"):
        self.overwrite = overwrite
        self.ns_prefix = ns_prefix

    def _clear_ns(self, id3: ID3) -> None:
        """Remove existing namespaced TXXX frames if overwriting."""
        if not self.overwrite:
            return
        to_delete = []
        for key, frame in id3.items():
            if not isinstance(frame, TXXX):
                continue
            # TXXX(desc=...) holds our "<ns>:<key>"
            if isinstance(frame.desc, str) and frame.desc.startswith(f"{self.ns_prefix}:"):  # type: ignore[attr-defined]
                to_delete.append(key)
        for k in to_delete:
            try:
                del id3[k]
            except Exception:
                # Silently continue on any oddities in old tags
                pass

    def write(self, path: LibraryPath, tags: dict[str, Any]) -> None:
        """Write tags as ID3 TXXX frames (one save per file)."""
        # Enforce validation before file operations
        if not path.is_valid():
            raise ValueError(f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}")

        path_str = str(path.absolute)
        try:
            try:
                id3 = ID3(path_str)
            except ID3NoHeaderError:
                id3 = ID3()

            self._clear_ns(id3)

            # Expect a flat dict of keys -> values.
            for k, v in (tags or {}).items():
                ns_key = _ns_key(k, self.ns_prefix)
                # Allow multi-value tags when provided a list of strings
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    id3.add(TXXX(encoding=3, desc=ns_key, text=v))
                else:
                    txt = _to_text_value(v)
                    id3.add(TXXX(encoding=3, desc=ns_key, text=[txt]))

            id3.save(path_str, v2_version=4)  # Use ID3v2.4 for proper multi-value support
        except MutagenError as e:
            raise RuntimeError(f"MP3 write failed: {e}") from e


# ----------------------------------------------------------------------
# MP4/M4A (iTunes freeform atoms) writer
# ----------------------------------------------------------------------
class _MP4Writer:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom"):
        self.overwrite = overwrite
        self.ns_prefix = ns_prefix

    @staticmethod
    def _ff_key(ns_key: str) -> str:
        """
        Build the iTunes freeform key:
          '----:com.apple.iTunes:<ns_key>'
        where ns_key is '<namespace>:<key>'.
        """
        return f"----:com.apple.iTunes:{ns_key}"

    def _clear_ns(self, mp4: MP4) -> None:
        """Remove existing namespaced freeform atoms if overwriting."""
        if not self.overwrite:
            return
        if mp4.tags is None:
            return
        to_delete: Iterable[str] = [
            k
            for k in list(mp4.tags.keys())
            if isinstance(k, str) and k.startswith(f"----:com.apple.iTunes:{self.ns_prefix}:")
        ]
        for k in to_delete:
            try:
                del mp4.tags[k]
            except Exception:
                # If a malformed key exists, ignore and continue
                pass

    def write(self, path: LibraryPath, tags: dict[str, Any]) -> None:
        """Write tags as iTunes freeforms with UTF-8 payloads."""
        if not path.is_valid():
            raise ValueError(f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}")

        path_str = str(path.absolute)
        try:
            mp4 = MP4(path_str)
            if mp4.tags is None:
                mp4.add_tags()

            self._clear_ns(mp4)

            for k, v in (tags or {}).items():
                ns_key = _ns_key(k, self.ns_prefix)
                atom_key = self._ff_key(ns_key)
                # Multi-value support: list of strings -> multiple freeform atoms
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    mp4.tags[atom_key] = [MP4FreeForm(x.encode("utf-8")) for x in v]  # type: ignore[index]
                else:
                    payload = _to_text_value(v).encode("utf-8")
                    mp4.tags[atom_key] = [MP4FreeForm(payload)]  # type: ignore[index]

            mp4.save()
        except MutagenError as e:
            raise RuntimeError(f"MP4/M4A write failed: {e}") from e


# ----------------------------------------------------------------------
# FLAC/OGG/Opus (Vorbis comments) writer
# ----------------------------------------------------------------------
class _VorbisWriter:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom"):
        self.overwrite = overwrite
        self.ns_prefix = ns_prefix

    @staticmethod
    def _vorbis_key(ns_key: str) -> str:
        """
        Convert namespaced key to Vorbis-compatible format.
        Replace ':' and '-' with '_', then uppercase.

        Examples:
          'essentia:mood-strict' -> 'ESSENTIA_MOOD_STRICT'
          'essentia:yamnet_happy' -> 'ESSENTIA_YAMNET_HAPPY'
        """
        return ns_key.replace(":", "_").replace("-", "_").upper()

    def _clear_ns(self, vorbis_file) -> None:
        """Remove existing namespaced tags if overwriting."""
        if not self.overwrite:
            return
        if vorbis_file.tags is None:
            return

        # Vorbis tags are case-insensitive, but stored keys may vary
        prefix = self._vorbis_key(f"{self.ns_prefix}:")
        to_delete = [k for k in list(vorbis_file.tags.keys()) if k.upper().startswith(prefix)]

        for k in to_delete:
            try:
                del vorbis_file.tags[k]
            except Exception:
                pass

    def write(self, path: LibraryPath, tags: dict[str, Any]) -> None:
        """Write tags as Vorbis comments (native multi-value support)."""
        if not path.is_valid():
            raise ValueError(f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}")

        path_str = str(path.absolute)
        try:
            # Detect file type
            ext = path_str.lower().rsplit(".", 1)[-1]
            if ext == "flac":
                vorbis_file = FLAC(path_str)
            elif ext == "ogg":
                vorbis_file = OggVorbis(path_str)  # type: ignore[assignment]
            elif ext == "opus":
                vorbis_file = OggOpus(path_str)  # type: ignore[assignment]
            else:
                raise RuntimeError(f"Unsupported Vorbis file type: .{ext}")

            if vorbis_file.tags is None:
                vorbis_file.add_tags()

            self._clear_ns(vorbis_file)

            for k, v in (tags or {}).items():
                ns_key = _ns_key(k, self.ns_prefix)
                vorbis_key = self._vorbis_key(ns_key)

                # Vorbis natively supports multiple values - just assign a list
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    vorbis_file.tags[vorbis_key] = v  # type: ignore[index]
                else:
                    vorbis_file.tags[vorbis_key] = _to_text_value(v)  # type: ignore[index]

            vorbis_file.save()
        except MutagenError as e:
            raise RuntimeError(f"Vorbis write failed: {e}") from e


# ----------------------------------------------------------------------
# Public, format-aware writer
# ----------------------------------------------------------------------
class TagWriter:
    """
    Format-aware tag writer that respects:
      - overwrite: if True, clears only existing '<namespace>:' tags before writing
      - full precision: numeric values are written as unrounded strings
      - namespace: every key is written as '<namespace>:<key>' exactly once
    """

    def __init__(self, overwrite: bool = True, namespace: str = "nom"):
        self.overwrite = overwrite
        self.namespace = namespace
        self._mp3 = _MP3Writer(overwrite=overwrite, ns_prefix=namespace)
        self._mp4 = _MP4Writer(overwrite=overwrite, ns_prefix=namespace)
        self._vorbis = _VorbisWriter(overwrite=overwrite, ns_prefix=namespace)

    def _write_to_path(self, path_str: str, tags: dict[str, Any]) -> None:
        """Internal write method that works with string paths (for temp files)."""
        from pathlib import Path as PathLib

        from nomarr.helpers.dto.path_dto import LibraryPath

        # Create a minimal LibraryPath for internal writers
        # Status is "valid" since we're writing to a known good temp file
        temp_lib_path = LibraryPath(
            relative="",
            absolute=PathLib(path_str),
            library_id=None,
            status="valid",
        )

        ext = path_str.lower().rsplit(".", 1)[-1]
        if ext == "mp3":
            self._mp3.write(temp_lib_path, tags)
        elif ext in ("m4a", "mp4", "m4b"):
            self._mp4.write(temp_lib_path, tags)
        elif ext in ("flac", "ogg", "opus"):
            self._vorbis.write(temp_lib_path, tags)
        else:
            raise RuntimeError(f"Unsupported file type for writing: .{ext}")

    def write(self, path: LibraryPath, tags: Tags) -> None:
        """Write tags directly to file (no safety verification)."""
        if not path.is_valid():
            raise ValueError(f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}")

        # Convert Tags DTO to dict for internal writers
        tags_dict = tags.to_dict()

        ext = str(path.absolute).lower().rsplit(".", 1)[-1]
        if ext == "mp3":
            self._mp3.write(path, tags_dict)
        elif ext in ("m4a", "mp4", "m4b"):
            self._mp4.write(path, tags_dict)
        elif ext in ("flac", "ogg", "opus"):
            self._vorbis.write(path, tags_dict)
        else:
            raise RuntimeError(f"Unsupported file type for writing: .{ext}")

    def write_safe(
        self,
        path: LibraryPath,
        tags: Tags,
        library_root: Path,
        chromaprint: str,
    ) -> SafeWriteResult:
        """
        Write tags using atomic copy-modify-verify-replace pattern.

        This prevents file corruption if a crash occurs during write.
        Verifies audio content hasn't changed by comparing chromaprints.

        Args:
            path: LibraryPath to the file to modify
            tags: Tags DTO to write
            library_root: Root path of the library (for temp folder)
            chromaprint: Chromaprint of original file for verification

        Returns:
            SafeWriteResult with success status and folder_mtime_changed flag

        The caller should always update folder mtime after a successful write
        since all write strategies modify folder mtime.
        """
        from pathlib import Path as PathLib

        from nomarr.components.tagging.safe_write_comp import SafeWriteResult, safe_write_tags

        if not path.is_valid():
            return SafeWriteResult(
                success=False,
                error=f"Invalid path: {path.reason}",
            )

        # Convert Tags DTO to dict for internal writer
        tags_dict = tags.to_dict()

        def write_fn(temp_path: PathLib) -> None:
            self._write_to_path(str(temp_path), tags_dict)

        return safe_write_tags(path, library_root, chromaprint, write_fn)
