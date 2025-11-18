# nomarr.ml.models.heads

API reference for `nomarr.ml.models.heads`.

---

## Classes

### Cascade

Tier thresholds from the original training calibration.

**Methods:**

- `__init__(self, high: 'float' = 0.8, medium: 'float' = 0.75, low: 'float' = 0.6, ratio_high: 'float' = 1.2, ratio_medium: 'float' = 1.1, ratio_low: 'float' = 1.02, gap_high: 'float' = 0.15, gap_medium: 'float' = 0.08, gap_low: 'float' = 0.03) -> None`

### HeadDecision

A lightweight container for the decision of a single head.

**Methods:**

- `__init__(self, head: 'HeadSpec', details: 'dict[str, Any]', all_probs: 'dict[str, float] | None' = None)`
- `as_tags(self, prefix: 'str' = '', key_builder: 'Callable[[str], str] | None' = None) -> 'dict[str, Any]'`
- `to_head_outputs(self, head_info: 'Any', framework_version: 'str', prefix: 'str' = '', key_builder: 'Callable[[str], str] | None' = None) -> 'list[Any]'`

### HeadSpec

HeadSpec(name: 'str', kind: 'str', labels: 'list[str]' = <factory>, cascade: 'Cascade' = <factory>, label_thresholds: 'dict[str, float]' = <factory>, min_conf: 'float' = 0.15, max_classes: 'int' = 5, top_ratio: 'float' = 0.5, prob_input: 'bool' = True)

**Methods:**

- `__init__(self, name: 'str', kind: 'str', labels: 'list[str]' = <factory>, cascade: 'Cascade' = <factory>, label_thresholds: 'dict[str, float]' = <factory>, min_conf: 'float' = 0.15, max_classes: 'int' = 5, top_ratio: 'float' = 0.5, prob_input: 'bool' = True) -> None`

---

## Functions

### decide_multiclass_adaptive(scores: 'np.ndarray', spec: 'HeadSpec') -> 'dict[str, Any]'

Multiclass adaptive top-K:

### decide_multilabel(scores: 'np.ndarray', spec: 'HeadSpec') -> 'dict[str, Any]'

Multilabel: select all labels with score >= (per-label threshold or cascade.low).

### decide_regression(values: 'np.ndarray', labels: 'list[str]') -> 'dict[str, float]'

Return raw float outputs keyed by label; preserves full precision.

### head_is_multiclass(spec: 'HeadSpec') -> 'bool'

TODO: describe head_is_multiclass

### head_is_multilabel(spec: 'HeadSpec') -> 'bool'

TODO: describe head_is_multilabel

### head_is_regression(spec: 'HeadSpec') -> 'bool'

TODO: describe head_is_regression

### run_head_decision(sc: 'Sidecar', scores: 'np.ndarray', *, prefix: 'str' = '', emit_all_scores: 'bool' = True) -> 'HeadDecision'

Turn the raw output vector for a head into a HeadDecision.

---
