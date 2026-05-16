"""
Phase 2: head inference -- pool-then-classify (PTC) and classify-then-pool (CTP).

PTC: pool patches with strategy -> run pooled [embed_dim] through head -> [2]
CTP: run head on raw patches [n_patches, embed_dim] -> [n_patches, 2]
     -> pool the per-patch probabilities -> [2]

Both pathways are stored per (song_id, backbone, head, strategy, pathway)
in the DuckDB head_results table.

This directly answers:
  - Does pooling the embedding first produce a stronger class signal?
  - Or does pooling the head output (classify-then-pool) work better?
  - Do songs with the same head decision cluster together more tightly?

Run from inside the devcontainer:
  python /workspace/scripts/embedding_research/classify.py [--limit N] [--backbone effnet]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

from .config import (
    BACKBONES,
    HEADS,
    bootstrap_nomarr,
    discover_audio,
    patches_path,
    song_id,
)
from .db import (
    connect,
    head_strategy_done,
    load_pooled_matrix,
    upsert_head,
)
from .pooling import STRATEGIES


def _run_head_session(session, embed_batch: np.ndarray) -> np.ndarray:
    """
    Run a head ONNX session. embed_batch: [n, d] -> [n, 2].
    Handles single-vec input by adding/removing batch dim.
    """
    inp = embed_batch if embed_batch.ndim == 2 else embed_batch[None, :]
    return session.run(["activations"], {"embeddings": inp.astype(np.float32)})[0]


def classify_song(
    path: Path,
    backbone_name: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    con,
    pooled_map: dict,  # {strategy: vec [embed_dim]} preloaded from DB
    force: bool = False,
) -> bool:
    """
    Compute PTC + CTP activations for all strategies. Upsert into DuckDB.
    Returns True if new work was done.
    """
    sid = song_id(path)

    if not force and all(head_strategy_done(con, sid, backbone_name, head_name, s) for s in STRATEGIES):
        return False

    # ── Load raw patches from sidecar ─────────────────────────────────────────
    sidecar = patches_path(sid, backbone_name)
    if not sidecar.exists():
        return False  # embed phase not done for this song

    patches = np.load(str(sidecar)).astype(np.float32)  # [n_patches, embed_dim]

    # ── CTP: run head on all patches once, then pool per strategy ─────────────
    try:
        patch_acts = run_in_batches_fn(
            lambda b: _run_head_session(head_session, b),
            patches,
            batch_size,
        )  # [n_patches, 2]
    except Exception as exc:
        raise RuntimeError(f"CTP head inference failed for {path.name}/{head_name}") from exc

    for strategy_name, pool_fn in STRATEGIES.items():
        if not force and head_strategy_done(con, sid, backbone_name, head_name, strategy_name):
            continue

        # PTC: pool embedding, then classify
        pooled_vec = pooled_map.get(strategy_name)
        if pooled_vec is None:
            # Fall back to on-the-fly pooling from patches
            pooled_vec = pool_fn(patches).astype(np.float32)
        ptc_act = _run_head_session(head_session, pooled_vec[None, :])[0]  # [2]

        # CTP: pool the per-patch activations
        ctp_act = pool_fn(patch_acts).astype(np.float32)  # [2]

        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ptc", ptc_act.tolist())
        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ctp", ctp_act.tolist())

    return True


def run(
    limit: int | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    verbose: bool = False,
) -> None:
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import (
        _BACKBONE_BATCH_SIZE,
        _run_in_batches,
        create_session,
    )

    audio_paths = discover_audio(limit=limit)
    bb_names = backbones or list(BACKBONES)

    with connect() as con:
        for bb_name in bb_names:
            head_map = {h: p for h, p in HEADS.get(bb_name, {}).items() if heads is None or h in heads}
            if not head_map:
                print(f"No heads for {bb_name}")
                continue

            # Pre-load all pooled vectors for this backbone from DuckDB
            # Strategy -> {sid: vec} lookup (avoids repeated DB queries per song)
            print(f"\n[{bb_name}] Pre-loading pooled vectors from DB ...")
            strat_to_pooled: dict[str, dict[str, np.ndarray]] = {}
            for strategy in STRATEGIES:
                vecs, sids, _ = load_pooled_matrix(con, bb_name, strategy)
                strat_to_pooled[strategy] = dict(zip(sids, vecs, strict=False)) if len(sids) > 0 else {}
            print(f"  Loaded {len(next(iter(strat_to_pooled.values())))} pooled vecs per strategy")

            for head_name, head_model_path in head_map.items():
                print(f"\n  [{bb_name}/{head_name}] Loading head session ...")
                try:
                    head_session = create_session(head_model_path, device="cpu")
                except Exception as exc:
                    print(f"  [ERROR] Failed to load {head_name}: {exc}")
                    continue

                done = skipped = errors = 0
                t0 = time.time()

                pbar = tqdm(audio_paths, desc=f"  [{bb_name}/{head_name}]", unit="song")
                for path in pbar:
                    sid = song_id(path)
                    # Build per-song pooled map
                    pooled_map = {s: strat_to_pooled[s].get(sid) for s in STRATEGIES}
                    try:
                        worked = classify_song(
                            path,
                            bb_name,
                            head_name,
                            head_session,
                            _run_in_batches,
                            _BACKBONE_BATCH_SIZE,
                            con,
                            pooled_map,
                            force=force,
                        )
                        done += 1 if worked else 0
                        skipped += 0 if worked else 1
                        pbar.set_postfix(done=done, skip=skipped, err=errors)
                    except Exception as exc:
                        errors += 1
                        if verbose:
                            tqdm.write(f"  [ERROR] {path.name}: {exc}")

                elapsed = time.time() - t0
                print(f"  [{bb_name}/{head_name}] done={done} skip={skipped} err={errors} in {elapsed:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 2: head inference (PTC + CTP) into DuckDB")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--backbone", nargs="+", choices=list(BACKBONES), default=None)
    ap.add_argument("--head", nargs="+", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, force=args.force, backbones=args.backbone, heads=args.head, verbose=args.verbose)


if __name__ == "__main__":
    main()
