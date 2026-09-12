"""Pinned numerical execution profile for Gram geometry."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Any

GEOMETRY_SEMANTICS_VERSION = "gram-ptc-v1"
GEOMETRY_SERIALIZATION_VERSION = "float32-le-c-order-v1"
SCALAR_KERNEL_VERSION = "scalar-f32-v1"


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "uninstalled"


@dataclass(frozen=True)
class GeometryProfile:
    """Immutable environment and arithmetic identity used to create geometry."""

    manifest: tuple[tuple[str, str], ...]
    digest: str

    @classmethod
    def current(cls) -> GeometryProfile:
        values: dict[str, str] = {
            "geometry_semantics_version": GEOMETRY_SEMANTICS_VERSION,
            "geometry_serialization_version": GEOMETRY_SERIALIZATION_VERSION,
            "scalar_kernel_version": SCALAR_KERNEL_VERSION,
            "python_version": platform.python_version(),
            "numpy_version": _version("numpy"),
            "duckdb_version": _version("duckdb"),
            "os": platform.system(),
            "architecture": platform.machine(),
            "byte_order": sys.byteorder,
            "blas_provider": _blas_provider(),
            "blas_threads": os.environ.get("OPENBLAS_NUM_THREADS", "unknown"),
            "fpu_denormal_policy": "environment-observable-only",
            "normalization_policy": "scalar-float32-ascending-dimension",
            "threshold_arithmetic_policy": "float32-canonical-indexed",
            "scalar_operation_manifest": "f32-add-mul-div-sqrt-max-ascending-v1",
        }
        manifest = tuple(sorted(values.items()))
        digest = profile_digest(dict(manifest))
        return cls(manifest=manifest, digest=digest)

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> GeometryProfile:
        if (
            not isinstance(manifest, dict)
            or not manifest
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in manifest.items())
        ):
            raise ValueError("geometry profile manifest must be a non-empty string mapping")
        canonical = dict(sorted(manifest.items()))
        digest = profile_digest(canonical)
        return cls(manifest=tuple(canonical.items()), digest=digest)

    def to_manifest(self) -> dict[str, str]:
        return dict(self.manifest)


def canonical_profile_json(manifest: dict[str, Any]) -> bytes:
    """Return the canonical sorted/compact ASCII JSON bytes of a profile manifest."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def profile_digest(manifest: dict[str, Any]) -> str:
    """Return the lowercase SHA-256 digest of the canonical profile manifest bytes."""
    return hashlib.sha256(canonical_profile_json(manifest)).hexdigest()


def _blas_provider() -> str:
    try:
        import numpy as np

        config = getattr(np, "__config__", None)
        return str(getattr(config, "CONFIG", "numpy-config"))
    except (ImportError, AttributeError, TypeError):
        return "unknown"


__all__ = [
    "GEOMETRY_SEMANTICS_VERSION",
    "GEOMETRY_SERIALIZATION_VERSION",
    "SCALAR_KERNEL_VERSION",
    "GeometryProfile",
    "canonical_profile_json",
    "profile_digest",
]
