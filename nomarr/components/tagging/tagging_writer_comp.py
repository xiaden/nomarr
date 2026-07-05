"""Format-aware tag writers with atomic safe-write support."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path as PathLib
from typing import TYPE_CHECKING

import mutagen
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from nomarr.components.tagging.safe_write_comp import SafeWriteResult, safe_write_tags
from nomarr.helpers.dto.path_dto import LibraryPath

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from nomarr.helpers.dto.tags_dto import Tags


def _to_text_value(value: object) -> str:
    """Convert a tag value to a stable, locale-independent text representation."""
    if isinstance(value, int | float):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _ns_key(key: str, ns_prefix: str) -> str:
    """Ensure 'key' is namespaced with 'ns_prefix' exactly once."""
    if not ns_prefix:
        return key
    prefix = f"{ns_prefix}:"
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"


class _MP3Writer:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom") -> None:
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
            desc_val = getattr(frame, "desc", "")
            if isinstance(desc_val, str) and desc_val.startswith(f"{self.ns_prefix}:"):
                to_delete.append(key)
        for key_to_delete in to_delete:
            with contextlib.suppress(Exception):
                del id3[key_to_delete]

    def write(self, path: LibraryPath, tags: Mapping[str, object]) -> None:
        """Write tags as ID3 TXXX frames."""
        if not path.is_valid():
            msg = f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}"
            raise ValueError(msg)

        path_str = str(path.absolute)
        try:
            try:
                id3 = ID3(path_str)
            except ID3NoHeaderError:
                id3 = ID3()

            self._clear_ns(id3)

            for tag_key, tag_value in (tags or {}).items():
                ns_key = _ns_key(tag_key, self.ns_prefix)
                if isinstance(tag_value, list) and all(isinstance(x, str) for x in tag_value):
                    id3.add(TXXX(encoding=3, desc=ns_key, text=tag_value))
                else:
                    txt = _to_text_value(tag_value)
                    id3.add(TXXX(encoding=3, desc=ns_key, text=[txt]))

            id3.save(path_str, v2_version=4)
        except MutagenError as e:
            msg = f"MP3 write failed: {e}"
            raise RuntimeError(msg) from e


class _MP4Writer:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom") -> None:
        self.overwrite = overwrite
        self.ns_prefix = ns_prefix

    @staticmethod
    def _ff_key(ns_key: str) -> str:
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
        for key_to_delete in to_delete:
            with contextlib.suppress(Exception):
                del mp4.tags[key_to_delete]

    def write(self, path: LibraryPath, tags: Mapping[str, object]) -> None:
        """Write tags as iTunes freeform atoms."""
        if not path.is_valid():
            msg = f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}"
            raise ValueError(msg)

        path_str = str(path.absolute)
        try:
            mp4 = MP4(path_str)
            if mp4.tags is None:
                mp4.add_tags()

            self._clear_ns(mp4)

            if not isinstance(mp4.tags, dict):
                logging.getLogger(__name__).warning("MP4 tags is not a dict for %s", path_str)
                return

            for tag_key, tag_value in (tags or {}).items():
                ns_key = _ns_key(tag_key, self.ns_prefix)
                atom_key = self._ff_key(ns_key)
                if isinstance(tag_value, list) and all(isinstance(x, str) for x in tag_value):
                    mp4.tags[atom_key] = [MP4FreeForm(x.encode("utf-8")) for x in tag_value]
                else:
                    payload = _to_text_value(tag_value).encode("utf-8")
                    mp4.tags[atom_key] = [MP4FreeForm(payload)]

            mp4.save()
        except MutagenError as e:
            msg = f"MP4/M4A write failed: {e}"
            raise RuntimeError(msg) from e


class _VorbisWriter:
    def __init__(self, overwrite: bool = True, ns_prefix: str = "nom") -> None:
        self.overwrite = overwrite
        self.ns_prefix = ns_prefix

    @staticmethod
    def _vorbis_key(ns_key: str) -> str:
        """Convert namespaced key to Vorbis-compatible format."""
        return ns_key.replace(":", "_").replace("-", "_").upper()

    def _clear_ns(self, vorbis_file: mutagen.FileType) -> None:
        """Remove existing namespaced tags if overwriting."""
        if not self.overwrite:
            return
        if vorbis_file.tags is None:
            return

        prefix = self._vorbis_key(f"{self.ns_prefix}:")
        to_delete = [k for k in list(vorbis_file.tags.keys()) if k.upper().startswith(prefix)]

        for key_to_delete in to_delete:
            with contextlib.suppress(Exception):
                del vorbis_file.tags[key_to_delete]

    def write(self, path: LibraryPath, tags: Mapping[str, object]) -> None:
        """Write tags as Vorbis comments."""
        if not path.is_valid():
            msg = f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}"
            raise ValueError(msg)

        path_str = str(path.absolute)
        try:
            ext = path_str.lower().rsplit(".", 1)[-1]
            if ext == "flac":
                vorbis_file: mutagen.FileType = FLAC(path_str)
            elif ext == "ogg":
                vorbis_file = OggVorbis(path_str)
            elif ext == "opus":
                vorbis_file = OggOpus(path_str)
            else:
                msg = f"Unsupported Vorbis file type: .{ext}"
                raise RuntimeError(msg)

            if vorbis_file.tags is None:
                vorbis_file.add_tags()

            self._clear_ns(vorbis_file)

            if not isinstance(vorbis_file.tags, dict):
                logging.getLogger(__name__).warning("Vorbis tags is not a dict for %s", path_str)
                return

            for tag_key, tag_value in (tags or {}).items():
                ns_key = _ns_key(tag_key, self.ns_prefix)
                vorbis_key = self._vorbis_key(ns_key)

                if isinstance(tag_value, list) and all(isinstance(x, str) for x in tag_value):
                    vorbis_file.tags[vorbis_key] = tag_value
                else:
                    vorbis_file.tags[vorbis_key] = [_to_text_value(tag_value)]

            vorbis_file.save()
        except MutagenError as e:
            msg = f"Vorbis write failed: {e}"
            raise RuntimeError(msg) from e


class TagWriter:
    """Format-aware tag writer with namespace support and safe-write capability."""

    def __init__(self, overwrite: bool = True, namespace: str = "nom") -> None:
        self.overwrite = overwrite
        self.namespace = namespace
        self._mp3 = _MP3Writer(overwrite=overwrite, ns_prefix=namespace)
        self._mp4 = _MP4Writer(overwrite=overwrite, ns_prefix=namespace)
        self._vorbis = _VorbisWriter(overwrite=overwrite, ns_prefix=namespace)

    def _write_to_path(self, path_str: str, tags: Mapping[str, object]) -> None:
        """Write tags to a temp file path using the appropriate format writer."""
        temp_lib_path = LibraryPath(relative="", absolute=PathLib(path_str), library_id=None, status="valid")

        ext = path_str.lower().rsplit(".", 1)[-1]
        if ext == "mp3":
            self._mp3.write(temp_lib_path, tags)
        elif ext in ("m4a", "mp4", "m4b"):
            self._mp4.write(temp_lib_path, tags)
        elif ext in ("flac", "ogg", "opus"):
            self._vorbis.write(temp_lib_path, tags)
        else:
            msg = f"Unsupported file type for writing: .{ext}"
            raise RuntimeError(msg)

    def write(self, path: LibraryPath, tags: Tags) -> None:
        """Write tags directly to file (no safety verification)."""
        if not path.is_valid():
            msg = f"Cannot write tags to invalid path ({path.status}): {path.absolute} - {path.reason}"
            raise ValueError(msg)

        tags_dict = tags.to_dict()

        ext = str(path.absolute).lower().rsplit(".", 1)[-1]
        if ext == "mp3":
            self._mp3.write(path, tags_dict)
        elif ext in ("m4a", "mp4", "m4b"):
            self._mp4.write(path, tags_dict)
        elif ext in ("flac", "ogg", "opus"):
            self._vorbis.write(path, tags_dict)
        else:
            msg = f"Unsupported file type for writing: .{ext}"
            raise RuntimeError(msg)

    def write_safe(
        self,
        path: LibraryPath,
        tags: Tags,
        library_root: Path,
        expected_mtime_ms: int,
    ) -> SafeWriteResult:
        """Write tags using atomic copy-modify-verify-replace to prevent corruption."""
        if not path.is_valid():
            return SafeWriteResult(success=False, error=f"Invalid path: {path.reason}")

        tags_dict = tags.to_dict()

        def write_fn(temp_path: PathLib) -> None:
            self._write_to_path(str(temp_path), tags_dict)

        return safe_write_tags(path, library_root, write_fn, expected_mtime_ms)
