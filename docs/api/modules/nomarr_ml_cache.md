# nomarr.ml.cache

API reference for `nomarr.ml.cache`.

---

## Functions

### cache_key(head_info: 'HeadInfo') -> 'str'

Unique cache key for a head across backbones/types.

### check_and_evict_idle_cache() -> 'bool'

Check if cache has been idle longer than timeout and evict if needed.

### clear_predictor_cache() -> 'int'

Clear the predictor cache and free GPU memory.

### get_cache_idle_time() -> 'float'

Get the number of seconds since last cache access.

### get_cache_size() -> 'int'

Return number of predictors in cache.

### is_initialized() -> 'bool'

Check if cache has been initialized.

### touch_cache() -> 'None'

Update the last access time for the cache.

### warmup_predictor_cache(models_dir: 'str', cache_idle_timeout: 'int' = 300) -> 'int'

Pre-load all model predictors into cache to avoid loading overhead during processing.

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
