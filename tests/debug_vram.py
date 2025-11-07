#!/usr/bin/env python3
"""
Debug script to analyze VRAM usage during model loading.
Run this to see what's actually allocating GPU memory.
"""

import os

os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"
os.environ["TF_GPU_THREAD_MODE"] = "gpu_private"


import tensorflow as tf

from essentia_autotag.config import compose
from essentia_autotag.discovery import discover_heads
from essentia_autotag.embed import BackboneCache
from essentia_autotag.heads import ClassifierCache


def get_gpu_memory():
    """Get current GPU memory usage in MB."""
    gpus = tf.config.list_physical_devices("GPU")
    if not gpus:
        return None

    # Get memory info
    try:
        memory_info = tf.config.experimental.get_memory_info("GPU:0")
        current_mb = memory_info["current"] / (1024**2)
        peak_mb = memory_info["peak"] / (1024**2)
        return current_mb, peak_mb
    except Exception:
        return None, None


def main():
    print("=" * 70)
    print("VRAM Usage Analysis")
    print("=" * 70)

    # Initial state
    current, peak = get_gpu_memory()
    if current:
        print(f"\n📊 Initial GPU Memory: {current:.1f} MB (peak: {peak:.1f} MB)")

    # Load config
    cfg = compose({})
    models_dir = cfg["models_dir"]

    # Discover models
    print(f"\n🔍 Discovering models in: {models_dir}")
    heads = discover_heads(models_dir)

    # Group by backbone
    by_backbone = {}
    for head in heads:
        if head.backbone not in by_backbone:
            by_backbone[head.backbone] = []
        by_backbone[head.backbone].append(head)

    print(f"\n📦 Found {len(heads)} heads across {len(by_backbone)} backbones:")
    for backbone, heads_list in by_backbone.items():
        print(f"  - {backbone}: {len(heads_list)} heads")

    # Load backbones one by one
    backbone_cache = BackboneCache()

    for backbone_name in sorted(by_backbone.keys()):
        print(f"\n{'=' * 70}")
        print(f"Loading backbone: {backbone_name}")
        print(f"{'=' * 70}")

        # Before loading
        current, peak = get_gpu_memory()
        mem_before = current if current else 0
        print(f"  Memory before: {mem_before:.1f} MB")

        # Load backbone
        backbone = backbone_cache.load(backbone_name)

        # After loading
        current, peak = get_gpu_memory()
        mem_after = current if current else 0
        delta = mem_after - mem_before
        print(f"  Memory after:  {mem_after:.1f} MB")
        print(f"  📈 Delta:       {delta:.1f} MB")

        # Now load heads for this backbone
        classifier_cache = ClassifierCache()
        heads_list = by_backbone[backbone_name]

        print(f"\n  Loading {len(heads_list)} heads for {backbone_name}:")
        for head in heads_list:
            current_before, _ = get_gpu_memory()
            mem_head_before = current_before if current_before else 0

            classifier_cache.load(head)

            current_after, _ = get_gpu_memory()
            mem_head_after = current_after if current_after else 0
            head_delta = mem_head_after - mem_head_before

            print(f"    • {head.name:40s} +{head_delta:6.1f} MB")

        # Total after all heads
        current, peak = get_gpu_memory()
        mem_total = current if current else 0
        total_delta = mem_total - mem_before
        print(f"\n  📊 Total for {backbone_name}: +{total_delta:.1f} MB")

    # Final summary
    print(f"\n{'=' * 70}")
    print("FINAL SUMMARY")
    print(f"{'=' * 70}")
    current, peak = get_gpu_memory()
    if current:
        print(f"Current GPU Memory: {current:.1f} MB")
        print(f"Peak GPU Memory:    {peak:.1f} MB")

    # TensorFlow memory summary
    print("\n📋 TensorFlow Memory Allocator Info:")
    try:
        from tensorflow.python.eager import context

        ctx = context.context()
        if ctx.list_devices():
            print(f"  Devices: {len(ctx.list_devices())}")
            for device in ctx.list_devices():
                print(f"    - {device}")
    except Exception as e:
        print(f"  Could not get device info: {e}")


if __name__ == "__main__":
    main()
