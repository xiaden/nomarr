# Tag Gating Algorithms

## 1. Classification Head: `_determine_tier()` (ml_heads_comp.py)

Three numeric gates must **ALL** pass to assign a tier. Lower gates are inclusive — a score that meets "high" also meets "medium" and "low":

| Gate | high | medium | low |
| ------ | ------ | -------- | ----- |
| `prob >=` (raw activation) | 0.80 | 0.75 | 0.60 |
| `ratio >=` (prob / counter_confidence) | 1.20 | 1.10 | 1.02 |
| `gap >=` (prob − counter_confidence) | 0.15 | 0.08 | 0.03 |

Pre-checks (applied before tier evaluation):

- `prob >= min_conf (0.15)` — floor filter, rejects noise
- `prob >= per-label threshold` (defaults to cascade.low = 0.60)

### Counter-confidence (`_find_counter_confidence`)

Determines what "prob" is competing against:

1. Explicit negation label (`non_*` or `not_*`) probability
2. If binary head (2 labels): the other label's probability
3. Fallback: `max(all_other_probs)`

**Ratio and gap gates guard against high-probability-but-close decisions** — a label at 0.80 with a counter at 0.79 fails both ratio (1.01 < 1.02) and gap (0.01 < 0.03) even at the low tier.

### Cascade dataclass (ml_head_dto.py)

```python
@dataclass
class Cascade:
    low: float = 0.60
    medium: float = 0.75
    high: float = 0.80
    low_ratio: float = 1.02
    medium_ratio: float = 1.10
    high_ratio: float = 1.20
    low_gap: float = 0.03
    medium_gap: float = 0.08
    high_gap: float = 0.15
    min_conf: float = 0.15
```

Thresholds are per-`HeadSpec` — not stored in DB, not currently user-configurable.

---

## 2. Stability Gating (Segment Variance Cap)

Applied after the numeric gates. Caps the maximum achievable tier based on cross-segment variance (`std` of activation scores across audio patches):

| std condition | Maximum tier |
| --------------- | -------------- |
| `std >= 0.25` | No tier (label suppressed entirely) |
| `std >= 0.15` | Cap at "low" |
| `std >= 0.08` | Cap at "medium" |
| `std < 0.08` | Full range (high / medium / low) |

**Rationale:** High cross-segment variance means the model is uncertain about different parts of the audio — a "high" tier label is not credible if it's only high for 20% of segments.

---

## 3. Regression Head: `assign_regression_outputs()` (tagging_aggregation_comp.py)

Regression heads output a single float per label in [0, 1]:

```
mean >= 0.70  →  high-intensity label
mean <= 0.30  →  low-intensity label
0.30 < mean < 0.70  →  neutral: BOTH labels emitted, tier=None

Tier for decisive case (abs(mean - 0.5) * 2 = intensity):
  std < 0.08  AND intensity >= 0.80  →  tier="high"
  std < 0.15  AND intensity >= 0.60  →  tier="medium"
  std < 0.25  (otherwise)            →  tier="low"
  std >= 0.25                        →  no tier
```

Regression mood label mappings live in `mood_labels_comp.py` `MOOD_MAPPING` — currently covers only `approachability_regression` and `engagement_regression`. Classification-based mood uses `KNOWN_MODELS` labels directly (different code path).

---

## 4. Opponent Suppression (tagging_aggregation_comp.py)

`OPPONENT_MAP` (from `ml_known_models_comp.py`) maps every label to the set of labels that are semantically opposed (co-defined within the same model stem).

**Two suppression passes in `_compute_suppressed_keys()`:**

### Intra-head suppression

Within a single head instance, if multiple tiered outputs exist, keep the one with the highest `(tier_rank, value)`. Suppress the rest.

Tier rank: `high/strict = 3 > medium/norm/normal = 2 > low = 1`

### Cross-head suppression

If two tiered outputs from *different* heads have labels that are opponents per `OPPONENT_MAP`, **suppress BOTH**. Contradictory cross-head signals cancel rather than one winning.

Example: `"Relaxed"` from `mood_relaxed` and `"Aggressive"` from `mood_aggressive` are opponents — if both are tiered, both are dropped.

### Mood tier sets (inclusive)

After suppression, surviving tiered outputs form inclusive sets:

- `nom:mood-strict` ← tier="high" only
- `nom:mood-regular` ← tier="high" ∪ tier="medium"
- `nom:mood-loose` ← tier="high" ∪ tier="medium" ∪ tier="low"

---

## 5. Calibration and Mood File-Write Gate

### Segment stats storage

Per inference run, `upsert_segment_stats_batch()` stores per-label `{mean, std, min, max}` across all audio patches in `segment_scores_stats`. This allows mood tiers to be **re-derived** from stored stats without re-running ML (calibration).

### CalibrationState fields

`{head_name, label, p5, p95, histogram, n, underflow_count, overflow_count}`

### Mood file-write gate (`write_file_tags_wf.py` `_filter_tags_for_mode`)

`nom:mood-*` tags are **stripped from the file-writeback payload** when `has_calibration=False`, regardless of `target_mode`. This is silent — no user-visible signal.

---

## 6. Known Gaps and Gotchas

1. **Hardcoded thresholds**: `Cascade` defaults are not per-model configurable. Changing thresholds requires a code change + redeploy.

2. **Silent mood write suppression**: `has_calibration=False` silently withholds mood tags from audio files in all modes. No UI signal.

3. **`tag_model_output` edge-resolution brittleness**: `resolve_tag_ids()` uses `(tag_name, score)` as lookup key where `score = ho.value` (probability). If the float doesn't match a stored tag value precisely, provenance edges silently fail to link.

4. **`MOOD_MAPPING` only covers two regression heads** (`approachability_regression`, `engagement_regression`). Classification-based mood heads use `KNOWN_MODELS` labels directly via a separate code path — the two registries are not unified.

5. **Ghost tag vertices after curation**: Orphan cleanup excludes tags that have `tag_model_output` provenance edges even if they have no `song_has_tags` links — these accumulate after curation operations that don't clean up provenance edges.

6. **`nom:mood-*` stored as JSON-encoded lists**: The `tags` collection schema declares `value` as `str`, but mood values are JSON-encoded lists. Reconstruction is handled by `tag_parsing_comp.py` but this is undocumented at the schema level.

7. **No end-to-end integration test** for the full ML score → DB tag write path.

---

## 7. Statistical / Algorithmic Alternatives Worth Knowing

These are not currently implemented but are directly relevant to improving the gating and scoring system.

### Calibration

**Platt scaling** — fit a sigmoid `P(y=1|f) = 1 / (1 + exp(A*f + B))` to the raw ONNX logits on a holdout set. Converts raw scores to proper probabilities. Better for well-behaved sigmoid-shaped distributions.

**Isotonic regression** — non-parametric monotone calibration. Better when the score-to-probability relationship is non-linear or skewed.

**Temperature scaling** — single parameter `T` applied to logits before softmax: `P_i = softmax(z_i / T)`. Simplest calibration; preserves relative ordering.

**Expected Calibration Error (ECE)** — measures bin-averaged gap between mean confidence and accuracy. Use to assess whether the current thresholds are well-calibrated before changing them.

### Score Aggregation (Pooling)

Current: **trimmed mean** (10% trim) across audio patches.

Alternatives:

- **Median pooling** — more robust to outlier patches, zero implementation cost
- **Percentile pooling** — e.g. p75/p90 emphasizes confident patches (useful for rare-event tags)
- **Attention-weighted pooling** — learn per-patch weights from a small trainable layer; requires fine-tuning
- **Coefficient of variation** (`cv = std / mean`) as a normalized stability signal instead of raw `std`; avoids the variance-cap thresholds being scale-sensitive

### Threshold Optimization

**Youden's J statistic** (`sensitivity + specificity − 1`): finds the threshold on an ROC curve that maximizes both recall and specificity simultaneously. Requires a labeled validation set.

**Precision-recall curve + target F1**: useful when false positives are more costly than false negatives (aggressive tagging vs. conservative).

**Cross-validation grid search** over `(prob, ratio, gap)` thresholds against a labeled reference set.

### Opponent Suppression

Current: cross-head opponents **both** suppressed (conservative).

Alternatives:

- **Keep higher-confidence winner** — suppress only the lower-tier label, not both
- **Confidence-weighted voting** — weight by `prob * tier_rank`; only suppress if winner confidence > loser confidence by a margin
- **Soft suppression** — demote the weaker to a lower tier instead of dropping it entirely

### Variance / Stability

Current: discrete `std` bucket caps.

Alternatives:

- **Bootstrap confidence interval**: resample segment scores to get a CI on the pooled mean; gate on CI width rather than raw std
- **Coefficient of variation** (`std / mean`): normalized uncertainty; avoids the issue where high-activation labels are penalized more for the same absolute std
- **Bayesian posterior** over label probability given segment scores (e.g. Beta-Binomial); provides credible intervals directly
