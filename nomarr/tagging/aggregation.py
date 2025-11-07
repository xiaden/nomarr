"""
Tag aggregation logic - mood tiers, label simplification, and conflict resolution.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np


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


def simplify_label(base_key: str) -> str:
    """Map model-prefixed labels to human terms: 'yamnet_non_happy' -> 'not happy', 'effnet_bright' -> 'bright'."""
    s = base_key.lower()
    # strip known model prefixes
    for pref in ("yamnet_", "vggish_", "effnet_", "musicnn_"):
        if s.startswith(pref):
            s = s[len(pref) :]
            break
    if s.startswith("non_"):
        core = s[4:]
        return f"not {core.replace('_', ' ')}"
    if s.startswith("not_"):
        core = s[4:]
        return f"not {core.replace('_', ' ')}"
    return s.replace("_", " ")


def add_regression_mood_tiers(tags: dict[str, Any], predictions: dict[str, list[float]]) -> None:
    """
    Convert regression head predictions (approachability, engagement) into mood tier tags.

    Regression heads output INTENSITY values (0-1), not probabilities:
    - High values (>0.7) indicate STRONG presence of the attribute
    - Low values (<0.3) indicate STRONG presence of the opposite attribute
    - Middle values (0.3-0.7) are neutral/ambiguous

    Only emit tags when variance is LOW (model is confident/consistent):
    - High variance indicates the model is flip-flopping → unreliable, skip
    - Low variance indicates stable measurement → trustworthy, use it

    Tier assignment combines both intensity AND stability:
    - "high" tier: Extreme values (very strong) with very low variance
    - "medium" tier: Strong values with low variance
    - "low" tier: Moderate values with acceptable variance
    - No tag: High variance (unreliable) or neutral values (0.3-0.7)

    Modifies tags dict in-place by adding synthetic <prefix>_<term> and <prefix>_<term>_tier tags.
    """
    if not predictions:
        return

    # Intensity thresholds (mean value indicates strength, not probability)
    STRONG_THRESHOLD = 0.7  # Strongly mainstream/engaging
    WEAK_THRESHOLD = 0.3  # Strongly fringe/mellow
    # Values between 0.3-0.7 are neutral → don't emit

    # Variance thresholds (std deviation indicates measurement reliability)
    VERY_STABLE = 0.08  # Extremely consistent → high tier if value is extreme
    STABLE = 0.15  # Consistent → medium tier if value is strong
    ACCEPTABLE = 0.25  # Moderately consistent → low tier if value qualifies
    # std >= 0.25 → too inconsistent, don't trust the measurement

    # Map head names to mood terms (positive/negative pairs)
    mood_mapping = {
        "approachability_regression": ("mainstream", "fringe"),  # high/low
        "engagement_regression": ("engaging", "mellow"),  # high/low
    }

    for head_name, segment_values in predictions.items():
        if not segment_values or head_name not in mood_mapping:
            continue

        # Compute statistics across all segments
        arr = np.array(segment_values)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        # Skip if variance too high (model is flip-flopping, unreliable)
        if std_val >= ACCEPTABLE:
            logging.info(
                f"[aggregation] Skipping {head_name}: high variance (std={std_val:.3f}) indicates unreliable measurement"
            )
            continue

        # Skip if value is neutral (neither strongly high nor strongly low)
        if WEAK_THRESHOLD < mean_val < STRONG_THRESHOLD:
            logging.debug(f"[aggregation] Skipping {head_name}: neutral value (mean={mean_val:.3f}) in ambiguous range")
            continue

        # Determine which term to emit based on intensity
        high_term, low_term = mood_mapping[head_name]
        is_high = mean_val >= STRONG_THRESHOLD
        mood_term = high_term if is_high else low_term

        # Determine tier based on BOTH variance (stability) AND intensity (extremeness)
        # More extreme values + lower variance → higher tier (more confident)
        intensity = abs(mean_val - 0.5) * 2  # Normalize distance from neutral (0-1 scale)

        if std_val < VERY_STABLE and intensity >= 0.8:
            # Very stable AND very extreme → strict tier
            tier = "high"
        elif std_val < STABLE and intensity >= 0.6:
            # Stable AND strong → regular tier
            tier = "medium"
        else:
            # Acceptable variance OR moderate intensity → loose tier
            tier = "low"

        # Add synthetic tags that mimic natural head outputs
        # Use "effnet_" prefix since these are effnet regression heads
        tag_base = f"effnet_{mood_term}"
        tags[tag_base] = mean_val  # Raw intensity value
        tags[f"{tag_base}_tier"] = tier  # Tier for aggregation

        logging.info(
            f"[aggregation] Regression mood: {head_name} → {mood_term} "
            f"(mean={mean_val:.3f}, std={std_val:.3f}, intensity={intensity:.2f}, tier={tier})"
        )


def aggregate_mood_tiers(tags: dict[str, Any], mood_terms: set[str] | None = None) -> None:
    """
    Aggregate mood-tier tags into mood-strict, mood-regular, mood-loose collections.

    Applies pair conflict suppression: if both sides of a pair (e.g., happy/sad,
    aggressive/relaxed) have the same tier, neither is emitted to avoid contradictory tags.

    Also applies label improvements for better human readability.

    Modifies tags dict in-place.
    """
    logging.debug(f"[aggregation] aggregate_mood_tiers called with mood_terms={mood_terms}")

    # Collect all tier tags with their probabilities
    tier_map: dict[str, tuple[str, float]] = {}  # base_key -> (tier, prob)

    for k, v in list(tags.items()):
        if not isinstance(k, str) or not k.endswith("_tier"):
            continue

        base_key = k[: -len("_tier")]
        tier = str(v).lower()

        # Select only mood-related keys if mood_terms provided; else require 'mood' substring
        if mood_terms is not None:
            base_l = base_key.lower()
            if not any(term in base_l for term in mood_terms):
                logging.debug(f"[aggregation] Skipping non-mood tier tag: {k} (base={base_key})")
                continue
        else:
            if "mood" not in base_key.lower():
                continue

        p_val = tags.get(base_key)
        try:
            p = float(p_val) if p_val is not None else None
        except Exception:
            p = None

        if p is None:
            logging.warning(f"[aggregation] No probability value found for {base_key} (tier tag {k})")
            continue

        tier_map[base_key] = (tier, p)

    logging.info(f"[aggregation] Tier map has {len(tier_map)} entries: {list(tier_map.keys())}")

    # Define opposing pairs with improved labels
    # Format: (pos_key_pattern, neg_key_pattern, pos_label, neg_label)
    # NOTE: These patterns match ONLY the positive/unnegated forms to detect cross-model conflicts
    # e.g., "happy" matches mood_happy but NOT non_happy (which supports sad, not conflicts with it)
    label_pairs = [
        ("happy", "sad", "peppy", "sombre"),
        ("aggressive", "relaxed", "aggressive", "relaxed"),
        ("electronic", "acoustic", "electronic production", "acoustic production"),
        ("party", "not_party", "bass-forward", "bass-light"),
        ("danceable", "not_danceable", "easy to dance to", "hard to dance to"),
        ("bright", "dark", "majorish", "minorish"),
        ("male", "female", "male vocal lead", "female vocal lead"),
        ("tonal", "atonal", "tonal", "atonal"),
        ("instrumental", "voice", "instrumental heavy", "vocal heavy"),
    ]

    # Track which keys to suppress due to conflicts
    suppressed_keys: set[str] = set()

    # Check each pair for conflicts
    for pos_pat, neg_pat, _pos_label, _neg_label in label_pairs:
        # Find matching keys (handle prefixes like yamnet_, effnet_, etc.)
        # Exclude negated versions: "happy" should NOT match "non_happy" or "not_happy"
        pos_keys = [
            k
            for k in tier_map
            if pos_pat in k.lower() and f"non_{pos_pat}" not in k.lower() and f"not_{pos_pat}" not in k.lower()
        ]
        neg_keys = [
            k
            for k in tier_map
            if neg_pat in k.lower() and f"non_{neg_pat}" not in k.lower() and f"not_{neg_pat}" not in k.lower()
        ]

        logging.info(
            f"[aggregation] Checking pair ({pos_pat}, {neg_pat}): found pos={len(pos_keys)} neg={len(neg_keys)}"
        )

        if not pos_keys or not neg_keys:
            continue

        # Take the strongest evidence for each side (highest tier, then highest prob)
        def get_best(keys):
            tier_order = {"high": 3, "strict": 3, "medium": 2, "norm": 2, "normal": 2, "low": 1}
            best = None
            best_score = 0
            for k in keys:
                tier, prob = tier_map[k]
                score = tier_order.get(tier, 0) * 100 + prob
                if score > best_score:
                    best = k
                    best_score = score
            return best

        pos_key = get_best(pos_keys)
        neg_key = get_best(neg_keys)

        if pos_key and neg_key:
            pos_tier, _ = tier_map[pos_key]
            neg_tier, _ = tier_map[neg_key]

            # Suppress both if EITHER side has ANY tier (conflict between models)
            # This catches models that disagree and avoids writing contradictory tags
            suppressed_keys.add(pos_key)
            suppressed_keys.add(neg_key)
            logging.info(
                f"[aggregation] Suppressing conflicting pair: {pos_key} ({pos_tier}) vs {neg_key} ({neg_tier})"
            )

    # Build tier sets with improved labels, excluding suppressed keys
    strict_terms: set[str] = set()
    regular_terms: set[str] = set()
    loose_terms: set[str] = set()

    # Build label_map using simplified keys for both positive and negated forms
    label_map = {}
    for pos_pat, neg_pat, pos_label, neg_label in label_pairs:
        for k in tier_map:
            simplified = simplify_label(k)
            # Map positive forms
            if simplified == pos_pat:
                label_map[simplified] = pos_label
            # Map negated forms ("not happy" etc.)
            if simplified == f"not {pos_pat}":
                label_map[simplified] = f"not {pos_label}"
            # Also allow mapping for negative patterns
            if simplified == neg_pat:
                label_map[simplified] = neg_label
            if simplified == f"not {neg_pat}":
                label_map[simplified] = f"not {neg_label}"

    for base_key, (tier, prob) in tier_map.items():
        if base_key in suppressed_keys:
            continue

        simplified = simplify_label(base_key)
        # Use improved label if available, otherwise simplified
        term = label_map.get(simplified, simplified)

        logging.debug(f"[aggregation] Adding {base_key}={prob} ({term}) to tier '{tier}'")
        if tier in ("high", "strict"):
            strict_terms.add(term)
        elif tier in ("medium", "norm", "normal"):
            regular_terms.add(term)
        else:
            loose_terms.add(term)

    logging.info(
        f"[aggregation] Mood aggregation: strict={len(strict_terms)}, regular={len(regular_terms)}, loose={len(loose_terms)}"
    )

    # Inclusive mood sets: strict ⊂ regular ⊂ loose
    if strict_terms:
        regular_terms |= strict_terms
        loose_terms |= strict_terms
    if regular_terms:
        loose_terms |= regular_terms

    # Write human-friendly multi-value tags for playlisting
    if strict_terms:
        tags["mood-strict"] = sorted(strict_terms)
    if regular_terms:
        tags["mood-regular"] = sorted(regular_terms)
    if loose_terms:
        tags["mood-loose"] = sorted(loose_terms)
