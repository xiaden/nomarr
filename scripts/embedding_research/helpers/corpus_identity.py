"""Canonical corpus-identity and comparability helpers (corrective contract).

This module is the single authoritative owner of the corrected corpus-wide
identities:

* :func:`search_representation_id` hashes ONLY the inputs that change the scored
  search result (semantics, observation/mask identity, ordered corpus population,
  ordered medoid source indices, normalized searchable weights, searchable count).
  ``threshold_id``, structural identity, boundaries, absorbed locations, and any
  transient per-song ``geometry_id`` are excluded, so representations with
  different geometry ids but identical scoring inputs collapse.
* :func:`structural_identity` is the canonical binding rule for the separate structural
  digest (over ``threshold_id``, boundaries, and absorbed locations).  The runtime production
  owner of the persisted structural digest is ``analyze_all_thresholds`` in
  ``common/threshold_analysis.py`` (payload ``{experiment, threshold_id, threshold_index,
  ranges, absorbed_indices}``); this helper is the canonical rule/preimage used by tests and
  NEVER feeds the search hash.
* :func:`classify_representation` classifies one representation/query as
  comparable/defined/eligible and records explicit non-comparability reasons.

The module is pure CPU/stdlib (no DuckDB, IO, NumPy, or segmentation runtime) so
derived analysis phases can import it without crossing a boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

__all__ = [
    "CorpusSongSearchInput",
    "RepresentationState",
    "classify_representation",
    "search_representation_id",
    "structural_identity",
]


@dataclass(frozen=True)
class RepresentationState:
    """Comparability/definedness/eligibility state with explicit reasons."""

    comparable: bool
    defined: bool
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("comparable", "defined", "eligible"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))


def _sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _int(value, name)


def _canonical(value: object) -> object:
    """Recursively canonicalize tuples/lists/ints/floats/strings/None."""
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (bool, int)):
        return int(value)
    if isinstance(value, float):
        return _float(value, "value")
    if isinstance(value, str):
        return value
    if value is None:
        return None
    raise ValueError(f"unsupported canonical value type: {type(value)!r}")


@dataclass(frozen=True)
class CorpusSongSearchInput:
    """One ordered song's complete contribution to a corpus search identity."""

    song_id: str
    observation_group_sha256: str
    mask_identity: str
    medoid_source_indices: tuple[int | None, ...]
    normalized_searchable_weights: tuple[float, ...]
    searchable_count: int


def search_representation_id(
    *,
    experiment: str,
    scoring_semantics_version: int,
    geometry_semantics_version: str,
    numerical_profile_digest: str,
    ordered_song_inputs: tuple[CorpusSongSearchInput, ...],
) -> str:
    """Return the canonical hash for one complete ordered corpus input roster.

    The DTO is the sole API: every ordered song contributes its observation and mask
    identities, source medoids, normalized positive weights, and searchable count.
    Threshold and structural identities remain separate evidence axes.
    """
    inputs = tuple(ordered_song_inputs)
    if not inputs or any(not isinstance(item, CorpusSongSearchInput) for item in inputs):
        raise ValueError("ordered_song_inputs must be a non-empty tuple of CorpusSongSearchInput values")
    payload = {
        "experiment": _text(experiment, "experiment"),
        "scoring_semantics_version": _int(scoring_semantics_version, "scoring_semantics_version"),
        "geometry_semantics_version": _text(geometry_semantics_version, "geometry_semantics_version"),
        "numerical_profile_digest": _text(numerical_profile_digest, "numerical_profile_digest"),
        "ordered_song_inputs": [
            {
                "song_id": item.song_id,
                "observation_group_sha256": item.observation_group_sha256,
                "mask_identity": item.mask_identity,
                "medoid_source_indices": [
                    _optional_int(value, "medoid_source_indices") for value in item.medoid_source_indices
                ],
                "normalized_searchable_weights": [
                    _float(value, "normalized_searchable_weights") for value in item.normalized_searchable_weights
                ],
                "searchable_count": _int(item.searchable_count, "searchable_count"),
            }
            for item in inputs
        ],
    }
    return _sha256(payload)


def structural_identity(
    *,
    threshold_id: str,
    boundaries: object,
    absorbed_locations: object,
) -> str:
    """Return the separate lowercase 64-hex structural identity digest."""
    payload = {
        "threshold_id": _text(threshold_id, "threshold_id"),
        "boundaries": _canonical(boundaries),
        "absorbed_locations": _canonical(absorbed_locations),
    }
    return _sha256(payload)


def classify_representation(
    *,
    alignment_ok: bool,
    searchable_count: int,
    medoid_defined: bool,
    candidate_count: int,
    label_defined: bool,
) -> RepresentationState:
    """Classify one representation/query; explicit reasons on non-comparability."""
    if (
        not isinstance(alignment_ok, bool)
        or not isinstance(medoid_defined, bool)
        or not isinstance(label_defined, bool)
    ):
        raise ValueError("alignment_ok, medoid_defined, and label_defined must be boolean")
    if isinstance(searchable_count, bool) or not isinstance(searchable_count, int):
        raise ValueError("searchable_count must be an integer")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
        raise ValueError("candidate_count must be an integer")
    reasons: list[str] = []
    if not alignment_ok:
        reasons.append("alignment_failed")
    if searchable_count <= 0:
        reasons.append("zero_searchable")
    if not medoid_defined:
        reasons.append("no_medoid")
    if candidate_count <= 0:
        reasons.append("no_candidates")
    if reasons:
        return RepresentationState(False, False, False, tuple(reasons))
    if not label_defined:
        return RepresentationState(True, True, False, ("label_missing",))
    return RepresentationState(True, True, True, ())


def _as_sequence(value: object, name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
        raise ValueError(f"{name} must be an ordered sequence")
    # ``value`` is ``object``; the hasattr guard above proves it is iterable at runtime.
    return tuple(value)  # type: ignore[arg-type]
