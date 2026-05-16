"""
I/O helpers for patch sidecars.

Pooled vectors, head results, and metrics are stored in DuckDB (see db.py).
Raw [n_patches, embed_dim] patch arrays stay on disk as .npy sidecars to
avoid bloating the database with large float tensors.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import PATCHES_DIR


def ensure_patches_dir() -> None:
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)


def save_patches(sidecar: Path, arr: np.ndarray) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(sidecar), arr.astype(np.float32))


def load_patches(sidecar: Path) -> np.ndarray | None:
    if sidecar.exists():
        return np.load(str(sidecar)).astype(np.float32)
    return None
