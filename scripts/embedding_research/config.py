"""
Global configuration for the embedding research package.
All paths are written for execution inside the nomarr devcontainer.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# ── nomarr package on the container path ─────────────────────────────────────
NOMARR_APP = Path("/app")
WORKSPACE = Path("/workspace")

MEDIA_ROOT = WORKSPACE / ".devcontainer/test-media"
OUTPUT_ROOT = WORKSPACE / "scripts/outputs/embedding_research"

# ── Output paths ──────────────────────────────────────────────────────────────
# Raw patch sidecars stay on disk (not in DuckDB) because storing
# [n_patches, 1280] float32 arrays for 2386 songs would bloat the DB.
PATCHES_DIR = OUTPUT_ROOT / "patches"
REPORT_DIR = OUTPUT_ROOT / "report"

# Allow overriding the DB path via env var so the run can use a fast local
# filesystem (e.g. /tmp) instead of the slow 9p Windows mount.
# Example: RESEARCH_DB_PATH=/tmp/research.duckdb
DB_PATH = Path(os.environ.get("RESEARCH_DB_PATH", str(OUTPUT_ROOT / "research.duckdb")))

# ── Backbone model registry ───────────────────────────────────────────────────
BACKBONES: dict[str, dict] = {
    "effnet": {
        "path": str(NOMARR_APP / "models/effnet/embeddings/discogs-effnet-bsdynamic-1.onnx"),
        "embed_dim": 1280,
        "backbone_name": "effnet",  # arg for preprocess_for_backbone
        "vram_limit_bytes": 3_748_659_200,  # match musicnn; production probe was ~450MB but headroom needed
    },
    "musicnn": {
        "path": str(NOMARR_APP / "models/musicnn/embeddings/msd-musicnn-1.onnx"),
        "embed_dim": 200,
        "backbone_name": "musicnn",
        "vram_limit_bytes": 3_748_659_200,  # production probe value
    },
}

# VRAM budget for all binary head classifiers (softmax/*.onnx).
# Production probe measured every head at 20761804 bytes.
HEAD_VRAM_BYTES: int = 20_761_804


# ── Head model registry ───────────────────────────────────────────────────────
def _discover_heads() -> dict[str, dict[str, str]]:
    """Returns {backbone: {head_name: onnx_path}}."""
    result: dict[str, dict[str, str]] = {b: {} for b in BACKBONES}
    for backbone in BACKBONES:
        heads_dir = NOMARR_APP / "models" / backbone / "heads" / "softmax"
        if heads_dir.exists():
            for f in sorted(heads_dir.glob("*.onnx")):
                # e.g. timbre-discogs-effnet-1.onnx  ->  "timbre"
                head_name = f.stem.split("-")[0]
                result[backbone][head_name] = str(f)
    return result


HEADS: dict[str, dict[str, str]] = _discover_heads()

# Human-readable labels for binary head outputs (index -> label).
HEAD_LABELS: dict[str, list[str]] = {
    "timbre": ["bright", "dark"],
    "approachability_2c": ["approachable", "non-approachable"],
    "engagement_2c": ["engaging", "non-engaging"],
    "danceability": ["not_danceable", "danceable"],
    "gender": ["female", "male"],
    "mood_aggressive": ["non-aggressive", "aggressive"],
    "mood_happy": ["non-happy", "happy"],
    "mood_party": ["non-party", "party"],
    "mood_relaxed": ["non-relaxed", "relaxed"],
    "mood_sad": ["non-sad", "sad"],
    "tonal_atonal": ["tonal", "atonal"],
    "voice_instrumental": ["instrumental", "voice"],
}


# Supported audio extensions — must match nomarr's metadata_extraction_comp
_AUDIO_EXTS = frozenset({".m4a", ".mp4", ".m4b", ".m4p", ".mp3", ".mp2", ".flac", ".ogg", ".opus"})


# ── Path helpers ──────────────────────────────────────────────────────────────


def song_id(path: str | Path) -> str:
    """Deterministic 12-char ID from the absolute path."""
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]


def patches_path(sid: str, backbone: str) -> Path:
    """Sidecar path for raw [n_patches, embed_dim] float32 array."""
    return PATCHES_DIR / f"{sid}.{backbone}.npy"


# ── Audio discovery ───────────────────────────────────────────────────────────


def stratify_songs(songs: list[dict], limit: int | None) -> list[dict]:
    """Return a stratified subset of *songs* (dicts with 'artist' and 'album' keys).

    Selection order:
      Round 1 – 2 songs per artist (different albums when possible)
      Round 2 – 2 more per artist (next-unused albums)
      … continue until *limit* is reached or all songs are included.

    Within each round songs are picked in sorted order so results are
    deterministic across runs.
    """
    if not limit:
        return songs

    # Group by artist, then within each artist by album, sorted deterministically
    from collections import defaultdict

    by_artist: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for s in sorted(songs, key=lambda x: (x.get("artist", ""), x.get("album", ""), x.get("title", x.get("path", "")))):
        by_artist[s["artist"]][s["album"]].append(s)

    # Per-artist: flatten into a list that interleaves albums
    # e.g. [alb1_song1, alb2_song1, alb1_song2, alb2_song2, alb3_song1, ...]
    artist_queues: dict[str, list[dict]] = {}
    for artist, albums in sorted(by_artist.items()):
        interleaved: list[dict] = []
        album_lists = [v for v in sorted(albums.values(), key=lambda lst: lst[0].get("album", ""))]
        max_per_album = max(len(lst) for lst in album_lists)
        for i in range(max_per_album):
            for alb in album_lists:
                if i < len(alb):
                    interleaved.append(alb[i])
        artist_queues[artist] = interleaved

    # Round-robin 2-at-a-time across artists until limit reached
    selected: list[dict] = []
    artists = sorted(artist_queues.keys())
    positions = {a: 0 for a in artists}
    chunk = 2
    while len(selected) < limit:
        added_this_round = 0
        for artist in artists:
            if len(selected) >= limit:
                break
            pos = positions[artist]
            batch = artist_queues[artist][pos: pos + chunk]
            take = min(len(batch), limit - len(selected))
            selected.extend(batch[:take])
            positions[artist] = pos + take
            added_this_round += take
        if added_this_round == 0:
            break  # all artists exhausted

    return selected


def discover_audio(limit: int | None = None) -> list[Path]:
    """Return a stratified list of audio files.

    With *limit*, picks 2 songs per artist (across different albums) and keeps
    cycling through artists until *limit* is reached, rather than just taking
    the first N alphabetically.

    Genre tags are NOT read here — path-based artist/album/title are sufficient
    for stratification. Genre is read lazily during DB upsert only.
    """
    files = sorted(p for p in MEDIA_ROOT.rglob("*") if p.suffix.lower() in _AUDIO_EXTS)
    if not limit:
        return files
    # Build lightweight path-only meta (no file I/O) purely for stratification.
    metas = []
    for f in files:
        parts = f.relative_to(MEDIA_ROOT).parts
        metas.append({
            "_path": f,
            "artist": parts[0] if len(parts) > 0 else "unknown",
            "album": parts[1] if len(parts) > 1 else "unknown",
            "title": f.stem,
        })
    selected = stratify_songs(metas, limit)
    return [s["_path"] for s in selected]


def path_to_meta(path: Path) -> dict:
    """Extract full metadata from an audio file using nomarr's tag normalizer.

    Falls back to path-derived values if tags are absent or unreadable.
    Caller must have called bootstrap_nomarr() first so nomarr imports resolve.
    """
    parts = path.relative_to(MEDIA_ROOT).parts
    path_artist = parts[0] if len(parts) > 0 else "unknown"
    path_album  = parts[1] if len(parts) > 1 else "unknown"
    path_title  = path.stem

    try:
        from nomarr.components.library.metadata_extraction_comp import extract_metadata
        from nomarr.helpers.dto.path_dto import LibraryPath

        lp = LibraryPath(
            relative=path.relative_to(MEDIA_ROOT).as_posix(),
            absolute=path.resolve(),
            library_id=None,
            status="valid",
        )
        meta = extract_metadata(lp)
        genres: list[str] = meta.get("genre") or []
        return {
            "path": str(path),
            "artist": meta.get("artist") or path_artist,
            "album":  meta.get("album")  or path_album,
            "title":  meta.get("title")  or path_title,
            "genre":  genres[0] if genres else "unknown",
        }
    except Exception:
        return {
            "path": str(path),
            "artist": path_artist,
            "album":  path_album,
            "title":  path_title,
            "genre":  "unknown",
        }


# Re-export so callers can do: from .config import stratify_songs


# ── nomarr import bootstrap ───────────────────────────────────────────────────


def bootstrap_nomarr() -> None:
    """Ensure /app is on sys.path so nomarr can be imported."""
    app = str(NOMARR_APP)
    if app not in sys.path:
        sys.path.insert(0, app)
