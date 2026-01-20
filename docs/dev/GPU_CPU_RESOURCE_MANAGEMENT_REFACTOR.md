# GPU/CPU Resource Management Refactor Plan

**Status**: PLANNING - Not Yet Implemented  
**Target**: Worker system and ML components  
**Goal**: Make workers dynamically fallback from GPU → CPU → graceful failure based on resource availability

---

## Executive Summary

Workers currently operate in all-or-nothing mode: either GPU is available or processing fails. This refactor adds **adaptive resource management** where workers monitor VRAM and RAM usage and gracefully degrade:

1. **VRAM > 80%** → Switch from GPU to CPU + RAM processing
2. **RAM > 80% (while on CPU)** → Log warning, mark job failed, exit worker
3. **Both resources healthy** → Use GPU (normal operation)

This prevents OOM crashes and allows workers to survive resource pressure spikes while providing clear failure signals when truly out of resources.

---

## Background

### Current State

**GPU Usage** (from codebase analysis):
- **Backbone embeddings** (EffNet, MusiCNN, YAMNet): Run on GPU via Essentia `TensorflowPredict*` classes - **MOST VRAM INTENSIVE** (~8-9GB per backbone predictor)
- **Head models**: Already forced to CPU via `tf.device("/CPU:0")` (line 312 of `ml_inference_comp.py`) - lightweight (~100MB per head)
- **Model cache**: Dual-cache system implemented but backbone cache not yet populated:
  - `_PREDICTOR_CACHE`: Full two-stage predictors (waveform → embedding → predictions) - used during cache warmup only
  - `_BACKBONE_CACHE`: Backbone embedding predictors (declared but not used) - **KEY MISSING PIECE**
  - Both caches share 300s idle eviction timeout
  - **Lazy warmup**: Worker waits for first file before loading models (avoids VRAM allocation until work arrives)

**Resource Monitoring**:
- ✅ **GPU availability**: `probe_gpu_availability()` checks nvidia-smi every 15s
- ✅ **GPU health tracking**: `GPUHealthMonitor` writes status to DB meta table
- ❌ **VRAM usage monitoring**: No current implementation
- ❌ **RAM usage monitoring**: No current implementation
- ❌ **Dynamic device selection**: Workers use GPU if available, no fallback logic
**Lazy cache warmup** (recently added): Worker waits for first file claim before loading models
- **Idle eviction** (recently added): Cache cleared after 300s of no work (frees VRAM)
- No runtime GPU health checks during job processing
- No adaptive behavior when resources become constrained

**Backbone Cache Architecture (Recently Added, Partially Implemented)**:
- **Purpose**: Separate cache for backbone embedding predictors to enable:
  1. One-time backbone computation per file (not per-head)
  2. Memory-efficient head inference (reuse embeddings across heads)
  3. Device-specific caching (GPU vs CPU backbone predictors)
- **Current Status**: Infrastructure exists (`_BACKBONE_CACHE` dict) but not yet populated
- **Missing Implementation**: Functions to cache/retrieve backbone predictors in workflows

### Problem Statement

**Without adaptive resource management**:
- Workers crash with `ResourceExhaustedError` when VRAM fills
- **Backbone models are the VRAM bottleneck**: EffNet = ~8GB, MusiCNN = ~4GB, YAMNet = ~2GB per predictor
- Multiple workers + large batch sizes = VRAM exhaustion (e.g., 2 workers × 8GB EffNet = 16GB minimum VRAM)
- **No device-aware backbone caching**: Current `compute_embeddings_for_backbone` rebuilds predictor every time (no caching implemented yet)

**Without adaptive resource management**:
- Workers crash with `ResourceExhaustedError` when VRAM fills
- Multiple workers + large batch sizes + EffNet embeddings = 9GB+ VRAM per worker
- No graceful degradation when resources spike (large files, calibration runs, etc.)
- Workers compete for VRAM without coordination

**User Impact**:
- "Out of Memory Errors" troubleshooting page (docs/user/getting_started.md:664) recommends manual config tweaks
- Users must preemptively reduce workers/batch size based on GPU memory
- Workers crash mid-job, leaving orphaned claims and inconsistent DB state

---

## Design Overview

### Resource Thresholds

```python
# Component: nomarr/components/platform/resource_monitor_comp.py (NEW)

VRAM_HIGH_THRESHOLD = 0.80  # 80% VRAM usage triggers CPU fallback
RAM_HIGH_THRESHOLD = 0.80   # 80% RAM usage triggers failure
RESOURCE_CHECK_INTERVAL_S = 5.0  # Check every 5 seconds
```

### Decision Tree

```
┌─────────────────────────────┐
│ Worker claims file          │
└─────────────┬───────────────┘
              │
              ▼
    ┌─────────────────────┐
    │ Check VRAM usage    │
    └─────────┬───────────┘
              │
         ╔════╩════╗
      < 80%     ≥ 80%
         ║          ║
         ▼          ▼
   ┌──────────┐  ┌──────────────────────┐
   │ Use GPU  │  │ Check RAM usage      │
   │ (normal) │  └──────────┬───────────┘
   └──────────┘             │
                       ╔════╩════╗
                    < 80%     ≥ 80%
                       ║          ║, **implement backbone caching**
- `ml_cache_comp.py`: **Populate `_BACKBONE_CACHE`**, t▼          ▼
              ┌────────────────┐  ┌─────────────────────┐
              │ Use CPU + RAM  │  │ Log warning         │
              │ (slow fallback)│  │ Mark job failed     │
              └────────────────┘  │ Exit worker         │
                                  └─────────────────────┘
```

### Architecture Changes

**New Components** (layer: `components/platform/`):
- `resource_monitor_comp.py`: Monitor VRAM/RAM usage via nvidia-smi + psutil

**Modified Components**:
- `discovery_worker.py`: Resource checks before processing, dynamic device selection
- `ml_inference_comp.py`: Accept device override parameter, TensorFlow device context management
- `ml_cache_comp.py`: Track cache VRAM usage, support device-specific caching

**Modified Workflows**:
- `process_file_wf.py`: Pass device selection to ML inference functions

---

## Detailed Implementation Plan

### Phase 1: Resource Monitoring Component (P0)

**Create** `nomarr/components/platform/resource_monitor_comp.py`

**API**:
```python
def get_vram_usage() -> dict[str, Any]:
    """
    Query current VRAM usage via nvidia-smi.
    
    Returns:
        Dict with:
            - total_mb: int - Total VRAM in MB
            - used_mb: int - Used VRAM in MB
            - free_mb: int - Free VRAM in MB
            - usage_percent: float - Usage percentage (0.0 - 1.0)
            - available: bool - GPU accessible
            - error: str | None - Error message if unavailable
    """

def get_ram_usage() -> dict[str, Any]:
    """
    Query current system RAM usage via psutil.
    
    Returns:
        Dict with:
            - total_mb: int - Total RAM in MB
            - used_mb: int - Used RAM in MB
            - free_mb: int - Free RAM in MB
            - usage_percent: float - Usage percentage (0.0 - 1.0)
            - error: str | None - Error message if unavailable
    """

def check_resource_headroom() -> dict[str, Any]:
    """
    Check if sufficient resources for GPU processing.
    
    Returns:
        Dict with:
            - can_use_gpu: bool - VRAM < 80% threshold
            - can_use_cpu: bool - RAM < 80% threshold
            - vram_usage_percent: float
            - ram_usage_percent: float
            - recommendation: str - "gpu", "cpu", or "exit"
    """
```

**Implementation Details**:
- **VRAM monitoring**: Use `nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits`
- **RAM monitoring**: Use `psutil.virtual_memory()` (add to requirements.txt)
- **Timeout handling**: 5s timeout for nvidia-smi like `gpu_probe_comp.py`
- **Error handling**: Return safe fallback values on error (assume resources available)
- **No caching**: Always query fresh values (resource state changes rapidly)

**Rationale**:
- Leaf component (no upward imports) for testability
- Pure query functions, no state mutation
- Compatible with multiprocessing (workers call from subprocess)

**Dependencies**:
- Add `psutil>=5.9.0` to `requirements.txt`, `pyproject.toml`, `dockerfile.base`

---

### Phase 0.5: Implement Backbone Caching (P0 - PREREQUISITE)

**CRITICAL**: This phase implements the missing backbone cache functionality that was declared but not yet used.

**Why this is P0**: Backbone models are the VRAM bottleneck (8GB for EffNet). Without caching, every `compute_embeddings_for_backbone` call rebuilds the predictor, wasting VRAM and time. The dual-cache infrastructure exists but is incomplete.

**Modify** `nomarr/components/ml/ml_cache_comp.py`

**Add backbone cache functions**:

```python
def get_backbone_predictor(backbone: str, emb_graph: str, emb_output: str) -> Any | None:
    """
    Get cached backbone embedding predictor.
    
    Args:
        backbone: Backbone name (effnet, musicnn, yamnet, vggish)
        emb_graph: Path to embedding graph file
        emb_output: Output node name for embeddings
    
    Returns:
        Cached Essentia predictor object or None if not cached
    """
    global _BACKBONE_CACHE
    cache_key = f"{backbone}::{emb_graph}::{emb_output}"
    
    with _CACHE_LOCK:
        return _BACKBONE_CACHE.get(cache_key)


def cache_backbone_predictor(
    backbone: str,
    emb_graph: str,
    emb_output: str,
    predictor: Any,
) -> None:
    """
    Cache a backbone embedding predictor.
    
    Args:
        backbone: Backbone name (effnet, musicnn, yamnet, vggish)
        emb_graph: Path to embedding graph file
        emb_output: Output node name for embeddings
        predictor: Essentia predictor object (TensorflowPredict*)
    """
    global _BACKBONE_CACHE, _CACHE_LAST_ACCESS
    cache_key = f"{backbone}::{emb_graph}::{emb_output}"
    
    with _CACHE_LOCK:
        _BACKBONE_CACHE[cache_key] = predictor
        _CACHE_LAST_ACCESS = time.time()
        logging.debug(f"[cache] Cached backbone predictor: {cache_key}")


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics including backbone/head breakdown."""
    return {
        "total_predictors": len(_PREDICTOR_CACHE),
        "backbone_predictors": len(_BACKBONE_CACHE),
        "cache_initialized": _CACHE_INITIALIZED,
        "idle_time_s": get_cache_idle_time(),
    }
```

**Modify** `nomarr/components/ml/ml_inference_comp.py`

**Update `compute_embeddings_for_backbone` to use cache**:

```python
def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
) -> tuple[np.ndarray, float, str]:
    """
    Compute embeddings for an audio file using a specific backbone.
    Uses cached backbone predictor if available.
    """
    backend_essentia.require()
    
    # ... existing audio loading and chromaprint computation ...
    
    # Build embedding predictor for this backbone
    emb_output = get_embedding_output_node(params.backbone)
    
    # TRY TO GET CACHED BACKBONE PREDICTOR FIRST
    from nomarr.components.ml.ml_cache_comp import cache_backbone_predictor, get_backbone_predictor
    
    emb_predictor = get_backbone_predictor(params.backbone, params.emb_graph, emb_output)
    
    if emb_predictor is None:
        # Cache miss - build new predictor
        logging.debug(f"[inference] Building new {params.backbone} predictor (cache miss)")
        
        if params.backbone == "yamnet":
            if TensorflowPredictVGGish is None:
                raise RuntimeError("TensorflowPredictVGGish not available")
            emb_predictor = TensorflowPredictVGGish(
                graphFilename=params.emb_graph, input="melspectrogram", output=emb_output
            )
        elif params.backbone == "vggish":
            if TensorflowPredictVGGish is None:
                raise RuntimeError("TensorflowPredictVGGish not available")
            emb_predictor = TensorflowPredictVGGish(graphFilename=params.emb_graph, output=emb_output)
        elif params.backbone == "effnet":
            if TensorflowPredictEffnetDiscogs is None:
                raise RuntimeError("TensorflowPredictEffnetDiscogs not available")
            emb_predictor = TensorflowPredictEffnetDiscogs(graphFilename=params.emb_graph, output=emb_output)
        elif params.backbone == "musicnn":
            if TensorflowPredictMusiCNN is None:
                raise RuntimeError("TensorflowPredictMusiCNN not available")
            emb_predictor = TensorflowPredictMusiCNN(graphFilename=params.emb_graph, output=emb_output)
        else:
            raise RuntimeError(f"Unsupported backbone {params.backbone}")
        
        # CACHE THE NEW PREDICTOR
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_output, emb_predictor)
        logging.debug(f"[inference] Cached new {params.backbone} predictor")
    else:
        logging.debug(f"[inference] Using cached {params.backbone} predictor")
    
    # Single-pass backbone processing: feed entire audio clip once
    wave_f32 = audio_result.waveform.astype(np.float32)
    emb = emb_predictor(wave_f32)
    emb = np.asarray(emb, dtype=np.float32)
    
    # ... existing normalization and return ...
```

**Rationale**:
- **Critical for VRAM efficiency**: Without backbone caching, every file processes with a fresh 8GB EffNet predictor
- **Performance**: Cache hit avoids ~2-5s predictor construction time
- **Foundation for device selection**: Phase 3 will add device parameter to this function
- **Completes dual-cache architecture**: `_BACKBONE_CACHE` was declared but unused

**Expected Impact**:
- **VRAM usage drops dramatically**: 2 workers processing EffNet files goes from 16GB (2×8GB) to 8GB (shared cache)
- **First file per backbone**: Still slow (builds predictor), subsequent files fast (cache hit)
- **Idle eviction**: After 300s idle, cache cleared (frees 8GB VRAM)

---

### Phase 2: Worker Resource Checks (P0)

**Modify** `nomarr/services/infrastructure/workers/discovery_worker.py`

**Changes**:

1. **Import resource monitor**:
```python
from nomarr.components.platform.resource_monitor_comp import check_resource_headroom
```

2. **Add preflight resource check before processing**:
```python
def run(self) -> None:
    # ... existing setup ...
    
    try:
        while not self._stop_event.is_set():
            # Discover and claim next file
            file_id = discover_and_claim_file(db, self.worker_id)
            
            if file_id is None:
                time.sleep(IDLE_SLEEP_S)
                continue
            
            # NEW: Check resource headroom before processing
            resources = check_resource_headroom()
            
            if resources["recommendation"] == "exit":
                # Both VRAM and RAM exhausted
                logger.error(
                    "[%s] Insufficient resources: VRAM %.1f%%, RAM %.1f%% - exiting",
                    self.worker_id,
                    resources["vram_usage_percent"] * 100,
                    resources["ram_usage_percent"] * 100,
                )
                self._current_status = "failed"
                release_claim(db, file_id)
                break  # Exit worker loop
            
            # Determine device for this job
            device = "gpu" if resources["can_use_gpu"] else "cpu"
            
            if device == "cpu":
                logger.warning(
                    "[%s] VRAM usage %.1f%% > 80%%, falling back to CPU processing",
                    self.worker_id,
                    resources["vram_usage_percent"] * 100,
                )
            
            # Get file path from database
            file_doc = db.library_files.get_file_by_id(file_id)
            # ... existing file_doc handling ...
            
            # Run the processing workflow WITH DEVICE SELECTION
            result = process_file_workflow(
                path=file_path,
                config=config,
                db=db,
                device=device,  # NEW: Pass device preference
            )
            
            # ... rest of existing processing logic ...
```

3. **Update health frames to include resource state** (optional telemetry):
```python
def _send_health_frame(self, status: str, device: str | None = None) -> None:
    """Send a health frame to the parent process via pipe."""
    if self._health_pipe is None:
        return
    
    frame_data = {
        "component_id": self.worker_id,
        "status": status,
    }
    
    if device:
        frame_data["device"] = device  # "gpu" or "cpu"
    
    frame = HEALTH_FRAME_PREFIX + json.dumps(frame_data)
    # ... existing send logic ...
```

**Rationale**:
- Check resources before each job (not just at startup)
- Fail fast if RAM exhausted (no point continuing)
- Log clear warnings when falling back to CPU
- Health frames remain simple (status + optional device telemetry)

---

### Phase 3: ML Inference Device Selection (P0)

**Modify** `nomarr/components/ml/ml_inference_comp.py`

**Changes**:

1. **Add device parameter to `compute_embeddings_for_backbone`**:

```python
def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
    device: str = "gpu",  # NEW: "gpu" or "cpu"
) -> tuple[np.ndarray, float, str]:
    """
    Compute embeddings for an audio file using a specific backbone.
    
    Args:
        params: Parameters including backbone, paths, sample rate, etc.
        device: Device for computation ("gpu" or "cpu", default: "gpu")
    
    Returns:
        Tuple of (embeddings, duration, chromaprint)
    """
    backend_essentia.require()
    
    # ... existing audio loading and chromaprint computation ...
    
    # Build embedding predictor with device context
    emb_output = get_embedding_output_node(params.backbone)
    
    # Try to get cached backbone predictor (device-specific key)
    from nomarr.components.ml.ml_cache_comp import cache_backbone_predictor, get_backbone_predictor
    
    # DEVICE-SPECIFIC CACHE KEY (changed from Phase 0.5)
    emb_predictor = get_backbone_predictor(params.backbone, params.emb_graph, emb_output, device=device)
    
    if emb_predictor is None:
        # Cache miss - build new predictor WITH DEVICE CONTEXT
        logging.debug(f"[inference] Building new {params.backbone} predictor on {device} (cache miss)")
        
        # NEW: Wrap predictor construction in device context
        if HAVE_TF and tf is not None:
            if device == "cpu":
                device_context = tf.device("/CPU:0")
                logging.info(f"[inference] Building {params.backbone} predictor on CPU (VRAM pressure)")
            else:
                device_context = contextlib.nullcontext()  # Use default (GPU)
        else:
            device_context = contextlib.nullcontext()
        
        with device_context:
            if params.backbone == "yamnet":
                if TensorflowPredictVGGish is None:
                    raise RuntimeError("TensorflowPredictVGGish not available")
                emb_predictor = TensorflowPredictVGGish(
                    graphFilename=params.emb_graph, input="melspectrogram", output=emb_output
                )
            elif params.backbone == "vggish":
                if TensorflowPredictVGGish is None:
                    raise RuntimeError("TensorflowPredictVGGish not available")
                emb_predictor = TensorflowPredictVGGish(graphFilename=params.emb_graph, output=emb_output)
            elif params.backbone == "effnet":
                if TensorflowPredictEffnetDiscogs is None:
                    raise RuntimeError("TensorflowPredictEffnetDiscogs not available")
                emb_predictor = TensorflowPredictEffnetDiscogs(graphFilename=params.emb_graph, output=emb_output)
            elif params.backbone == "musicnn":
                if TensorflowPredictMusiCNN is None:
                    raise RuntimeError("TensorflowPredictMusiCNN not available")
                emb_predictor = TensorflowPredictMusiCNN(graphFilename=params.emb_graph, output=emb_output)
            else:
                raise RuntimeError(f"Unsupported backbone {params.backbone}")
        
        # Cache the new predictor with device-specific key
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_output, emb_predictor, device=device)
        logging.debug(f"[inference] Cached new {params.backbone} predictor on {device}")
    else:
        logging.debug(f"[inference] Using cached {params.backbone} predictor on {device}")
    
    # Run embedding computation (already in correct device context from construction)
    wave_f32 = audio_result.waveform.astype(np.float32)
    emb = emb_predictor(wave_f32)
    emb = np.asarray(emb, dtype=np.float32)
    
    # ... existing normalization and return ...
```

2. **Update `ml_cache_comp.py` to support device-specific backbone keys**:

```python
def get_backbone_predictor(
    backbone: str,
    emb_graph: str,
    emb_output: str,
    device: str = "gpu",  # NEW
) -> Any | None:
    """Get cached backbone embedding predictor (device-specific)."""
    global _BACKBONE_CACHE
    cache_key = f"{backbone}::{emb_graph}::{emb_output}::{device}"  # Device-specific key
    
    with _CACHE_LOCK:
        return _BACKBONE_CACHE.get(cache_key)


def cache_backbone_predictor(
    backbone: str,
    emb_graph: str,
    emb_output: str,
    predictor: Any,
    device: str = "gpu",  # NEW
) -> None:
    """Cache a backbone embedding predictor (device-specific)."""
    global _BACKBONE_CACHE, _CACHE_LAST_ACCESS
    cache_key = f"{backbone}::{emb_graph}::{emb_output}::{device}"  # Device-specific key
    
    with _CACHE_LOCK:
        _BACKBONE_CACHE[cache_key] = predictor
        _CACHE_LAST_ACCESS = time.time()
        logging.debug(f"[cache] Cached backbone predictor: {cache_key}")
```

3. **Note on head models**: Already forced to CPU (line 300-320), no changes needed.

**Rationale**:
- **TensorFlow device contexts control where operations execute**: Wrapping predictor **construction** sets device permanently
- **Embeddings are the VRAM bottleneck**: EffNet = ~8GB, heads = ~100MB each
- **Device-specific caching required**: GPU and CPU predictors have different memory layouts
- **CPU fallback is 10-30x slower** but prevents crashes
- **Essentia TensorFlow operations respect `tf.device()` context**

**Key Insight from Backbone Caching**:
- **Single backbone cache per device**: 2 workers on GPU share 1 cached EffNet predictor (8GB total)
- **CPU/GPU independence**: Can have both `effnet::graph.pb::emb_output::gpu` and `effnet::graph.pb::emb_output::cpu` cached simultaneously (but total VRAM still controlled by GPU cache eviction)

**Performance Impact**:
- **GPU mode**: 2-3s per track (current)
- **CPU mode**: 30-60s per track (10-30x slower, but graceful)
- **Cache warmup**: First file per backbone+device = slow (builds predictor), rest = fast
- **Exit mode**: 0s (fail fast when even RAM exhausted)

---

### Phase 4: Workflow Device Passthrough (P0)

**Modify** `nomarr/workflows/processing/process_file_wf.py`

**Changes**:

1. **Add device parameter**:
```python
def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    db: Database,
    device: str = "gpu",  # NEW: device selection from worker
) -> ProcessingResultDict:
    """
    Main file processing workflow.
    
    Args:
        path: Absolute file path
        config: Processor configuration
        db: Database connection
        device: Device for ML inference ("gpu" or "cpu", default: "gpu")
    
    Returns:
        Processing result dict
    """
    # ... existing setup ...
    
    # Pass device to ML processing
    ml_result = _process_ml_tags(
        path=path,
        config=config,
        db=db,
        device=device,  # NEW: pass device
    )
    
    # ... rest of workflow ...
```

2. **Update ML processing helper**:
```python
def _process_ml_tags(
    path: str,
    config: ProcessorConfig,
    db: Database,
    device: str = "gpu",  # NEW
) -> dict[str, Any]:
    """Process ML tags for a file."""
    
    # ... existing head discovery ...
    
    for head_info in heads:
        # Get cached predictor or build new one with device selection
        predictor = get_or_build_predictor(head_info, device=device)  # NEW: pass device
        
        # ... existing prediction logic ...
```

3. **Update cache lookup**:
```python
def get_or_build_predictor(
    head_info: HeadInfo,
    device: str = "gpu",  # NEW
) -> Callable[[np.ndarray, int], np.ndarray]:
    """Get predictor from cache or build new one."""
    from nomarr.components.ml.ml_cache_comp import cache_key, get_cached_predictor
    from nomarr.components.ml.ml_inference_comp import make_predictor_uncached
    
    key = cache_key(head_info)
    
    # Cache key includes device (cpu/gpu predictors are different)
    cache_key_with_device = f"{key}::{device}"
    
    predictor = get_cached_predictor(cache_key_with_device)
    if predictor:
        return predictor
    
    # Build new predictor with device selection
    return make_predictor_uncached(head_info, device=device)
```

**Rationale**:
- Workflow acts as passthrough (no logic, just parameter forwarding)
- Cache needs device-specific keys (GPU/CPU predictors have different memory layouts)
- Minimal changes to existing workflow structure

---

### Phase 5: Cache Device Awareness (P1)

**Modify** `nomarr/components/ml/ml_cache_comp.py`

**Changes**:

1. **Update cache key to include device**:
```python
def cache_key(head_info: HeadInfo, device: str = "gpu") -> str:
    """Unique cache key for a head + device combination."""
    return f"{head_info.name}::{head_info.backbone}::{head_info.head_type}::{device}"
```

2. **Track cache size per device**:
```python
def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics including device breakdown."""
    gpu_count = sum(1 for k in _PREDICTOR_CACHE if k.endswith("::gpu"))
    cpu_count = sum(1 for k in _PREDICTOR_CACHE if k.endswith("::cpu"))
    
    return {
        "total": len(_PREDICTOR_CACHE),
        "gpu_predictors": gpu_count,
        "cpu_predictors": cpu_count,
    }
```

3. **Device-specific eviction**:
```python
def clear_gpu_cache() -> int:
    """Clear only GPU predictors from cache (free VRAM)."""
    global _PREDICTOR_CACHE
    
    with _CACHE_LOCK:
        gpu_keys = [k for k in _PREDICTOR_CACHE if k.endswith("::gpu")]
        for key in gpu_keys:
            del _PREDICTOR_CACHE[key]
        
        # Force TensorFlow to release GPU memory
        import gc
        gc.collect()
        
        try:
            import tensorflow as tf
            tf.keras.backend.clear_session()
        except Exception:
            pass
        
        logger.info(f"[cache] Cleared {len(gpu_keys)} GPU predictors (VRAM freed)")
        return len(gpu_keys)
```

**Rationale**:
- GPU and CPU predictors are separate entities (different memory, different performance)
- Need ability to clear GPU cache without evicting CPU fallback predictors
- Device-specific metrics for monitoring and debugging

---

### Phase 6: Worker Exit Behavior (P0)

**Modify** `nomarr/services/infrastructure/workers/discovery_worker.py`

**Changes**:

1. **Add resource exhaustion exit handler**:
```python
def run(self) -> None:
    # ... existing setup ...
    
    resource_failures = 0
    MAX_RESOURCE_FAILURES = 3  # Exit after 3 consecutive resource failures
    
    try:
        while not self._stop_event.is_set():
            file_id = discover_and_claim_file(db, self.worker_id)
            
            if file_id is None:
                resource_failures = 0  # Reset on idle
                time.sleep(IDLE_SLEEP_S)
                continue
            
            # Check resource headroom
            resources = check_resource_headroom()
            
            if resources["recommendation"] == "exit":
                resource_failures += 1
                
                logger.error(
                    "[%s] Insufficient resources (attempt %d/%d): VRAM %.1f%%, RAM %.1f%%",
                    self.worker_id,
                    resource_failures,
                    MAX_RESOURCE_FAILURES,
                    resources["vram_usage_percent"] * 100,
                    resources["ram_usage_percent"] * 100,
                )
                
                # Release claim so file becomes rediscoverable
                release_claim(db, file_id)
                
                if resource_failures >= MAX_RESOURCE_FAILURES:
                    logger.error(
                        "[%s] Persistent resource exhaustion (%d consecutive failures) - exiting. "
                        "This indicates system-wide memory pressure. "
                        "Reduce worker count or batch size in config.yaml",
                        self.worker_id,
                        resource_failures,
                    )
                    self._current_status = "failed"
                    break
                
                # Brief backoff before retry
                time.sleep(10.0)
                continue
            
            # Reset failure counter on successful resource check
            resource_failures = 0
            
            # ... rest of processing ...
```

2. **Log resource state on exit**:
```python
finally:
    # Cleanup on exit
    final_resources = check_resource_headroom()
    
    logger.info(
        "[%s] Discovery worker stopping (processed %d files, final state: VRAM %.1f%%, RAM %.1f%%)",
        self.worker_id,
        files_processed,
        final_resources["vram_usage_percent"] * 100,
        final_resources["ram_usage_percent"] * 100,
    )
    
    db.health.mark_stopping(self.worker_id)
    # ... existing cleanup ...
```

**Rationale**:
- 3 consecutive failures = persistent system-wide issue (not transient spike)
- Release claims on resource failure (file becomes rediscoverable by other workers)
- Clear log messages guide users to config changes
- Log final resource state for post-mortem debugging

---

## Configuration Changes

**Add to** `config.yaml`:

```yaml
processing:
  # ... existing settings ...
  
  # Resource management thresholds
  resource_management:
    enabled: true  # Enable adaptive GPU/CPU fallback (default: true)
    vram_threshold: 0.80  # VRAM usage threshold for CPU fallback (0.0-1.0)
    ram_threshold: 0.80   # RAM usage threshold for worker exit (0.0-1.0)
    check_interval_s: 5.0  # Seconds between resource checks (default: 5.0)
```

**Update** `nomarr/helpers/dto/processing_dto.py`:

```python
@dataclass
class ResourceManagementConfig:
    """Resource management configuration."""
    enabled: bool = True
    vram_threshold: float = 0.80
    ram_threshold: float = 0.80
    check_interval_s: float = 5.0

@dataclass
class ProcessorConfig:
    """Configuration for file processing."""
    # ... existing fields ...
    resource_management: ResourceManagementConfig = field(default_factory=ResourceManagementConfig)
```

**Rationale**:
- Users can disable adaptive behavior if desired (set `enabled: false`)
- Tunable thresholds for different hardware configurations
- Sensible defaults for typical 8-12GB GPU setups

---

## Testing Strategy

### Unit Tests

**New file**: `tests/unit/components/platform/test_resource_monitor.py`

```python
"""Tests for resource monitoring component."""

import pytest
from unittest.mock import patch, MagicMock

from nomarr.components.platform.resource_monitor_comp import (
    get_vram_usage,
    get_ram_usage,
    check_resource_headroom,
)


class TestVRAMMonitoring:
    """Tests for VRAM usage monitoring."""
    
    @pytest.mark.unit
    @patch("subprocess.run")
    def test_vram_usage_normal(self, mock_run):
        """Should parse nvidia-smi output correctly."""
        mock_run.return_value = MagicMock(
            stdout="12288, 4096",  # 12GB total, 4GB used
            returncode=0
        )
        
        result = get_vram_usage()
        
        assert result["total_mb"] == 12288
        assert result["used_mb"] == 4096
        assert result["free_mb"] == 8192
        assert abs(result["usage_percent"] - 0.333) < 0.01
        assert result["available"] is True
    
    @pytest.mark.unit
    @patch("subprocess.run")
    def test_vram_usage_gpu_unavailable(self, mock_run):
        """Should handle GPU unavailability gracefully."""
        mock_run.side_effect = FileNotFoundError()
        
        result = get_vram_usage()
        
        assert result["available"] is False
        assert "nvidia-smi not found" in result["error"]


class TestRAMMonitoring:
    """Tests for RAM usage monitoring."""
    
    @pytest.mark.unit
    @patch("psutil.virtual_memory")
    def test_ram_usage_normal(self, mock_mem):
        """Should parse psutil output correctly."""
        mock_mem.return_value = MagicMock(
            total=16 * 1024**3,  # 16GB
            available=8 * 1024**3,  # 8GB free
            percent=50.0
        )
        
        result = get_ram_usage()
        
        assert result["total_mb"] == 16384
        assert result["free_mb"] == 8192
        assert result["usage_percent"] == 0.50


class TestResourceHeadroom:
    """Tests for resource headroom checks."""
    
    @pytest.mark.unit
    @patch("nomarr.components.platform.resource_monitor_comp.get_vram_usage")
    @patch("nomarr.components.platform.resource_monitor_comp.get_ram_usage")
    def test_can_use_gpu_normal(self, mock_ram, mock_vram):
        """Should recommend GPU when both resources healthy."""
        mock_vram.return_value = {"usage_percent": 0.60, "available": True}
        mock_ram.return_value = {"usage_percent": 0.50}
        
        result = check_resource_headroom()
        
        assert result["can_use_gpu"] is True
        assert result["can_use_cpu"] is True
        assert result["recommendation"] == "gpu"
    
    @pytest.mark.unit
    @patch("nomarr.components.platform.resource_monitor_comp.get_vram_usage")
    @patch("nomarr.components.platform.resource_monitor_comp.get_ram_usage")
    def test_fallback_to_cpu_high_vram(self, mock_ram, mock_vram):
        """Should recommend CPU when VRAM > 80%."""
        mock_vram.return_value = {"usage_percent": 0.85, "available": True}
        mock_ram.return_value = {"usage_percent": 0.50}
        
        result = check_resource_headroom()
        
        assert result["can_use_gpu"] is False
        assert result["can_use_cpu"] is True
        assert result["recommendation"] == "cpu"
    
    @pytest.mark.unit
    @patch("nomarr.components.platform.resource_monitor_comp.get_vram_usage")
    @patch("nomarr.components.platform.resource_monitor_comp.get_ram_usage")
    def test_exit_both_resources_exhausted(self, mock_ram, mock_vram):
        """Should recommend exit when both VRAM and RAM > 80%."""
        mock_vram.return_value = {"usage_percent": 0.85, "available": True}
        mock_ram.return_value = {"usage_percent": 0.85}
        
        result = check_resource_headroom()
        
        assert result["can_use_gpu"] is False
        assert result["can_use_cpu"] is False
        assert result["recommendation"] == "exit"
```

### Integration Tests

**New file**: `tests/integration/test_worker_resource_management.py`

```python
"""Integration tests for worker resource management."""

import pytest
from unittest.mock import patch, MagicMock

# Mark as container_only (requires GPU, models, DB)
pytestmark = pytest.mark.container_only


class TestWorkerResourceFallback:
    """Tests for worker GPU -> CPU fallback behavior."""
    
    def test_worker_processes_file_on_cpu(self, test_db, test_audio_file):
        """Worker should successfully process file using CPU when VRAM high."""
        # TODO: Implement after Phase 2-4 complete
        pass
    
    def test_worker_exits_on_ram_exhaustion(self, test_db, test_audio_file):
        """Worker should exit gracefully when RAM exhausted."""
        # TODO: Implement after Phase 6 complete
        pass
```

---

## Rollout Plan

### Phase 0: Dependencies (Week 1)

1. Add `psutil>=5.9.0` to:
   - `requirements.txt`
   - `pyproject.toml`
   - `dockerfile.base`
2. Update Python environment in dev/CI
3. Verify psutil works on target OS (Linux, Windows)

### Phase 1: Resource Monitoring (Week 1-2)

1. Implement `resource_monitor_comp.py`
2. Write unit tests
3. Manual testing: verify nvidia-smi parsing, psutil RAM queries
4. Document public API in module docstring

### Phase 2: Worker Resource Checks (Week 2-3)

1. Add resource checks to discovery worker
2. Implement backoff/exit logic
3. Add device selection passthrough
4. Update health frames (optional device telemetry)
5. Manual testing: simulate high VRAM/RAM, verify worker behavior

### Phase 3: ML Inference Device Selection (Week 3-4)

1. Add device parameter to `compute_embeddings_for_backbone`
2. Add TensorFlow device contexts
3. Update predictor construction
4. Manual testing: verify CPU fallback produces same results (within tolerance)
5. Performance benchmarking: GPU vs CPU inference times

### Phase 4: Workflow Integration (Week 4)

1. Add device parameter to `process_file_workflow`
2. Update ML processing helpers
3. Device-aware cache lookups
4. Integration testing: end-to-end file processing on GPU and CPU

### Phase 5: Cache Device Awareness (Week 5)

1. Update cache key generation
2. Implement device-specific eviction
3. Add cache statistics
4. Manual testing: verify GPU cache eviction frees VRAM

### Phase 6: Configuration and Documentation (Week 5-6)

1. Add `resource_management` config section
2. Update `ProcessorConfig` dataclass
3. Update user documentation:
   - "Out of Memory Errors" troubleshooting page
   - Add "Resource Management" section
4. Update deployment guide with tuning recommendations

---

## Performance Impact

### Expected Behavior

**Normal operation (VRAM < 80%, RAM < 80%)**:
- ✅ No performance change (GPU as usual)
- ✅ 5s resource check overhead every 5s (negligible)
- ✅ No additional VRAM usage

**High VRAM (VRAM > 80%, RAM < 80%)**:
- ⚠️ 10-30x slower processing (CPU fallback)
- ✅ No worker crashes
- ✅ Files still get processed (eventually)
- ✅ Workers log clear warnings

**Resource exhaustion (VRAM > 80%, RAM > 80%)**:
- ✅ Worker exits gracefully after 3 failures
- ✅ Claims released (files rediscoverable)
- ✅ Clear log messages point to config changes
- ✅ No orphaned claims or DB corruption

### Benchmarks (to measure during implementation)

**GPU mode** (current):
- EffNet embedding: ~2s per track
- MusiCNN embedding: ~1.5s per track
- Head inference: ~0.3s per track
- **Total**: 2-3s per track

**CPU mode** (expected):
- EffNet embedding: ~30-60s per track (20-30x slower)
- MusiCNN embedding: ~15-30s per track (10-20x slower)
- Head inference: ~0.5s per track (already on CPU)
- **Total**: 30-60s per track

**Resource check overhead**:
- nvidia-smi query: ~50-100ms
- psutil RAM query: ~1-5ms
- **Total per check**: ~50-100ms (every 5s = 1-2% overhead)

---

## Monitoring and Observability

### Log Messages

**Resource warnings**:
```
[worker:tag:0] VRAM usage 85.3% > 80%, falling back to CPU processing
[worker:tag:0] Insufficient resources (attempt 1/3): VRAM 87.1%, RAM 82.4%
[worker:tag:0] Persistent resource exhaustion (3 consecutive failures) - exiting
```

**Health frame telemetry** (optional):
```json
{"component_id": "worker:tag:0", "status": "healthy", "device": "cpu"}
{"component_id": "worker:tag:1", "status": "failed", "device": null}
```

### Metrics to Track (Future)

- `worker_device_mode{worker_id, device}` - Which device worker is using
- `resource_check_duration_ms` - Time to check VRAM/RAM
- `cpu_fallback_count` - Number of times worker fell back to CPU
- `resource_exhaustion_exits` - Number of workers that exited due to resource pressure

---

## Risks and Mitigations

### Risk 1: CPU fallback too slow (processing stalls)

**Impact**: Workers spend hours processing single files, queue backs up

**Mitigation**:
- Workers continue making progress (slow > crash)
- Users can disable resource management if desired (`enabled: false`)
- Clear log warnings alert users to config issues
- Add `max_cpu_processing_time_s` config to skip files that are too slow

### Risk 2: Resource checks add latency

**Impact**: 50-100ms overhead every 5s

**Mitigation**:
- Check interval configurable (`check_interval_s`)
- Checks only run when work available (not during idle)
- 1-2% overhead acceptable vs OOM crashes

### Risk 3: psutil not available on target OS

**Impact**: RAM monitoring fails, workers can't detect exhaustion

**Mitigation**:
- psutil is mature, cross-platform library (Linux, Windows, macOS)
- Fallback to `/proc/meminfo` parsing on Linux if psutil fails
- Windows: use `ctypes` + `GlobalMemoryStatusEx` if psutil unavailable

### Risk 4: TensorFlow ignores device context

**Impact**: CPU fallback doesn't actually use CPU

**Mitigation**:
- Test with `TF_CPP_MIN_LOG_LEVEL=0` to see device placement logs
- Verify with `nvidia-smi` that VRAM drops when using CPU mode
- Essentia TensorFlow operations tested to respect `tf.device()` contexts

### Risk 5: Cache device-specific keys break existing cache

**Impact**: Cached predictors become invalid, must rebuild

**Mitigation**:
- Phase 5 is P1 (not blocking for MVP)
- Workers rebuild cache on startup (existing behavior)
- Add migration: append `::gpu` to existing cache keys on first run

---

## Success Criteria

**Must Have (P0)**:
- ✅ Workers check VRAM/RAM before each job
- ✅ Workers fall back to CPU when VRAM > 80%
- ✅ Workers exit gracefully when RAM > 80%
- ✅ No OOM crashes during normal operation
- ✅ Clear log messages guide users to config changes

**Should Have (P1)**:
- ✅ Device-aware cache (separate GPU/CPU predictors)
- ✅ Cache GPU eviction frees VRAM
- ✅ Health frames include device telemetry
- ✅ Configuration options for thresholds

**Nice to Have (P2)**:
- Performance metrics (device mode, fallback counts)
- Max CPU processing time limit (skip slow files)
- StateBroker resource state aggregation

---

## Open Questions

1. **Should we check resources mid-job?**
   - Current plan: check before job only
   - Alternative: check every 5s during long jobs (adaptive mid-job fallback)
   - Decision: Start with pre-job checks, add mid-job checks if needed (P2)

2. **Should we cache CPU and GPU predictors simultaneously?**
   - Current plan: single device per cache key
   - Alternative: cache both, select at runtime
   - Decision: Single device per key (simpler, less memory)

3. **Should we auto-adjust worker count based on resources?**
   - Current plan: fixed worker count from config
   - Alternative: dynamic worker spawning/killing based on VRAM availability
   - Decision: Fixed count for now, dynamic scaling is P3 (requires significant service layer changes)

4. **Should we support mixed device workloads (some workers GPU, some CPU)?**
   - Current plan: each worker independently chooses device per job
   - This naturally creates mixed workloads when resources fluctuate
   - Decision: Implicit support via per-job checks (no explicit mixed-mode config)

---

## Related Work

**Existing Nomarr features**:
- GPU availability probing: `gpu_probe_comp.py`
- GPU health monitoring: `gpu_monitor_comp.py`
- Cache idle eviction: `ml_cache_comp.py` (timeout-based)
- Worker crash recovery: `worker_crash_comp.py` (restart limits)

**Integration points**:
- Discovery worker resource checks complement GPU health monitoring
- Resource monitoring uses same nvidia-smi approach as GPU probe
- Cache eviction can be triggered by high VRAM (in addition to idle timeout)

**Architecture alignment**:
- Resource monitor is leaf component (`components/platform/`)
- Workers call resource monitor (no upward imports)
- No changes to health telemetry protocol (optional device field only)
- Compatible with existing worker restart/crash handling

---

## Appendix A: TensorFlow Device Placement Primer

**Device contexts in TensorFlow**:
```python
import tensorflow as tf

# Force operation to CPU
with tf.device("/CPU:0"):
    result = model(input_data)

# Force operation to GPU
with tf.device("/GPU:0"):
    result = model(input_data)

# Use default device (usually GPU if available)
result = model(input_data)
```

**Essentia TensorFlow predictors**:
- Essentia's `TensorflowPredict*` classes respect TensorFlow device contexts
- Must wrap predictor **construction** in device context (not just prediction calls)
- Device placement is sticky (stays on chosen device for predictor lifetime)

**Verification**:
```python
# Enable TensorFlow device placement logging
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "0"

# Run inference - watch logs for "Executing op ... on /device:CPU:0"
```

---

## Appendix B: nvidia-smi Memory Query Examples

**Query VRAM usage**:
```bash
nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits
# Output: 12288,4096,8192  (MB: total, used, free)
```

**Query per-process VRAM**:
```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits
# Output: 1234,4096  (PID, used MB)
```

**Query GPU utilization** (optional future metric):
```bash
nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits
# Output: 85  (percent)
```

---

## Appendix C: psutil RAM Query Examples

**Query system RAM**:
```python
import psutil

mem = psutil.virtual_memory()
print(f"Total: {mem.total / 1024**3:.1f} GB")
print(f"Available: {mem.available / 1024**3:.1f} GB")
print(f"Used: {mem.used / 1024**3:.1f} GB")
print(f"Percent: {mem.percent}%")
```

**Query process memory** (optional future metric):
```python
import psutil
import os

process = psutil.Process(os.getpid())
mem_info = process.memory_info()
print(f"RSS: {mem_info.rss / 1024**3:.1f} GB")  # Resident set size
print(f"VMS: {mem_info.vms / 1024**3:.1f} GB")  # Virtual memory size
```

---

## Document Metadata

**Created**: 2026-01-20  
**Author**: GitHub Copilot (Claude Sonnet 4.5)  
**Target Audience**: ML agent implementing GPU/CPU resource management  
**Status**: PLANNING - Implementation not started  
**Estimated Implementation Time**: 5-6 weeks (1 developer)  
**Lines of Code Added**: ~800-1000 (new component + worker changes + tests)  
**Files Modified**: 8 files (3 new, 5 modified)  
**Dependencies Added**: psutil>=5.9.0  

**Review Checklist**:
- [ ] Resource monitoring approach verified with manual nvidia-smi/psutil testing
- [ ] TensorFlow device context behavior validated with small test script
- [ ] Configuration schema reviewed (sensible defaults, clear naming)
- [ ] Performance impact acceptable (1-2% overhead normal, 10-30x slower CPU fallback)
- [ ] Risk mitigations sufficient (CPU too slow, psutil unavailable, etc.)
- [ ] Architecture alignment confirmed (leaf component, no upward imports)
- [ ] Testing strategy complete (unit + integration tests)
- [ ] Documentation updates planned (user guide, deployment guide)
- [ ] Rollout plan realistic (5-6 weeks, phased implementation)
