"""
Global configuration for the embedding research package.
All paths are written for execution inside the nomarr devcontainer.
"""

from __future__ import annotations

import hashlib
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
DB_PATH = OUTPUT_ROOT / "research.duckdb"

# ── Backbone model registry ───────────────────────────────────────────────────
BACKBONES: dict[str, dict] = {
    "effnet": {
        "path": str(NOMARR_APP / "models/effnet/embeddings/discogs-effnet-bsdynamic-1.onnx"),
        "embed_dim": 1280,
        "backbone_name": "effnet",  # arg for preprocess_for_backbone
    },
    "musicnn": {
        "path": str(NOMARR_APP / "models/musicnn/embeddings/msd-musicnn-1.onnx"),
        "embed_dim": 200,
        "backbone_name": "musicnn",
    },
}


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


# ── Path helpers ──────────────────────────────────────────────────────────────


def song_id(path: str | Path) -> str:
    """Deterministic 12-char ID from the absolute path."""
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]


def patches_path(sid: str, backbone: str) -> Path:
    """Sidecar path for raw [n_patches, embed_dim] float32 array."""
    return PATCHES_DIR / f"{sid}.{backbone}.npy"


# ── Audio discovery ───────────────────────────────────────────────────────────


def discover_audio(limit: int | None = None) -> list[Path]:
    files = sorted(MEDIA_ROOT.rglob("*.m4a"))
    return files[:limit] if limit else files


def path_to_meta(path: Path) -> dict:
    parts = path.relative_to(MEDIA_ROOT).parts
    return {
        "path": str(path),
        "artist": parts[0] if len(parts) > 0 else "unknown",
        "album": parts[1] if len(parts) > 1 else "unknown",
        "title": path.stem,
    }


# ── nomarr import bootstrap ───────────────────────────────────────────────────


def bootstrap_nomarr() -> None:
    """Ensure /app is on sys.path so nomarr can be imported."""
    app = str(NOMARR_APP)
    if app not in sys.path:
        sys.path.insert(0, app)
