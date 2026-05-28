"""Patch-features table operations."""

from __future__ import annotations

# ── patch_features ────────────────────────────────────────────────────────────


def patch_features_done(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM patch_features WHERE song_id=? LIMIT 1", [song_id]).fetchone() is not None
