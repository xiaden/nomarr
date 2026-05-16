"""
Phase 1: backbone inference -> patch sidecars + pooled vectors in DuckDB.

For each audio file:
  - Load waveform via nomarr.components.ml.audio.ml_audio_comp.load_audio_mono
  - preprocess_for_backbone -> mel spectrogram patches [n_patches, patch_frames, n_mels]
  - Run through ONNX backbone -> embeddings [n_patches, embed_dim]
  - Save raw patches as .npy sidecar (avoids OOM on full corpus load)
  - Apply all pooling strategies -> upsert pooled vectors into DuckDB
  - Register song metadata in DuckDB songs table

Run from inside the devcontainer:
  python /workspace/scripts/embedding_research/embed.py [--limit N] [--backbone effnet musicnn]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

from .config import (
    BACKBONES,
    DB_PATH,
    PATCHES_DIR,
    bootstrap_nomarr,
    discover_audio,
    patches_path,
    path_to_meta,
    song_id,
)
from .db import connect, pooled_exists, song_exists, upsert_pooled, upsert_song
from .pooling import STRATEGIES


def embed_song(
    path: Path,
    backbone_name: str,
    backbone_cfg: dict,
    load_audio_fn,
    preprocess_fn,
    create_session_fn,
    run_in_batches_fn,
    batch_size: int,
    con,
    force: bool = False,
) -> bool:
    """
    Compute embeddings for one song+backbone. Returns True if work was done.
    Skips if all pooled vectors already exist in DB (unless force=True).
    """
    sid = song_id(path)

    # Check if all strategies already done
    if not force and all(pooled_exists(con, sid, backbone_name, s) for s in STRATEGIES):
        return False

    # ── Register song if new ──────────────────────────────────────────────────
    if not song_exists(con, sid):
        meta = path_to_meta(path)
        upsert_song(con, sid, meta["path"], meta["artist"], meta["album"], meta["title"])

    # ── Load audio via nomarr ─────────────────────────────────────────────────
    try:
        result = load_audio_fn(str(path), target_sr=16000)
        waveform = result.waveform
    except Exception as exc:
        raise RuntimeError(f"Audio load failed: {path}") from exc

    # ── Preprocess ────────────────────────────────────────────────────────────
    patches = preprocess_fn(waveform, backbone_cfg["backbone_name"])
    if patches is None or len(patches) == 0:
        return False

    # ── Backbone inference ────────────────────────────────────────────────────
    session = create_session_fn(backbone_cfg["path"], device="cpu")

    def predict(batch):
        return session.run(["embeddings"], {"melspectrogram": batch})[0]

    embeddings = run_in_batches_fn(predict, patches, batch_size)  # [n_patches, dim]

    # ── Save raw patches as sidecar (skip if exists and not force) ────────────
    sidecar = patches_path(sid, backbone_name)
    if force or not sidecar.exists():
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(sidecar), embeddings.astype(np.float32))

    # ── Pool and upsert into DuckDB ───────────────────────────────────────────
    for strategy_name, pool_fn in STRATEGIES.items():
        if force or not pooled_exists(con, sid, backbone_name, strategy_name):
            pooled = pool_fn(embeddings).astype(np.float32)
            upsert_pooled(con, sid, backbone_name, strategy_name, pooled)

    return True


def run(
    limit: int | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    verbose: bool = False,
) -> None:
    bootstrap_nomarr()

    from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono
    from nomarr.components.ml.audio.ml_preprocess_comp import preprocess_for_backbone
    from nomarr.components.ml.onnx.ml_session_comp import (
        _BACKBONE_BATCH_SIZE,
        _run_in_batches,
        create_session,
    )

    PATCHES_DIR.mkdir(parents=True, exist_ok=True)

    audio_paths = discover_audio(limit=limit)
    bb_names = backbones or list(BACKBONES)

    print(f"Embedding {len(audio_paths)} songs x {len(bb_names)} backbone(s) ...")
    print(f"Database: {DB_PATH}")

    with connect() as con:
        for bb_name in bb_names:
            bb_cfg = BACKBONES[bb_name]
            done = skipped = errors = 0
            t0 = time.time()

            pbar = tqdm(audio_paths, desc=f"[{bb_name}]", unit="song")
            for path in pbar:
                try:
                    worked = embed_song(
                        path,
                        bb_name,
                        bb_cfg,
                        load_audio_mono,
                        preprocess_for_backbone,
                        create_session,
                        _run_in_batches,
                        _BACKBONE_BATCH_SIZE,
                        con,
                        force=force,
                    )
                    if worked:
                        done += 1
                    else:
                        skipped += 1
                    pbar.set_postfix(done=done, skip=skipped, err=errors)
                except Exception as exc:
                    errors += 1
                    if verbose:
                        tqdm.write(f"  [ERROR] {bb_name} {path.name}: {exc}")

            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 and done > 0 else 0
            print(f"[{bb_name}] done={done} skipped={skipped} errors={errors} in {elapsed:.0f}s ({rate:.2f} songs/s)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 1: backbone inference -> sidecars + DuckDB")
    ap.add_argument("--limit", type=int, default=None, help="Process only N songs (debug)")
    ap.add_argument("--backbone", nargs="+", choices=list(BACKBONES), default=None)
    ap.add_argument("--force", action="store_true", help="Re-embed even if already done")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, force=args.force, backbones=args.backbone, verbose=args.verbose)


if __name__ == "__main__":
    main()
