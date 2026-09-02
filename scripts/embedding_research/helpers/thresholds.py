"""Pure threshold-resolution and canonical-identity contracts (Plan A, Phase 2).

This module is intentionally free of DuckDB / IO / audio / numpy-array side
effects so strategy code and tests can import it without any backend.  It is the
canonical home for two things:

* :class:`ThresholdResolution` and :func:`resolve_threshold` — the P2-S1 pure
  configured-vs-effective threshold contract.  ``direct_l2`` is the default and
  guarantees ``effective == configured``; ``std_scaled`` is an explicit
  legacy-fidelity opt-in that *requires* an explicit calibration basis and
  records that basis plus the computed effective value.  The old implicit
  ``x0.1`` fallback never appears here in any form.
* the P2-S3 deterministic canonical numeric/text encodings and config-hash
  inputs consumed by later ``seg_config`` rows (deterministic hashes and integer
  application identities per R9).  These apply to *new* identity/hash
  computation only — legacy on-disk cache-path lookup (``helpers.binning``
  ``threshold_key``/``canonical_threshold``) is deliberately left untouched so
  existing archival readers keep resolving.

Canonical numeric-format decision (documented choice + rationale)
----------------------------------------------------------------
Each float is rendered via its shortest round-trip ``repr`` (the same binary
float always yields the same text, so ``0.1`` and ``1e-1`` — the same double —
are identical), with any exponent form expanded to fixed-point by parsing the
repr digits through ``decimal.Decimal`` (so there is never scientific-notation
ambiguity), and ``-0.0`` normalised to ``0.0``.  Fixed-precision formatting was
rejected because rounding to a fixed number of places can conflate two distinct
floats; shortest-round-trip text cannot, and is locale-independent.  All
encoders reject non-finite inputs.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, get_args

# ── Semantics vocabulary ───────────────────────────────────────────────────────

#: The only two threshold-semantics labels (used verbatim in ``seg_config.semantics``).
ThresholdSemantics = Literal["direct_l2", "std_scaled"]

DIRECT_L2 = "direct_l2"
STD_SCALED = "std_scaled"

_SEMANTICS: frozenset[str] = frozenset(get_args(ThresholdSemantics))

# Calibration-record vocabulary: the calibration basis is recorded canonically as
# a flat mapping carrying at least ``statistic`` (a label such as ``"p50"``) and
# ``value`` (the numeric multiplier basis).  ``statistic`` names *which* statistic
# is the basis; ``value`` is the finite, positive multiplier applied to
# ``configured`` to produce the legacy ``std_scaled`` effective threshold.  This is
# a new explicit vocabulary (the legacy producer stored bare ``p10..sigma_d`` dicts
# that never identified the basis, which is exactly why the implicit path was dead).
_CALIBRATION_STATISTIC_KEY = "statistic"
_CALIBRATION_VALUE_KEY = "value"

# ── Identity-schema constants (P2-S3) ─────────────────────────────────────────
#: Canonical segmentation outlier window (matches ``helpers.binning.OUTLIER_WINDOW``).
DEFAULT_OUTLIER_WINDOW: int = 3
#: Canonical strategy version for the current PTC running-centroid segmentation
#: track (the algorithm is preserved; only the threshold semantics default changed).
#: Later plans (C) persist this in ``seg_config.strategy_version``.
PTC_STRATEGY_VERSION: int = 1


# ── Numeric coercion / finiteness ──────────────────────────────────────────────


def _coerce_finite(x: object, name: str) -> float:
    """Return *x* as a finite float, raising TypeError/ValueError with a clear message."""
    if isinstance(x, (bool, str)):
        raise TypeError(f"{name} must be a real number; got {type(x).__name__}")
    try:
        value = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real number; got {type(x).__name__}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite (no NaN/Inf); got {x!r}")
    return value


def _coerce_int(x: object, name: str) -> int:
    """Return *x* as an integer, rejecting bools and non-integral values."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise TypeError(f"{name} must be an integer; got {type(x).__name__}")
    return x


def validate_semantics(semantics: object) -> str:
    """Validate a threshold-semantics label against the canonical vocabulary."""
    if semantics not in _SEMANTICS:
        raise ValueError(f"Unknown threshold semantics {semantics!r}. Allowed: {sorted(_SEMANTICS)}")
    return semantics  # type: ignore[return-value]


# ── Threshold resolution (P2-S1) ──────────────────────────────────────────────


@dataclass(frozen=True)
class ThresholdResolution:
    """Immutable result of resolving a configured threshold.

    Attributes
    ----------
    configured:
        The configured threshold (direct unit-vector L2 distance by default).
    effective:
        The threshold actually applied during segmentation.  For ``direct_l2``
        this is exactly ``configured``; for ``std_scaled`` it is
        ``configured x calibration-basis``.
    semantics:
        ``"direct_l2"`` or ``"std_scaled"`` (the calibration-track label).
    calibration_record:
        Read-only mapping carrying the calibration basis for ``std_scaled``, or
        ``None`` for ``direct_l2``.  Never object identity — a stable serialization
        is provided by :func:`canonical_calibration_record`.

    All numeric fields are guaranteed finite; non-finite inputs are rejected at
    construction.  Instances are immutable (frozen dataclass + a read-only
    ``MappingProxyType`` wrapper around any calibration record).
    """

    configured: float
    effective: float
    semantics: str
    calibration_record: object  # MappingProxyType | None

    def __post_init__(self) -> None:
        configured = _coerce_finite(self.configured, "configured")
        effective = _coerce_finite(self.effective, "effective")
        semantics = validate_semantics(self.semantics)
        calibration_record = self._freeze_calibration(self.calibration_record)
        # Normalise stored values (floats) and replace any mutable calibration
        # record with a read-only proxy so the resolution is truly immutable.
        object.__setattr__(self, "configured", configured)
        object.__setattr__(self, "effective", effective)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "calibration_record", calibration_record)

    @staticmethod
    def _freeze_calibration(record: object) -> object:
        if record is None:
            return None
        if not isinstance(record, Mapping):
            raise TypeError(f"calibration_record must be a Mapping or None; got {type(record).__name__}")
        return MappingProxyType(dict(record))


def _require_calibration_basis(calibration_record: object) -> float:
    """Extract and validate the explicit calibration basis for ``std_scaled``."""
    if calibration_record is None:
        raise ValueError(
            "std_scaled requires an explicit calibration_record carrying the calibration "
            f"basis (a Mapping with {_CALIBRATION_STATISTIC_KEY!r} and {_CALIBRATION_VALUE_KEY!r}); "
            "no implicit p50/0.1 fallback is permitted"
        )
    if not isinstance(calibration_record, Mapping):
        raise TypeError(f"calibration_record must be a Mapping for std_scaled; got {type(calibration_record).__name__}")
    statistic = calibration_record.get(_CALIBRATION_STATISTIC_KEY)
    if not isinstance(statistic, str) or not statistic.strip():
        raise ValueError(
            f"std_scaled calibration_record must identify its basis with {_CALIBRATION_STATISTIC_KEY!r}; "
            f"got {statistic!r}"
        )
    value = calibration_record.get(_CALIBRATION_VALUE_KEY)
    basis = _coerce_finite(value, f"calibration_record[{_CALIBRATION_VALUE_KEY!r}]")
    if basis <= 0.0:
        raise ValueError(f"std_scaled calibration basis must be a finite positive distance; got {basis!r}")
    return basis


def resolve_threshold(
    configured: object,
    *,
    semantics: object = DIRECT_L2,
    calibration_record: object = None,
) -> ThresholdResolution:
    """Resolve a configured threshold to its effective segmentation threshold.

    Parameters
    ----------
    configured:
        The configured threshold — a finite real number.
    semantics:
        ``"direct_l2"`` (default) or ``"std_scaled"`` (explicit legacy opt-in).
    calibration_record:
        A Mapping carrying the explicit calibration basis (``statistic`` +
        ``value``).  Required for ``std_scaled``; ignored/None for ``direct_l2``.

    Returns
    -------
    ThresholdResolution
        Immutable, finite, deterministic.  ``direct_l2`` returns
        ``effective == configured`` exactly with no calibration record; the
        explicit ``std_scaled`` path computes
        ``effective = configured x basis`` and records the basis.
    """
    configured_f = _coerce_finite(configured, "configured")
    semantics_s = validate_semantics(semantics)

    if semantics_s == DIRECT_L2:
        # effective == configured exactly (no arithmetic), calibration basis is
        # semantically meaningless for a direct distance and is omitted.
        return ThresholdResolution(
            configured=configured_f,
            effective=configured_f,
            semantics=DIRECT_L2,
            calibration_record=None,
        )

    # std_scaled: explicit opt-in only; the basis must be explicit and usable.
    basis = _require_calibration_basis(calibration_record)
    effective = configured_f * basis
    return ThresholdResolution(
        configured=configured_f,
        effective=effective,
        semantics=STD_SCALED,
        calibration_record=calibration_record,
    )


# ── Canonical encoding (P2-S3) ────────────────────────────────────────────────


def canonical_float(x: object) -> str:
    """Deterministic, locale-independent, exponent-free encoding of a finite float.

    Same binary float -> same text (``0.1`` and ``1e-1`` are the same double and
    both encode as ``"0.1"``).  Rejects non-finite inputs.
    """
    value = _coerce_finite(x, "value")
    if value == 0.0:
        return "0.0"
    text = repr(value)
    if "e" in text or "E" in text:
        # Expand exponent form to fixed-point by parsing the exact repr digits.
        return format(Decimal(text), "f")
    return text


def canonical_int(x: object, name: str = "value") -> str:
    """Deterministic integer encoding (outlier window, strategy version, alias id)."""
    return str(_coerce_int(x, name))


def canonical_text(x: object, name: str = "value") -> str:
    """Deterministic text encoding (bin mode / backbone / labels)."""
    if isinstance(x, bool):
        raise TypeError(f"{name} must be text; got bool")
    text = str(x).strip()
    if not text:
        raise ValueError(f"{name} must be non-empty text")
    return text


def canonical_bin_mode(bin_mode: object) -> str:
    return canonical_text(bin_mode, "bin_mode")


def canonical_outlier_window(window: object) -> str:
    return canonical_int(window, "outlier_window")


def canonical_strategy_version(version: object) -> str:
    return canonical_int(version, "strategy_version")


def canonical_semantics(semantics: object) -> str:
    return validate_semantics(semantics)


def canonical_alias(alias_of_config_id: object) -> str:
    """Canonical alias target: ``"none"`` when unaliased, else the integer id."""
    if alias_of_config_id is None:
        return "none"
    return canonical_int(alias_of_config_id, "alias_of_config_id")


def canonical_threshold(
    configured: object,
    effective: object,
    semantics: object = DIRECT_L2,
) -> str:
    """Canonical threshold identity carrying both values and the semantics label.

    Sensitive to semantics: ``direct_l2`` and ``std_scaled`` of the same
    configured value encode differently (different label), so their config
    hashes never collide.
    """
    return (
        f"{validate_semantics(semantics)}:"
        f"configured={canonical_float(configured)}:"
        f"effective={canonical_float(effective)}"
    )


def canonical_threshold_of(resolution: ThresholdResolution) -> str:
    """Canonical threshold identity of an existing resolution (see :func:`canonical_threshold`)."""
    return canonical_threshold(resolution.configured, resolution.effective, resolution.semantics)


def canonical_calibration_record(record: object) -> str:
    """Stable serialization of a calibration basis (not object identity).

    Keys are sorted; numeric values use :func:`canonical_float`; text values use
    :func:`canonical_text`.  Two equal-content records in different insertion
    order serialize identically.  ``None`` encodes as ``"none"``.
    """
    if record is None:
        return "none"
    if not isinstance(record, Mapping):
        raise TypeError(f"calibration_record must be a Mapping or None; got {type(record).__name__}")
    parts: list[str] = []
    for key in sorted(record, key=str):
        value = record[key]
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        elif isinstance(value, str):
            encoded = canonical_text(value, f"calibration_record[{key!r}]")
        else:
            encoded = canonical_float(value)
        parts.append(f"{canonical_text(key, 'calibration_record key')}={encoded}")
    return ";".join(parts)


def canonical_config_inputs(
    *,
    backbone: object,
    bin_mode: object,
    threshold_configured: object,
    threshold_effective: object,
    semantics: object = DIRECT_L2,
    calibration_record: object = None,
    outlier_window: object = DEFAULT_OUTLIER_WINDOW,
    strategy_version: object = PTC_STRATEGY_VERSION,
    alias_of_config_id: object = None,
) -> str:
    """Canonical pre-hash string in the seg_config ordering.

    Field order is fixed (per the parts ledger): backbone, bin mode,
    threshold_configured, threshold_effective, semantics, calibration_record,
    outlier_window, strategy_version, alias target.
    """
    fields: list[tuple[str, str]] = [
        ("backbone", canonical_text(backbone, "backbone")),
        ("bin_mode", canonical_bin_mode(bin_mode)),
        ("threshold_configured", canonical_float(threshold_configured)),
        ("threshold_effective", canonical_float(threshold_effective)),
        ("semantics", canonical_semantics(semantics)),
        ("calibration_record", canonical_calibration_record(calibration_record)),
        ("outlier_window", canonical_outlier_window(outlier_window)),
        ("strategy_version", canonical_strategy_version(strategy_version)),
        ("alias_of_config_id", canonical_alias(alias_of_config_id)),
    ]
    return "|".join(f"{key}={value}" for key, value in fields)


def canonical_config_hash(
    *,
    backbone: object,
    bin_mode: object,
    threshold_configured: object,
    threshold_effective: object,
    semantics: object = DIRECT_L2,
    calibration_record: object = None,
    outlier_window: object = DEFAULT_OUTLIER_WINDOW,
    strategy_version: object = PTC_STRATEGY_VERSION,
    alias_of_config_id: object = None,
) -> str:
    """Deterministic sha256 config hash over :func:`canonical_config_inputs`.

    The returned hex digest is stable across runs and equivalent numeric
    spellings, and is sensitive to every segmentation parameter including the
    semantics label and the calibration record.
    """
    payload = canonical_config_inputs(
        backbone=backbone,
        bin_mode=bin_mode,
        threshold_configured=threshold_configured,
        threshold_effective=threshold_effective,
        semantics=semantics,
        calibration_record=calibration_record,
        outlier_window=outlier_window,
        strategy_version=strategy_version,
        alias_of_config_id=alias_of_config_id,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
