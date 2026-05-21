"""Patch-features table operations."""

from __future__ import annotations


# ── patch_features ────────────────────────────────────────────────────────────


def patch_features_done(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM patch_features WHERE song_id=? LIMIT 1", [song_id]).fetchone() is not None


def upsert_patch_features(con, song_id: str, features: list[dict]) -> None:
    """
    Bulk-upsert per-patch audio features for one song.
    ``features`` is a list (one entry per patch index) of dicts with keys:
      rms, spectral_centroid, onset_strength, chroma_key
    """
    rows = [
        (
            song_id,
            idx,
            f.get("rms"),
            f.get("spectral_centroid"),
            f.get("onset_strength"),
            f.get("chroma_key"),
        )
        for idx, f in enumerate(features)
    ]
    con.executemany(
        """
        INSERT INTO patch_features
          (song_id, patch_idx, rms, spectral_centroid, onset_strength, chroma_key)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT (song_id, patch_idx) DO UPDATE SET
          rms=excluded.rms,
          spectral_centroid=excluded.spectral_centroid,
          onset_strength=excluded.onset_strength,
          chroma_key=excluded.chroma_key
        """,
        rows,
    )
