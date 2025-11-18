# nomarr.tagging.aggregation

API reference for `nomarr.tagging.aggregation`.

---

## Functions

### add_regression_mood_tiers(regression_heads: 'list[tuple[Any, list[float]]]', framework_version: 'str') -> 'list[Any]'

Convert regression head predictions (approachability, engagement) into HeadOutput objects.

### aggregate_mood_tiers(head_outputs: 'list[Any]', calibrations: 'dict[str, dict[str, Any]] | None' = None) -> 'dict[str, Any]'

Aggregate HeadOutput objects into mood-strict, mood-regular, mood-loose collections.

### get_prefix(backbone: 'str') -> 'str'

Get tag prefix based on backbone folder name.

### load_calibrations(models_dir: 'str', calibrate_heads: 'bool' = False) -> 'dict[str, dict[str, Any]]'

Load all calibration sidecars from models directory.

### normalize_tag_label(label: 'str') -> 'str'

Normalize model label for tag key consistency.

### simplify_label(base_key: 'str') -> 'str'

Map model-prefixed labels to human terms: 'yamnet_non_happy' -> 'not happy', 'effnet_bright' -> 'bright'.

---

## Constants

### LABEL_PAIRS

```python
LABEL_PAIRS = [('happy', 'sad', 'peppy', 'sombre'), ('aggressive', 'relaxed', 'aggressive', 'relaxed'), ('electron
```

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
