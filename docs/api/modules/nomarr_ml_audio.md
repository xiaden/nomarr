# nomarr.ml.audio

API reference for `nomarr.ml.audio`.

---

## Functions

### load_audio_mono(path: 'str', target_sr: 'int' = 16000) -> 'tuple[np.ndarray, int, float]'

Load an audio file as mono float32 in [-1, 1] at target_sr.

### should_skip_short(duration_s: 'float', min_duration_s: 'int', allow_short: 'bool') -> 'bool'

Check if audio file should be skipped due to insufficient duration.

---

## Constants

### HAVE_ESSENTIA

```python
HAVE_ESSENTIA = False
```

---
