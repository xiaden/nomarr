"""
Typed vector containers for the embedding research pipeline.

Usage pattern
-------------
Function signatures declare the wrapper type:

    def embed(path: str) -> RawVector: ...
    def compute_sim(a: UnitVector, b: UnitVector) -> float: ...

Methods on each type preserve the type, so operations stay self-consistent:

    unit_v  = raw_v.normalize()             # -> UnitVector  (norm = ||raw_v||)
    unit_t  = raw_t.normalize()             # -> UnitTensor  (norm = row norms)
    song_v  = unit_tensor.pool_mean()       # -> UnitVector  (norm = MRL)

Combination rule: always go through a UnitTensor, pool once
-----------------------------------------------------------
  WRONG - mean(mean(a, b), c) gives wrong direction AND corrupt norm:
      result = a.stack(b).pool_mean().stack(c).pool_mean()  # DO NOT DO THIS

  RIGHT - flat combination, single pool:
      result = a.stack(b, c).pool_mean()   # direction correct, MRL meaningful

Two types encode normalization state
-------------------------------------
  RawVector / RawTensor
      Direct model / patch-file output, float32, no normalization.
      Only valid input to head models.

  UnitVector / UnitTensor
      L2-normalized (||v|| = 1 per vector / row).  Property setter always
      normalizes on assignment.  Use for all cosine arithmetic and storage.

.norm and .mean_norm
--------------------
  UnitVector.norm -> float
      The L2 norm of the data *before* normalization.
      For raw.normalize() : original embedding magnitude (intensity).
      For pool_mean()/mean(): MRL (mean resultant length) — directional
      coherence in [0, 1].  MRL ≈ 1 means all inputs pointed the same way;
      MRL ≈ 0 means they cancelled out.

  UnitTensor.norm -> np.ndarray  shape (n,)
      Per-row norms before normalization.  Use for per-row intensity filtering:
          keep = tensor[tensor.norm > threshold]
      Preserved through __getitem__ so tensor[i].norm == tensor.norm[i].

  UnitTensor.mean_norm -> float
      Mean of per-row norms.  Represents average intensity of the bin/batch.

  UnitTensor.std_norm -> float
      Std of per-row norms.  Use for intensity spread / outlier detection.

Two-track analysis pattern
--------------------------
  Intensity (magnitude of raw embeddings)
      → tracked via UnitTensor.norm / UnitTensor.mean_norm
      → filter rows before pooling: rows = tensor[tensor.norm > threshold]
      → after pooling, intensity info is summarized, not preserved

  Coherence (alignment of directions)
      → tracked via UnitVector.norm (MRL) after pool_mean()
      → low MRL = directionally noisy bin; high MRL = tight cluster
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Normalize arr to unit length.  Returns (unit_arr, original_norm)."""
    norm = float(np.linalg.norm(arr))
    unit = (arr / norm).astype(np.float32) if norm > 1e-9 else arr.astype(np.float32)
    return unit, norm


def _normalise_rows(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row-wise normalize.  Returns (unit_arr, original_row_norms)."""
    norms = np.linalg.norm(arr, axis=1, keepdims=True)  # (n, 1)
    norms_1d = norms.squeeze(1)  # (n,)
    safe = np.where(norms < 1e-9, 1.0, norms)
    return (arr / safe).astype(np.float32), norms_1d.astype(np.float32)


# ---------------------------------------------------------------------------
# Single-vector types
# ---------------------------------------------------------------------------


class RawVector:
    """float32, no normalization. Only valid for head model input."""

    __slots__ = ("_data",)

    def __init__(self, data: np.ndarray) -> None:
        self.data = data

    @property
    def data(self) -> np.ndarray:
        return self._data

    @data.setter
    def data(self, value: np.ndarray) -> None:
        self._data = np.asarray(value, dtype=np.float32)

    @property
    def shape(self) -> tuple:
        return self._data.shape

    def __array__(self, dtype=None) -> np.ndarray:  # type: ignore[override]
        return self._data if dtype is None else self._data.astype(dtype)

    def normalize(self) -> UnitVector:
        """L2-normalize and return a UnitVector.  .norm captures original magnitude."""
        return UnitVector(self._data)

    def mean(self, *others: RawVector) -> RawVector:
        """Element-wise mean of self and *others. Returns RawVector."""
        arrays = np.stack([self._data] + [np.asarray(o, dtype=np.float32) for o in others])
        return RawVector(arrays.mean(axis=0))

    def stack(self, *others: RawVector) -> RawTensor:
        """Stack self and *others into a RawTensor."""
        arrays = np.stack([self._data] + [np.asarray(o, dtype=np.float32) for o in others])
        return RawTensor(arrays)

    def __repr__(self) -> str:
        return f"RawVector(shape={self._data.shape})"


class UnitVector:
    """L2-normalized (||v|| = 1). Setter always normalizes. Use for cosine arithmetic."""

    __slots__ = ("_data", "_norm")

    def __init__(self, data: np.ndarray) -> None:
        self.data = data

    @classmethod
    def _from_unit(cls, data: np.ndarray, norm: float) -> UnitVector:
        """Internal: construct from already-unit data with pre-computed norm."""
        obj = cls.__new__(cls)
        obj._data = data.astype(np.float32)
        obj._norm = float(norm)
        return obj

    @property
    def data(self) -> np.ndarray:
        return self._data

    @data.setter
    def data(self, value: np.ndarray) -> None:
        self._data, self._norm = _normalise(np.asarray(value, dtype=np.float32))

    @property
    def norm(self) -> float:
        """L2 norm of data before normalization.  For raw.normalize() this is
        the original embedding intensity.  For pool_mean()/mean() this is the
        mean resultant length (MRL) — a directional coherence measure."""
        return self._norm

    @property
    def shape(self) -> tuple:
        return self._data.shape

    def __array__(self, dtype=None) -> np.ndarray:  # type: ignore[override]
        return self._data if dtype is None else self._data.astype(dtype)

    def stack(self, *others: UnitVector) -> UnitTensor:
        """Stack self and *others into a UnitTensor."""
        arrays = np.stack([self._data] + [np.asarray(o, dtype=np.float32) for o in others])
        norms = np.array([self._norm] + [o._norm for o in others], dtype=np.float32)
        return UnitTensor._from_unit(arrays, norms)

    def __repr__(self) -> str:
        return f"UnitVector(shape={self._data.shape}, norm={self._norm:.4f})"


# ---------------------------------------------------------------------------
# Tensor (batch) types
# ---------------------------------------------------------------------------


class RawTensor:
    """[n, D] batch of raw vectors. Only valid for head model input."""

    __slots__ = ("_data",)

    def __init__(self, data: np.ndarray) -> None:
        self.data = data

    @property
    def data(self) -> np.ndarray:
        return self._data

    @data.setter
    def data(self, value: np.ndarray) -> None:
        self._data = np.asarray(value, dtype=np.float32)

    @property
    def shape(self) -> tuple:
        return self._data.shape

    def __array__(self, dtype=None) -> np.ndarray:  # type: ignore[override]
        return self._data if dtype is None else self._data.astype(dtype)

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx):
        result = self._data[idx]
        return RawVector(result) if result.ndim == 1 else RawTensor(result)

    def normalize(self) -> UnitTensor:
        """Row-wise L2-normalize and return a UnitTensor.  .norm captures row magnitudes."""
        return UnitTensor(self._data)

    def pool_mean(self) -> RawVector:
        """Collapse rows to a single RawVector via mean."""
        return RawVector(self._data.mean(axis=0))

    def pool_max(self) -> RawVector:
        """Collapse rows to a single RawVector via max."""
        return RawVector(self._data.max(axis=0))

    def mean(self, *others: RawTensor) -> RawTensor:
        """Element-wise mean across same-shape tensors. Returns RawTensor."""
        arrays = np.stack([self._data] + [np.asarray(o, dtype=np.float32) for o in others])
        return RawTensor(arrays.mean(axis=0))

    def stack(self, *others: RawTensor) -> RawTensor:
        """Concatenate rows of self and *others into a larger RawTensor."""
        arrays = [self._data] + [np.asarray(o, dtype=np.float32) for o in others]
        return RawTensor(np.concatenate(arrays, axis=0))

    def __repr__(self) -> str:
        return f"RawTensor(shape={self._data.shape})"


class UnitTensor:
    """[n, D] batch, row-wise ||v|| = 1. Setter always row-normalizes."""

    __slots__ = ("_data", "_norm")

    def __init__(self, data: np.ndarray) -> None:
        self.data = data

    @classmethod
    def _from_unit(cls, data: np.ndarray, norms: np.ndarray) -> UnitTensor:
        """Internal: construct from already-unit rows with pre-computed norms."""
        obj = cls.__new__(cls)
        obj._data = data.astype(np.float32)
        obj._norm = norms.astype(np.float32)
        return obj

    @property
    def data(self) -> np.ndarray:
        return self._data

    @data.setter
    def data(self, value: np.ndarray) -> None:
        self._data, self._norm = _normalise_rows(np.asarray(value, dtype=np.float32))

    @property
    def norm(self) -> np.ndarray:
        """Per-row L2 norms before normalization.  Shape (n,).
        For raw_t.normalize() these are the original row magnitudes (intensity).
        Preserved through __getitem__ so tensor[i].norm == tensor.norm[i]."""
        return self._norm

    @property
    def shape(self) -> tuple:
        return self._data.shape

    def __array__(self, dtype=None) -> np.ndarray:  # type: ignore[override]
        return self._data if dtype is None else self._data.astype(dtype)

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, idx):
        result = self._data[idx]
        norms = self._norm[idx]
        if result.ndim == 1:
            return UnitVector._from_unit(result, float(norms))
        return UnitTensor._from_unit(result, norms)

    def pool_mean(self) -> UnitVector:
        """Collapse rows via mean, renormalize. Returns UnitVector.
        .norm of result is the MRL (mean resultant length)."""
        return UnitVector(self._data.mean(axis=0))  # setter computes norm before normalizing

    def pool_max(self) -> UnitVector:
        """Collapse rows via max, renormalize. Returns UnitVector."""
        return UnitVector(self._data.max(axis=0))  # setter computes norm before normalizing

    def mean(self, *others: UnitTensor) -> UnitTensor:
        """Element-wise mean across same-shape tensors, row-renormalized. Returns UnitTensor."""
        arrays = np.stack([self._data] + [np.asarray(o, dtype=np.float32) for o in others])
        return UnitTensor(arrays.mean(axis=0))  # setter row-normalizes and captures norms

    @property
    def mean_norm(self) -> float:
        """Mean of per-row norms.  Average intensity of the batch."""
        return float(self._norm.mean())

    @property
    def std_norm(self) -> float:
        """Std of per-row norms.  Intensity spread; use for outlier detection."""
        return float(self._norm.std())

    def stack(self, *others: UnitTensor) -> UnitTensor:
        """Concatenate rows of self and *others. Returns UnitTensor."""
        data_arrays = [self._data] + [o._data for o in others]
        norm_arrays = [self._norm] + [o._norm for o in others]
        return UnitTensor._from_unit(
            np.concatenate(data_arrays, axis=0),
            np.concatenate(norm_arrays, axis=0),
        )

    def __repr__(self) -> str:
        return f"UnitTensor(shape={self._data.shape}, norm=[{self._norm.min():.4f}..{self._norm.max():.4f}])"
