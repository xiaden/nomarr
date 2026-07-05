"""M3U playlist building and file output.

Stateless functions for constructing M3U content with relative paths
and saving playlist files to disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Characters that are unsafe in filenames on both Unix and Windows.
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def build_m3u(
    playlist_name: str,
    files: list[dict[str, object]],
    ordered_ids: list[str],
    library_root: str,
) -> str:
    """Build M3U playlist content preserving the order of requested IDs.

    Paths are emitted relative to *library_root* for portability.
    """
    root = library_root.replace("\\", "/").rstrip("/") + "/"

    files_by_id: dict[str, dict[str, object]] = {str(f["_id"]): f for f in files}

    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{playlist_name}",
        "",
    ]

    for fid in ordered_ids:
        file_doc = files_by_id.get(fid)
        if file_doc is None:
            continue

        abs_path = str(file_doc.get("path", "")).replace("\\", "/")
        if abs_path.startswith(root):
            rel_path = abs_path[len(root) :]
        else:
            rel_path = abs_path

        artist = str(file_doc.get("artist", "Unknown"))
        title = str(file_doc.get("title", "")) or rel_path.rsplit("/", 1)[-1]
        duration_raw = file_doc.get("duration_seconds")
        duration_s = int(float(str(duration_raw))) if duration_raw is not None else -1

        lines.append(f"#EXTINF:{duration_s},{artist} - {title}")
        lines.append(rel_path)

    return "\n".join(lines) + "\n"


def save_m3u(
    library_root: str,
    m3u_output_path: str,
    playlist_name: str,
    m3u_content: str,
) -> str:
    """Write M3U content to a file inside the library.

    The file is saved as ``{library_root}/{m3u_output_path}/{safe_name}.m3u``.
    Unsafe filename characters are replaced with underscores.
    Returns the absolute path of the saved file.
    """
    safe_name = _UNSAFE_FILENAME_RE.sub("_", playlist_name).strip(". ")
    if not safe_name:
        safe_name = "playlist"

    out_dir = Path(library_root) / m3u_output_path
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"{safe_name}.m3u"
    out_file.write_text(m3u_content, encoding="utf-8")
    logger.info("M3U playlist saved to %s", out_file)
    return str(out_file)
