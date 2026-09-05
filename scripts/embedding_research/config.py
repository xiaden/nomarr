"""
Global configuration for the embedding research package.
All paths are written for execution inside the nomarr devcontainer.
"""

from __future__ import annotations

import hashlib
import logging as _logging
import os
import sys
from pathlib import Path

_log = _logging.getLogger(__name__)

# ── nomarr package on the container path ─────────────────────────────────────
# Override with NOMARR_APP_PATH env var when running outside the default devcontainer layout.
NOMARR_APP = Path(os.environ.get("NOMARR_APP_PATH", "/app"))
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
    if not any(result.values()):
        _log.warning(
            "No ONNX head classifiers found under %s — disc_head will be 0 for all strategies. "
            "Is the devcontainer running with head models mounted at /app/models/?",
            NOMARR_APP / "models",
        )
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
    """Return a stratified subset of *songs*.

    Each song dict must have 'artist' and 'album' keys.  An optional 'genre'
    key is used when present to guarantee ≥2 songs per genre as well.

    Selection passes (in priority order):
      Pass 1 - guarantee ≥2 songs per artist       (essential for disc_artist)
      Pass 2 - guarantee ≥2 songs per album        (ensures album metadata coverage)
      Pass 3 - guarantee ≥2 songs per genre        (only when genre != 'unknown')
      Pass 4 - fill remaining capacity round-robin by artist/album interleave

    Within each pass songs are picked in sorted order so results are
    deterministic across runs.
    """
    if not limit:
        return songs

    from collections import defaultdict

    all_songs = sorted(
        songs,
        key=lambda x: (x.get("artist", ""), x.get("album", ""), x.get("title", x.get("path", ""))),
    )
    selected: list[dict] = []
    selected_ids: set[str] = set()

    def _song_id(s: dict) -> str:
        return str(s.get("_path", s.get("path", id(s))))

    def _pick_up_to(candidates: list[dict], n: int) -> None:
        """Add up to n candidates not already selected, respecting limit."""
        added = 0
        for s in candidates:
            if len(selected) >= limit or added >= n:
                break
            sid = _song_id(s)
            if sid not in selected_ids:
                selected.append(s)
                selected_ids.add(sid)
                added += 1

    # ── Pass 1: ≥2 per artist ────────────────────────────────────────────────
    by_artist: dict[str, list[dict]] = defaultdict(list)
    for s in all_songs:
        by_artist[s.get("artist", "unknown")].append(s)
    for artist in sorted(by_artist):
        _pick_up_to(by_artist[artist], 2)

    # ── Pass 2: ≥2 per album ─────────────────────────────────────────────────
    by_album: dict[str, list[dict]] = defaultdict(list)
    for s in all_songs:
        key = f"{s.get('artist', 'unknown')}::{s.get('album', 'unknown')}"
        by_album[key].append(s)
    for key in sorted(by_album):
        _pick_up_to(by_album[key], 2)

    # ── Pass 3: ≥2 per genre (skip 'unknown') ────────────────────────────────
    by_genre: dict[str, list[dict]] = defaultdict(list)
    for s in all_songs:
        g = s.get("genre") or "unknown"
        if g != "unknown":
            by_genre[g].append(s)
    for genre in sorted(by_genre):
        _pick_up_to(by_genre[genre], 2)

    # ── Pass 4: fill remaining round-robin by artist, interleaving albums ────
    if len(selected) < limit:
        artist_queues: dict[str, list[dict]] = {}
        for artist, _ in sorted({a: defaultdict(list) for a in by_artist}.items()):
            # rebuild per-album interleave for fill pass
            alb: dict[str, list[dict]] = defaultdict(list)
            for s in by_artist[artist]:
                alb[s.get("album", "unknown")].append(s)
            album_lists = sorted(alb.values(), key=lambda lst: lst[0].get("album", ""))
            max_pa = max(len(lst) for lst in album_lists)
            interleaved = [alst[i] for i in range(max_pa) for alst in album_lists if i < len(alst)]
            artist_queues[artist] = interleaved

        artist_order = sorted(artist_queues.keys())
        positions = dict.fromkeys(artist_order, 0)
        chunk = 2
        while len(selected) < limit:
            added_this_round = 0
            for artist in artist_order:
                if len(selected) >= limit:
                    break
                pos = positions[artist]
                batch = artist_queues[artist][pos : pos + chunk]
                took = 0
                for s in batch:
                    if len(selected) >= limit:
                        break
                    sid = _song_id(s)
                    if sid not in selected_ids:
                        selected.append(s)
                        selected_ids.add(sid)
                        took += 1
                positions[artist] = pos + len(batch)
                added_this_round += took
            if added_this_round == 0:
                break

    return selected


def discover_audio(limit: int | None = None, *, con=None) -> list[Path]:
    """Return a stratified list of audio files.

    When *con* is provided (a DuckDB connection with an ingested songs table),
    genre data from the DB is used for genre-aware stratification so disc_genre
    pairs are guaranteed.  Falls back gracefully when the table is absent or
    when songs haven't been ingested yet.

    Without *limit*, all discovered files are returned in sorted order.
    """
    files = sorted(p for p in MEDIA_ROOT.rglob("*") if p.suffix.lower() in _AUDIO_EXTS)
    if not limit:
        return files

    # Build path-only meta first (no file I/O)
    path_to_meta_quick: dict[str, dict] = {}
    for f in files:
        parts = f.relative_to(MEDIA_ROOT).parts
        sid = song_id(str(f))
        path_to_meta_quick[sid] = {
            "_path": f,
            "artist": parts[0] if len(parts) > 0 else "unknown",
            "album": parts[1] if len(parts) > 1 else "unknown",
            "title": f.stem,
            "genre": "unknown",
        }

    # Overlay genre from DB if available
    if con is not None:
        try:
            rows = con.execute(
                "SELECT song_id, genre FROM songs WHERE genre IS NOT NULL AND genre != '' AND genre != 'unknown'"
            ).fetchall()
            for db_song_id, genre in rows:
                if db_song_id in path_to_meta_quick and genre:
                    path_to_meta_quick[db_song_id]["genre"] = genre
        except Exception:
            pass  # songs table absent or query failed — proceed without genre

    metas = list(path_to_meta_quick.values())
    selected = stratify_songs(metas, limit)
    return [s["_path"] for s in selected]


def path_to_meta(path: Path) -> dict:
    """Extract full metadata from an audio file using nomarr's tag normalizer.

    Falls back to path-derived values if tags are absent or unreadable.
    Caller must have called bootstrap_nomarr() first so nomarr imports resolve.
    """
    parts = path.relative_to(MEDIA_ROOT).parts
    path_artist = parts[0] if len(parts) > 0 else "unknown"
    path_album = parts[1] if len(parts) > 1 else "unknown"
    path_title = path.stem

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
            "album": meta.get("album") or path_album,
            "title": meta.get("title") or path_title,
            "genre": genres[0] if genres else "unknown",
        }
    except Exception as exc:
        _log.warning(
            "path_to_meta: tag extraction failed for %s: %s — using path-derived fallback",
            path.name,
            exc,
        )
        return {
            "path": str(path),
            "artist": path_artist,
            "album": path_album,
            "title": path_title,
            "genre": "unknown",
        }


# Re-export so callers can do: from .config import stratify_songs


# ── nomarr import bootstrap ───────────────────────────────────────────────────


def bootstrap_nomarr() -> None:
    """Ensure /app is on sys.path so nomarr can be imported."""
    app = str(NOMARR_APP)
    if app not in sys.path:
        sys.path.insert(0, app)
