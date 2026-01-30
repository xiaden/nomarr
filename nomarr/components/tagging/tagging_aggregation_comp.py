"""Tag aggregation logic - mood tiers, label simplification, and conflict resolution."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from nomarr.components.ml.ml_calibration_comp import apply_minmax_calibration
from nomarr.helpers.dto.ml_dto import HeadOutput
from nomarr.helpers.dto.tagging_dto import BuildTierTermSetsResult

logger = logging.getLogger(__name__)


def load_calibrations(models_dir: str, calibrate_heads: bool = False) -> dict[str, dict[str, Any]]:
    """DEPRECATED: Load calibration bundles from disk (transport artifacts only).

    WARNING: This function is for BUNDLE IMPORT/EXPORT workflows only.
    Production processing/recalibration must NEVER call this directly.

    ARCHITECTURE:
    - Bundles are TRANSPORT ARTIFACTS for distribution (e.g., nom-cal repo)
    - Database (calibration_state) is the SINGLE SOURCE OF TRUTH
    - Use import_calibration_bundle_wf to parse bundles into DB
    - Use calibration_loader_wf to read from DB for processing/tagging

    DO NOT USE THIS IN:
    - process_file_wf (use calibration_loader_wf with DB)
    - write_calibrated_tags_wf (use calibration_loader_wf with DB)
    - Any production processing path

    Args:
        models_dir: Path to models directory containing bundle files
        calibrate_heads: If True, load versioned bundles (dev mode). If False, load reference bundles (default)

    Returns:
        Dictionary mapping tag keys to calibration parameters
        Empty dict if no bundles found (graceful degradation)

    Note:
        This is retained for backward compatibility with import/export workflows.
        Will be moved to workflows/calibration in future refactor.

    """
    calibrations: dict[str, Any] = {}
    try:
        models_path = Path(models_dir)
        if not models_path.exists():
            logger.debug(f"[calibration] Models directory not found: {models_dir}")
            return calibrations
        if calibrate_heads:
            calib_files = list(models_path.rglob("*-calibration-v*.json"))
            logger.debug(f"[calibration] Loading versioned calibration bundles (dev mode): {len(calib_files)} found")
        else:
            calib_files = list(models_path.rglob("*-calibration.json"))
            calib_files = [f for f in calib_files if "-calibration-v" not in f.name]
            logger.debug(f"[calibration] Loading reference calibration bundles: {len(calib_files)} found")
        for calib_file in calib_files:
            try:
                with open(calib_file, encoding="utf-8") as f:
                    calib_data = json.load(f)
                labels = calib_data.get("labels", {})
                calibrations.update(labels)
            except Exception as e:
                logger.warning(f"[calibration] Failed to load {calib_file}: {e}")
        logger.debug(f"[calibration] Loaded calibrations for {len(calibrations)} labels")
    except Exception as e:
        logger.exception(f"[calibration] Error loading calibrations: {e}")
    return calibrations


def get_prefix(backbone: str) -> str:
    """Get tag prefix based on backbone folder name."""
    if backbone == "yamnet":
        return "yamnet_"
    if backbone == "vggish":
        return "vggish_"
    if backbone == "effnet":
        return "effnet_"
    if backbone == "musicnn":
        return "musicnn_"
    return ""


def normalize_tag_label(label: str) -> str:
    """Normalize model label for tag key consistency.

    Converts 'non_*' to 'not_*' for consistent naming.
    Example: 'non_happy' -> 'not_happy'

    Args:
        label: Raw label from model (e.g., 'happy', 'non_happy')

    Returns:
        Normalized label for use in tag keys

    """
    if label.startswith("non_"):
        return f"not_{label[4:]}"
    return label


def simplify_label(base_key: str) -> str:
    """Map model-prefixed labels to human terms: 'yamnet_non_happy' -> 'not happy', 'effnet_bright' -> 'bright'."""
    label_stripped = base_key.lower()
    for pref in ("yamnet_", "vggish_", "effnet_", "musicnn_"):
        if label_stripped.startswith(pref):
            label_stripped = label_stripped[len(pref) :]
            break
    if label_stripped.startswith("non_"):
        core = label_stripped[4:]
        return f"not {core.replace('_', ' ')}"
    if label_stripped.startswith("not_"):
        core = label_stripped[4:]
        return f"not {core.replace('_', ' ')}"
    return label_stripped.replace("_", " ")


def add_regression_mood_tiers(regression_heads: list[tuple[Any, list[float]]], framework_version: str) -> list[Any]:
    """Convert regression head predictions (approachability, engagement) into HeadOutput objects.

    Uses versioned tag keys from HeadInfo.build_versioned_tag_key() instead of hardcoded prefixes.

    Regression heads output INTENSITY values (0-1), not probabilities:
    - High values (>0.7) indicate STRONG presence of the attribute
    - Low values (<0.3) indicate STRONG presence of the opposite attribute
    - Middle values (0.3-0.7) are neutral/ambiguous

    ALWAYS creates a HeadOutput with the mean value (clamped to [0, 1]).
    Variance only affects TIER assignment:
    - High variance → no tier (unreliable measurement)
    - Low variance + extreme value → tier assigned based on confidence

    Args:
        regression_heads: List of (HeadInfo, segment_values) tuples for regression heads
        framework_version: Runtime Essentia version (e.g., "2.1b6.dev1389")

    Returns:
        List of HeadOutput objects with tier information

    """
    if not regression_heads:
        return []
    outputs: list[HeadOutput] = []
    for head_info, segment_values in regression_heads:
        head_name = head_info.name
        if not segment_values or head_name not in _MOOD_MAPPING:
            continue
        arr = np.array(segment_values)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))
        mean_val = max(0.0, min(1.0, mean_val))
        high_term, low_term = _MOOD_MAPPING[head_name]
        is_high = mean_val >= _STRONG_THRESHOLD
        is_low = mean_val <= _WEAK_THRESHOLD
        if is_high:
            mood_term = high_term
        elif is_low:
            mood_term = low_term
        else:
            model_key_high, calib_id_high = head_info.build_versioned_tag_key(
                high_term, framework_version=framework_version, calib_method="none", calib_version=0,
            )
            model_key_low, calib_id_low = head_info.build_versioned_tag_key(
                low_term, framework_version=framework_version, calib_method="none", calib_version=0,
            )
            outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=model_key_high,
                    label=high_term,
                    value=mean_val,
                    tier=None,
                    calibration_id=calib_id_high,
                ),
            )
            outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=model_key_low,
                    label=low_term,
                    value=1.0 - mean_val,
                    tier=None,
                    calibration_id=calib_id_low,
                ),
            )
            logger.debug(
                f"[aggregation] Regression neutral: {head_name} → both {high_term}/{low_term} (mean={mean_val:.3f}, std={std_val:.3f})",
            )
            continue
        model_key, calibration_id = head_info.build_versioned_tag_key(
            mood_term, framework_version=framework_version, calib_method="none", calib_version=0,
        )
        tier: str | None = None
        if std_val >= _ACCEPTABLE:
            logger.debug(
                f"[aggregation] Regression no tier: {head_name} → {mood_term} (mean={mean_val:.3f}, std={std_val:.3f} - high variance)",
            )
        else:
            intensity = abs(mean_val - 0.5) * 2
            if std_val < _VERY_STABLE and intensity >= 0.8:
                tier = "high"
            elif std_val < _STABLE and intensity >= 0.6:
                tier = "medium"
            else:
                tier = "low"
            logger.debug(
                f"[aggregation] Regression mood: {head_name} → {mood_term} (mean={mean_val:.3f}, std={std_val:.3f}, intensity={intensity:.2f}, tier={tier})",
            )
        outputs.append(
            HeadOutput(
                head=head_info,
                model_key=model_key,
                label=mood_term,
                value=mean_val,
                tier=tier,
                calibration_id=calibration_id,
            ),
        )
    return outputs


LABEL_PAIRS = [
    ("happy", "sad", "peppy", "sombre"),
    ("aggressive", "relaxed", "aggressive", "relaxed"),
    ("electronic", "acoustic", "synth-like", "acoustic-like"),
    ("party", "not_party", "party-like", "not party-like"),
    ("danceable", "not_danceable", "easy to dance to", "hard to dance to"),
    ("bright", "dark", "bright timbre", "dark timbre"),
    ("male", "female", "low-pitch vocal", "high-pitch vocal"),
    ("tonal", "atonal", "tonal", "atonal"),
    ("instrumental", "voice", "instrumental only", "has vocals"),
]
_STRONG_THRESHOLD = 0.7
_WEAK_THRESHOLD = 0.3
_VERY_STABLE = 0.08
_STABLE = 0.15
_ACCEPTABLE = 0.25
_MOOD_MAPPING = {
    "approachability_regression": ("mainstream", "fringe"),
    "engagement_regression": ("engaging", "mellow"),
}


def _build_tier_map(
    head_outputs: list[Any], calibrations: dict[str, dict[str, Any]] | None,
) -> dict[str, tuple[str, float, str]]:
    """Build tier map from HeadOutput objects, applying calibration when available.

    Args:
        head_outputs: List of HeadOutput objects
        calibrations: Optional calibration data (tag_key -> {p5, p95, method})

    Returns:
        Dictionary mapping model_key -> (tier, value, label)

    """
    mood_outputs = [ho for ho in head_outputs if ho.head.is_mood_source and ho.tier is not None]
    logger.debug(f"[aggregation] {len(mood_outputs)} mood outputs with tiers")
    if not mood_outputs:
        logger.info("[aggregation] No mood outputs with tiers, returning empty mood tags")
        return {}
    tier_map: dict[str, tuple[str, float, str]] = {}
    for ho in mood_outputs:
        value = ho.value
        if calibrations and ho.model_key in calibrations:
            raw_value = value
            value = apply_minmax_calibration(value, calibrations[ho.model_key])
            logger.debug(f"[aggregation] Applied calibration to {ho.model_key}: {raw_value:.3f} → {value:.3f}")
        tier_map[ho.model_key] = (ho.tier, value, ho.label)
    logger.debug(f"[aggregation] Tier map has {len(tier_map)} entries")
    return tier_map


def _compute_suppressed_keys(
    tier_map: dict[str, tuple[str, float, str]], label_pairs: list[tuple[str, str, str, str]],
) -> set[str]:
    """Identify conflicting mood pairs and return keys to suppress.

    Args:
        tier_map: Dictionary mapping model_key -> (tier, value, label)
        label_pairs: List of opposing mood pairs

    Returns:
        Set of model keys to suppress due to conflicts

    """
    suppressed_keys: set[str] = set()
    for pos_pat, neg_pat, _pos_label, _neg_label in label_pairs:
        pos_keys = [
            k
            for k in tier_map
            if pos_pat in k.lower() and f"non_{pos_pat}" not in k.lower() and (f"not_{pos_pat}" not in k.lower())
        ]
        neg_keys = [
            k
            for k in tier_map
            if neg_pat in k.lower() and f"non_{neg_pat}" not in k.lower() and (f"not_{neg_pat}" not in k.lower())
        ]
        logger.debug(
            f"[aggregation] Checking pair ({pos_pat}, {neg_pat}): found pos={len(pos_keys)} neg={len(neg_keys)}",
        )
        if not pos_keys or not neg_keys:
            continue

        def get_best(keys):
            tier_order = {"high": 3, "strict": 3, "medium": 2, "norm": 2, "normal": 2, "low": 1}
            best = None
            best_score: float = 0
            for tag_key in keys:
                tier, prob, _label = tier_map[tag_key]
                score = tier_order.get(tier, 0) * 100 + prob
                if score > best_score:
                    best = tag_key
                    best_score = score
            return best

        pos_key = get_best(pos_keys)
        neg_key = get_best(neg_keys)
        if pos_key and neg_key:
            pos_tier, _, _ = tier_map[pos_key]
            neg_tier, _, _ = tier_map[neg_key]
            suppressed_keys.add(pos_key)
            suppressed_keys.add(neg_key)
            logger.info(f"[aggregation] Suppressing conflicting pair: {pos_key} ({pos_tier}) vs {neg_key} ({neg_tier})")
    return suppressed_keys


def _build_label_map(
    tier_map: dict[str, tuple[str, float, str]], label_pairs: list[tuple[str, str, str, str]],
) -> dict[str, str]:
    """Build label map for improved human-readable mood terms.

    Args:
        tier_map: Dictionary mapping model_key -> (tier, value, label)
        label_pairs: List of opposing mood pairs with improved labels

    Returns:
        Dictionary mapping simplified keys to human-readable labels

    """
    label_map = {}
    for pos_pat, neg_pat, pos_label, neg_label in label_pairs:
        for _tier, _value, label in tier_map.values():
            simplified = simplify_label(label)
            if simplified == pos_pat:
                label_map[simplified] = pos_label
            if simplified == f"not {pos_pat}":
                label_map[simplified] = f"not {pos_label}"
            if simplified == neg_pat:
                label_map[simplified] = neg_label
            if simplified == f"not {neg_pat}":
                label_map[simplified] = f"not {neg_label}"
    return label_map


def _build_tier_term_sets(
    tier_map: dict[str, tuple[str, float, str]], suppressed_keys: set[str], label_map: dict[str, str],
) -> BuildTierTermSetsResult:
    """Build strict, regular, and loose term sets from tier map.

    Args:
        tier_map: Dictionary mapping model_key -> (tier, value, label)
        suppressed_keys: Set of keys to skip due to conflicts
        label_map: Dictionary mapping simplified keys to human-readable labels

    Returns:
        BuildTierTermSetsResult with strict_terms, regular_terms, loose_terms

    """
    strict_terms: set[str] = set()
    regular_terms: set[str] = set()
    loose_terms: set[str] = set()
    for model_key, (tier, value, label) in tier_map.items():
        if model_key in suppressed_keys:
            continue
        simplified = simplify_label(label)
        term = label_map.get(simplified, simplified)
        logger.debug(f"[aggregation] Adding {model_key}={value:.3f} ({term}) to tier '{tier}'")
        if tier in ("high", "strict"):
            strict_terms.add(term)
        elif tier in ("medium", "norm", "normal"):
            regular_terms.add(term)
        else:
            loose_terms.add(term)
    logger.debug(
        f"[aggregation] Mood aggregation: strict={len(strict_terms)}, regular={len(regular_terms)}, loose={len(loose_terms)}",
    )
    return BuildTierTermSetsResult(strict_terms=strict_terms, regular_terms=regular_terms, loose_terms=loose_terms)


def _make_inclusive_mood_tags(strict_terms: set[str], regular_terms: set[str], loose_terms: set[str]) -> dict[str, Any]:
    """Build final mood tag dictionary with inclusive tier expansion.

    Implements: strict ⊂ regular ⊂ loose

    Args:
        strict_terms: Set of strict tier terms
        regular_terms: Set of regular tier terms
        loose_terms: Set of loose tier terms

    Returns:
        Dictionary containing mood-strict, mood-regular, mood-loose tags

    """
    if strict_terms:
        regular_terms |= strict_terms
        loose_terms |= strict_terms
    if regular_terms:
        loose_terms |= regular_terms
    result: dict[str, Any] = {}
    if strict_terms:
        result["mood-strict"] = sorted(strict_terms)
    if regular_terms:
        result["mood-regular"] = sorted(regular_terms)
    if loose_terms:
        result["mood-loose"] = sorted(loose_terms)
    return result


def aggregate_mood_tiers(
    head_outputs: list[Any], calibrations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate HeadOutput objects into mood-strict, mood-regular, mood-loose collections.

    Uses HeadOutput.tier to determine confidence level instead of parsing *_tier tags.

    Optionally applies calibration to raw scores before tier assignment. If calibrations
    are provided, raw scores are normalized using min-max scaling to make different models
    comparable. If no calibration exists for a tag, the raw score is used unchanged.

    Applies pair conflict suppression: if both sides of a pair (e.g., happy/sad,
    aggressive/relaxed) have tiers, neither is emitted to avoid contradictory tags.

    Also applies label improvements for better human readability.

    Args:
        head_outputs: List of HeadOutput objects with tier information
        calibrations: Optional calibration data (tag_key -> {p5, p95, method})

    Returns:
        Dictionary containing mood-strict, mood-regular, mood-loose tags

    """
    logger.debug(
        f"[aggregation] aggregate_mood_tiers called with {len(head_outputs)} HeadOutput objects, calibrations={calibrations is not None}",
    )
    tier_map = _build_tier_map(head_outputs, calibrations)
    if not tier_map:
        return {}
    suppressed_keys = _compute_suppressed_keys(tier_map, LABEL_PAIRS)
    label_map = _build_label_map(tier_map, LABEL_PAIRS)
    tier_sets = _build_tier_term_sets(tier_map, suppressed_keys, label_map)
    return _make_inclusive_mood_tags(tier_sets.strict_terms, tier_sets.regular_terms, tier_sets.loose_terms)
