"""Direct normalized-unit-vector L2 threshold resolution and canonical identity (Plan A P1-S2).

This module is the single canonical home for the threshold and canonical-identity
contract consumed by segmentation configs and the durable segmentation catalog.
It is intentionally free of DuckDB / IO / audio / numpy side effects so strategy
code and tests can import it without any backend.

Threshold contract
------------------
There is exactly ONE threshold semantics: a finite direct L2 distance between
normalized unit vectors.  A resolved threshold is immutable and finite and always
satisfies ``effective == configured`` exactly.  There is no scaling, no
calibration basis, and no p50/percentile multiplier; no second semantics label
exists and ``resolve_threshold`` accepts no semantics selector.  The former
``std_scaled`` and calibration/p50 behavior were removed — they are historical and
never read at runtime.

Canonical encoding
------------------
Each float is rendered via its shortest round-trip ``repr`` (the same binary
float always yields the same text), exponent forms are expanded to fixed point
through :class:`decimal.Decimal`, and ``-0.0`` is normalized to ``0.0``.
Encoders reject non-finite inputs.

Boundary semantics
------------------
Strict ``>`` boundary comparison (a patch is a boundary when its distance to the
running spherical centroid is strictly greater than the threshold) is owned by the
segmentation helper in :mod:`helpers.segmentation` / the temporal segment code,
not by this module.  This module only resolves and canonically encodes the finite
threshold value.

Encoder version
---------------
``config_encoder_version()`` is the SHA-256 of the complete bytes of this module,
computed lazily on first use and refreshed whenever the module file's metadata
(mtime or size) changes.  It is deliberately whole-module (not an AST subset), so
any content edit — including a comment or formatting change — conservatively
triggers a new version.  There is no manual bump or allowlist.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

#: The one and only threshold semantics: a finite direct L2 distance between
#: normalized unit vectors.  Kept as a named constant so ``ThresholdResolution``
#: values and catalog manifests compare against a single spelling.
DIRECT_L2: Final[str] = "direct_l2"

#: Default outlier window (consecutive boundary patches absorbed before a hard
#: split).  Residing here so canonical hash computation and segmentation callers
#: share one spelling.  The strict ``>`` boundary semantics live downstream.
DEFAULT_OUTLIER_WINDOW: Final[int] = 3

#: PTC segmentation strategy version (running spherical centroid + strict ``>``).
PTC_STRATEGY_VERSION: Final[int] = 1

#: Absolute path of this module file, used for whole-module encoder-version hashing.
_MODULE_PATH: Final[Path] = Path(__file__)


@dataclass(frozen=True)
class ThresholdResolution:
    """Immutable result of resolving a configured threshold.

    Attributes
    ----------
    configured:
        The finite configured threshold (an L2 distance between unit vectors).
    effective:
        The finite effective threshold.  By construction ``effective == configured``
        exactly — there is exactly one mode and no calibration step.
    semantics:
        Always :data:`DIRECT_L2` (``"direct_l2"``).  No other semantics exists.
    encoder_version:
        The whole-module :func:`config_encoder_version` at resolution time, so the
        recorded contract pins the exact encoder source that produced it.
    """

    configured: float
    effective: float
    semantics: str
    encoder_version: str

    def __post_init__(self) -> None:
        configured = _coerce_finite(self.configured, "configured")
        effective = _coerce_finite(self.effective, "effective")
        if self.semantics != DIRECT_L2:
            raise ValueError(f"only {DIRECT_L2!r} threshold semantics exists; got {self.semantics!r}")
        # ``effective == configured`` exactly: no scaling, no calibration basis.
        if effective != configured:
            raise ValueError(
                f"effective must equal configured exactly (single direct-L2 mode); "
                f"configured={configured!r} effective={effective!r}"
            )
        object.__setattr__(self, "configured", configured)
        object.__setattr__(self, "effective", effective)
        if not isinstance(self.encoder_version, str) or not self.encoder_version:
            raise ValueError("encoder_version must be non-empty text")


def _coerce_finite(value: object, name: str) -> float:
    """Coerce ``value`` to a finite float, rejecting non-numeric and non-finite inputs."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric; got bool")
    if isinstance(value, (str, bytes, list, tuple, dict, set)) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric; got {type(value).__name__}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite; got {value!r}")
    return result


def _coerce_int(value: object, name: str) -> int:
    """Coerce ``value`` to an int, rejecting bool and non-int inputs."""
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an int; got bool")
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an int; got {type(value).__name__}")
    return value


def resolve_threshold(configured: object) -> ThresholdResolution:
    """Resolve a configured threshold into a direct-L2 :class:`ThresholdResolution`.

    There is exactly one mode: the configured value is applied directly as a
    finite L2 distance between normalized unit vectors (``effective == configured``
    exactly).  Non-finite or non-numeric inputs are rejected.  No ``semantics`` or
    ``calibration_record`` selector exists; scaled/calibration/p50 resolution is not
    representable.
    """
    finite = _coerce_finite(configured, "configured")
    return ThresholdResolution(
        configured=finite,
        effective=finite,
        semantics=DIRECT_L2,
        encoder_version=config_encoder_version(),
    )


# ---------------------------------------------------------------------------
# Canonical numeric / text encoders
# ---------------------------------------------------------------------------


def canonical_float(value: object) -> str:
    """Deterministic finite shortest-round-trip encoding with ``-0.0`` normalized.

    The same binary float always yields the same text; exponent forms are expanded
    to fixed point.  NaN and ±Inf are rejected.
    """
    finite = _coerce_finite(value, "value")
    if finite == 0.0:  # normalizes -0.0 and +0.0 to a single spelling
        return "0.0"
    # Shortest round-trip repr (same binary float -> same text), then expand any
    # exponent form to fixed point so there is no spelling/e-notation ambiguity.
    text = repr(finite)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def canonical_int(value: object) -> str:
    """Deterministic integer encoding (rejects bool and non-int)."""
    return str(_coerce_int(value, "value"))


def canonical_text(value: object, name: str = "text") -> str:
    """Deterministic text encoding; requires non-empty (non-blank) text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def canonical_bin_mode(value: object) -> str:
    """Deterministic bin-mode encoding (validated against no fixed set here)."""
    return canonical_text(value, "bin_mode")


def canonical_outlier_window(value: object) -> str:
    """Deterministic outlier-window encoding (validated as a positive int)."""
    window = _coerce_int(value, "outlier_window")
    if window < 1:
        raise ValueError(f"outlier_window must be >= 1; got {window}")
    return str(window)


def canonical_strategy_version(value: object) -> str:
    """Deterministic strategy-version encoding (validated as a positive int)."""
    version = _coerce_int(value, "strategy_version")
    if version < 1:
        raise ValueError(f"strategy_version must be >= 1; got {version}")
    return str(version)


# ---------------------------------------------------------------------------
# Canonical config inputs and hash
# ---------------------------------------------------------------------------


def canonical_config_inputs(
    *,
    backbone: str,
    bin_mode: str,
    threshold: float,
    outlier_window: int,
    strategy_version: int,
    encoder_version: str,
) -> str:
    """Deterministic tagged serialization of the seg_config key inputs.

    Field order is fixed and documented: backbone, bin_mode, threshold (the
    single effective==configured direct-L2 value), outlier_window,
    strategy_version, encoder_version.
    """
    ordered = [
        f"backbone={canonical_text(backbone, 'backbone')}",
        f"bin_mode={canonical_bin_mode(bin_mode)}",
        f"threshold={canonical_float(threshold)}",
        f"outlier_window={canonical_outlier_window(outlier_window)}",
        f"strategy_version={canonical_strategy_version(strategy_version)}",
        f"encoder_version={canonical_text(encoder_version, 'encoder_version')}",
    ]
    return "|".join(ordered)


def canonical_config_hash(
    *,
    backbone: str,
    bin_mode: str,
    threshold: float,
    outlier_window: int,
    strategy_version: int,
    encoder_version: str,
) -> str:
    """Deterministic SHA-256 canonical identity over the seg_config key ordering.

    All parameters are required keyword inputs.  ``threshold`` is the single
    direct-L2 value (``configured == effective``); there is no semantics or
    calibration input because only one semantics exists.  The ``encoder_version``
    is included so any encoder source change conservatively invalidates identity.
    """
    payload = canonical_config_inputs(
        backbone=backbone,
        bin_mode=bin_mode,
        threshold=threshold,
        outlier_window=outlier_window,
        strategy_version=strategy_version,
        encoder_version=encoder_version,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Whole-module encoder version
# ---------------------------------------------------------------------------

#: Cached (mtime_ns, size, version); refreshed when file metadata changes.
_encoder_version_cache: tuple[int, int, str] | None = None


def _module_sha256(data: bytes) -> str:
    """SHA-256 hexdigest of raw module bytes (testable against arbitrary bytes)."""
    return hashlib.sha256(data).hexdigest()


def config_encoder_version() -> str:
    """SHA-256 of the complete bytes of ``helpers/thresholds.py``.

    Computed lazily on first use and cached; the cache is keyed by the module
    file's (mtime, size) so any on-disk content change — including a comment or
    formatting edit — refreshes the value.  There is no manual bump or allowlist.
    """
    global _encoder_version_cache
    stat = _MODULE_PATH.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    if _encoder_version_cache is not None and _encoder_version_cache[:2] == key:
        return _encoder_version_cache[2]
    version = _module_sha256(_MODULE_PATH.read_bytes())
    _encoder_version_cache = (key[0], key[1], version)
    return version
