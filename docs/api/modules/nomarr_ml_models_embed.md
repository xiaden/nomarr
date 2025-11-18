# nomarr.ml.models.embed

API reference for `nomarr.ml.models.embed`.

---

## Classes

### Segments

Holds segmented waveform and boundaries in seconds (start, end).

**Methods:**

- `__init__(self, waves: 'list[np.ndarray]', bounds: 'list[tuple[float, float]]', sr: 'int') -> None`

---

## Functions

### analyze_with_segments(path: 'str', *, target_sr: 'int', segment_s: 'float', hop_s: 'float', min_duration_s: 'int', allow_short: 'bool', predict_fn: 'Callable[[np.ndarray, int], np.ndarray]', pool: 'str' = 'trimmed_mean', trim_perc: 'float' = 0.1) -> 'tuple[np.ndarray, Segments, float]'

Full flow for a single backbone/head:

### pool_scores(S: 'np.ndarray', mode: 'str' = 'mean', *, trim_perc: 'float' = 0.1, nan_policy: 'str' = 'omit') -> 'np.ndarray'

Pool segment-level scores into a single vector.

### score_segments(segments: 'Segments', predict_fn: 'Callable[[np.ndarray, int], np.ndarray]') -> 'np.ndarray'

Apply predict_fn to each segment waveform.

### segment_waveform(y: 'np.ndarray', sr: 'int', segment_s: 'float' = 10.0, hop_s: 'float' = 5.0, pad_final: 'bool' = False) -> 'Segments'

Slice a mono waveform into overlapping fixed-length segments.

---
