#!/usr/bin/env python3
"""Validate musicnn backbone patch on real audio files.

Runs CPU inference on a set of songs through both the original and patched
backbone models, then compares embeddings and (optionally) head scores.

Unlike the synthetic verify_numerical check in patch_musicnn_conv.py, this
tests the actual preprocessing → backbone → (head) pipeline on real mel
spectrograms. Results are more representative of production behaviour.

Usage:
    python test_musicnn_patch.py \\
        --original  /models/musicnn/embedding/msd-musicnn-1.onnx \\
        --patched   /models/musicnn/embedding/msd-musicnn-1-patched.onnx \\
        --audio-dir /media/Music \\
        --limit     20

    # Or pass explicit files:
    python test_musicnn_patch.py \\
        --original  ... --patched ... \\
        /media/Music/track1.flac /media/Music/track2.mp3

Options:
    --original PATH   Original (unpatched) backbone ONNX
    --patched  PATH   Patched backbone ONNX
    --audio-dir DIR   Scan DIR recursively for audio files (mp3/flac/ogg/m4a/wav)
    --limit N         Max number of files to test (default: 20)
    --head PATH       Optional: head ONNX to run on both embedding sets
    --threshold F     Max acceptable max_abs_diff in embeddings (default: 1e-3)
    --verbose         Print per-file stats
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".aif", ".wv"}


def _collect_audio_files(audio_dir: str, limit: int) -> list[str]:
    found = []
    for root, _, files in os.walk(audio_dir):
        for f in sorted(files):
            if Path(f).suffix.lower() in AUDIO_EXTS:
                found.append(os.path.join(root, f))
                if len(found) >= limit:
                    return found
    return found


def _load_backbone(path: str) -> ONNXBackboneModel:  # type: ignore[name-defined]  # noqa: F821
    from nomarr.components.ml.onnx.ml_backbone import ONNXBackboneModel
    model = ONNXBackboneModel(path)
    model.load("cpu")
    return model


def _run_head_session(session: ort.InferenceSession, embeddings: np.ndarray) -> np.ndarray:  # type: ignore[name-defined]  # noqa: F821
    """Run a head ONNX session on embeddings [N, embed_dim] → raw scores."""
    input_name = session.get_inputs()[0].name
    result: np.ndarray = session.run(None, {input_name: embeddings})[0]  # type: ignore[name-defined]  # ort.run returns list[Any]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare original vs patched musicnn backbone on real audio")
    parser.add_argument("--original", required=True, help="Path to original backbone ONNX")
    parser.add_argument("--patched", required=True, help="Path to patched backbone ONNX")
    parser.add_argument("--audio-dir", help="Directory to scan for audio files")
    parser.add_argument("--limit", type=int, default=20, help="Max files to test (default: 20)")
    parser.add_argument("--head", help="Optional head ONNX — compare scores too")
    parser.add_argument("--threshold", type=float, default=1e-3, help="Max acceptable max_abs_diff (default: 1e-3)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("files", nargs="*", help="Explicit audio files")
    args = parser.parse_args()

    # -- Resolve audio file list --
    audio_files: list[str] = list(args.files)
    if args.audio_dir:
        audio_files += _collect_audio_files(args.audio_dir, args.limit)
    audio_files = audio_files[: args.limit]

    if not audio_files:
        print("ERROR: No audio files specified. Use --audio-dir or provide file paths.")
        sys.exit(1)

    print(f"Testing on {len(audio_files)} file(s)")
    print(f"  original : {args.original}")
    print(f"  patched  : {args.patched}")
    print(f"  threshold: {args.threshold:.1e}")
    if args.head:
        print(f"  head     : {args.head}")
    print()

    # -- Load models --
    try:
        from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono
    except ImportError as e:
        print(f"ERROR: Could not import nomarr — is the package installed? {e}")
        sys.exit(1)

    print("Loading backbone models (CPU)…")
    orig_model = _load_backbone(args.original)
    patch_model = _load_backbone(args.patched)

    head_session = None
    if args.head:
        try:
            import onnxruntime as ort
            head_session = ort.InferenceSession(args.head, providers=["CPUExecutionProvider"])
            print(f"Loaded head: {args.head}")
        except Exception as e:
            print(f"WARNING: Could not load head model ({e}), skipping head comparison")
    print()

    # -- Per-file stats --
    emb_diffs: list[float] = []
    score_diffs: list[float] = []
    failures: list[str] = []

    for i, path in enumerate(audio_files):
        fname = os.path.basename(path)
        try:
            result = load_audio_mono(path, target_sr=16000)
            waveform = result.waveform
        except Exception as e:
            print(f"  [{i+1}/{len(audio_files)}] SKIP {fname}: load error — {e}")
            continue

        try:
            emb_orig = orig_model.run(waveform)   # [n_patches, embed_dim]
            emb_patch = patch_model.run(waveform)
        except Exception as e:
            print(f"  [{i+1}/{len(audio_files)}] SKIP {fname}: inference error — {e}")
            failures.append(path)
            continue

        if emb_orig.shape != emb_patch.shape:
            msg = f"shape mismatch: {emb_orig.shape} vs {emb_patch.shape}"
            print(f"  [{i+1}/{len(audio_files)}] FAIL {fname}: {msg}")
            failures.append(path)
            continue

        emb_max_diff = float(np.max(np.abs(emb_orig - emb_patch)))
        emb_mean_diff = float(np.mean(np.abs(emb_orig - emb_patch)))
        emb_diffs.append(emb_max_diff)
        status = "OK  " if emb_max_diff < args.threshold else "FAIL"

        line = (
            f"  [{i+1}/{len(audio_files)}] {status} {fname}"
            f"  emb_max={emb_max_diff:.3e}  emb_mean={emb_mean_diff:.3e}"
            f"  patches={emb_orig.shape[0]}"
        )

        # Optional head comparison
        if head_session is not None:
            try:
                scores_orig = _run_head_session(head_session, emb_orig)
                scores_patch = _run_head_session(head_session, emb_patch)
                score_max_diff = float(np.max(np.abs(scores_orig - scores_patch)))
                score_diffs.append(score_max_diff)
                line += f"  score_max={score_max_diff:.3e}"
            except Exception as e:
                line += f"  score=ERR({e})"

        if args.verbose or status != "OK  ":
            print(line)
        elif (i + 1) % 5 == 0:
            print(f"  … {i+1}/{len(audio_files)} processed")

        if emb_max_diff >= args.threshold:
            failures.append(path)

    # -- Summary --
    tested = len(emb_diffs)
    passed = sum(1 for d in emb_diffs if d < args.threshold)
    print()
    print("=" * 60)
    print(f"Results: {passed}/{tested} passed  ({len(failures)} failures)")
    if emb_diffs:
        print(f"  Embeddings  max_abs_diff — max={max(emb_diffs):.3e}  mean={np.mean(emb_diffs):.3e}  p95={np.percentile(emb_diffs, 95):.3e}")
    if score_diffs:
        print(f"  Head scores max_abs_diff — max={max(score_diffs):.3e}  mean={np.mean(score_diffs):.3e}  p95={np.percentile(score_diffs, 95):.3e}")
    if failures:
        print("\nFailed files:")
        for f in failures:
            print(f"  {f}")

    print("=" * 60)
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
