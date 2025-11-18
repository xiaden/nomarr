# nomarr.ml.inference

API reference for `nomarr.ml.inference`.

---

## Functions

### compute_embeddings_for_backbone(backbone: 'str', emb_graph: 'str', target_sr: 'int', segment_s: 'float', hop_s: 'float', path: 'str', min_duration_s: 'int', allow_short: 'bool') -> 'tuple[np.ndarray, float]'

Compute embeddings for an audio file using a specific backbone.

### make_head_only_predictor_batched(head_info: 'HeadInfo', embeddings_2d: 'np.ndarray', batch_size: 'int' = 11) -> 'Callable[[], np.ndarray]'

Create a batched predictor that processes segments in fixed-size batches.

### make_predictor_uncached(head_info: 'HeadInfo') -> 'Callable[[np.ndarray, int], np.ndarray]'

Build full two-stage predictor (waveform -> embedding -> head predictions).

---

## Constants

### HAVE_TF

```python
HAVE_TF = True
```

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
