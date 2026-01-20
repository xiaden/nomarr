# GPU/CPU Adaptive Resource Management

**Status**: Not implemented  
**Target**: Worker system + ML inference components  
**Deployment**: Python + Docker + nvidia-container-runtime (GPU passthrough)  
**Goal**: Workers monitor VRAM/RAM → fallback from GPU to CPU when VRAM > 80% → transition to recovering health state when RAM > 80%

---

## Current State

**Lazy cache + backbone caching: ✅ COMPLETE**

Workers now use backbone caching with lazy warmup and idle eviction:
- `_BACKBONE_CACHE` populated via `cache_backbone_predictor()` / `get_cached_backbone_predictor()`
- Workers wait for first file before loading models (lazy warmup)
- Cache evicts after 300s idle (frees VRAM)
- Backbone predictors cached per (backbone, emb_graph) key

**Missing: Adaptive resource management**

Workers still crash on VRAM exhaustion. No runtime resource checks, no GPU→CPU fallback.

---

## Problem

**Backbone models dominate VRAM**:
- EffNet: ~8GB per predictor
- MusiCNN: ~4GB per predictor  
- YAMNet: ~2GB per predictor
- Heads: ~100MB each (already CPU-only via `tf.device("/CPU:0")`)

**Current behavior**:
- Workers crash with `ResourceExhaustedError` when VRAM fills
- 2 workers × 8GB EffNet = 16GB minimum VRAM (even with caching)
- No fallback when resources spike (large files, calibration, multiple workers)

**User impact**:
- OOM crashes mid-job → orphaned claims
- Users must manually reduce worker count or batch size
- docs/user/getting_started.md:664 has troubleshooting section for OOM errors

---

## Solution

Workers check VRAM/RAM before each file (throttled via short-TTL cache):

1. **VRAM < 80%** → Use GPU (normal)
2. **VRAM ≥ 80%, RAM < 80%** → Use CPU + RAM (slow but safe)
3. **VRAM ≥ 80%, RAM ≥ 80%** → Transition to `recovering` health state with bounded recovery window (domain owner decides restart/backoff)

```
Worker claims file
    │
    ▼
Check VRAM usage (cached, TTL=1s)
    │
    ├─ < 80%  → Use GPU (2-3s per file)
    │
    └─ ≥ 80%  → Check RAM usage (cached, TTL=1s)
                    │
                    ├─ < 80%  → Use CPU (30-60s per file, but no crash)
                    │
                    └─ ≥ 80%  → Release claim, report 'recovering',
                                wait for recovery window or owner policy
```

---

## Implementation

### Phase 0: Add psutil dependency

**Dependency source of truth**: `pyproject.toml`

**Actions**:
1. Add `psutil>=5.9.0` to `pyproject.toml` dependencies
2. Regenerate `requirements.txt` from pyproject.toml (via `pip-compile` or equivalent)
3. Rebuild `dockerfile.base` (Docker build will install from requirements.txt)

**Do not** manually add psutil to multiple files—maintain single source of truth in pyproject.toml.

---

### Phase 1: Resource monitoring component with short-TTL caching

**Create** `nomarr/components/platform/resource_monitor_comp.py`:

**Critical requirement**: Subprocess calls (nvidia-smi, psutil) are expensive (50-100ms). Workers must NOT shell out per file. Use short-TTL caching (1-2s) to throttle queries.

```python
"""Resource monitoring for VRAM and RAM usage with short-TTL caching.

This is a LEAF PROBE component. It returns raw resource facts (VRAM %, RAM %, availability, errors).
Threshold/policy decisions belong in the caller (worker runtime or config-driven logic).
"""

import logging
import subprocess
import time
from typing import Any

CACHE_TTL_S = 1.0  # Cache resource queries for 1 second

# Module-level cache
_vram_cache: dict[str, Any] | None = None
_vram_cache_ts: float = 0.0
_ram_cache: dict[str, Any] | None = None
_ram_cache_ts: float = 0.0


def get_vram_usage() -> dict[str, Any]:
    """
    Query current VRAM usage via nvidia-smi (cached with 1s TTL).
    
    Returns dict:
        - total_mb: int
        - used_mb: int
        - free_mb: int
        - usage_percent: float (0.0-1.0)
        - available: bool
        - error: str | None
    """
    global _vram_cache, _vram_cache_ts
    
    # Return cached value if within TTL
    now = time.time()
    if _vram_cache is not None and (now - _vram_cache_ts) < CACHE_TTL_S:
        return _vram_cache
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=True,
        )
        
        # Parse: "12288, 4096" (MB)
        parts = result.stdout.strip().split(",")
        total_mb = int(parts[0].strip())
        used_mb = int(parts[1].strip())
        free_mb = total_mb - used_mb
        usage_percent = used_mb / total_mb if total_mb > 0 else 0.0
        
        result_dict = {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "free_mb": free_mb,
            "usage_percent": usage_percent,
            "available": True,
            "error": None,
        }
        
        # Cache the result
        _vram_cache = result_dict
        _vram_cache_ts = now
        
        return result_dict
    
    except FileNotFoundError:
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "available": False,
            "error": "nvidia-smi not found",
        }
    except Exception as e:
        logging.warning(f"[resource] Failed to query VRAM: {e}")
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "available": False,
            "error": str(e),
        }


def get_ram_usage() -> dict[str, Any]:
    """
    Query current RAM usage via psutil (cached with 1s TTL).
    
    **Container semantics**: psutil.virtual_memory() reports host memory, NOT cgroup limits.
    In Docker deployments, this may not reflect container memory limits. If container has
    cgroup memory limit (e.g., `docker run --memory=8g`), consider reading `/sys/fs/cgroup/memory/memory.limit_in_bytes`
    and `/sys/fs/cgroup/memory/memory.usage_in_bytes` instead.
    
    Returns dict:
        - total_mb: int
        - used_mb: int
        - free_mb: int
        - usage_percent: float (0.0-1.0)
        - error: str | None
    """
    global _ram_cache, _ram_cache_ts
    
    # Return cached value if within TTL
    now = time.time()
    if _ram_cache is not None and (now - _ram_cache_ts) < CACHE_TTL_S:
        return _ram_cache
    
    try:
        import psutil
        
        mem = psutil.virtual_memory()
        total_mb = int(mem.total / (1024 ** 2))
        free_mb = int(mem.available / (1024 ** 2))
        used_mb = total_mb - free_mb
        usage_percent = mem.percent / 100.0  # psutil gives 0-100, normalize to 0-1
        
        result_dict = {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "free_mb": free_mb,
            "usage_percent": usage_percent,
            "error": None,
        }
        
        # Cache the result
        _ram_cache = result_dict
        _ram_cache_ts = now
        
        return result_dict
    
    except ImportError:
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "error": "psutil not installed",
        }
    except Exception as e:
        logging.warning(f"[resource] Failed to query RAM: {e}")
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "error": str(e),
        }


def check_resource_headroom(
    vram_threshold: float = 0.80,
    ram_threshold: float = 0.80,
) -> dict[str, Any]:
    """
    Check if sufficient resources for GPU processing.
    
    **Layering**: This function derives recommendations from config-provided thresholds.
    The raw probe functions (get_vram_usage, get_ram_usage) return facts only.
    
    Args:
        vram_threshold: VRAM usage threshold (0.0-1.0, default 0.80)
        ram_threshold: RAM usage threshold (0.0-1.0, default 0.80)
    
    Returns dict:
        - can_use_gpu: bool (VRAM < vram_threshold)
        - can_use_cpu: bool (RAM < ram_threshold)
        - vram_usage_percent: float
        - ram_usage_percent: float
        - recommendation: str ("gpu", "cpu", or "recovering" - derived from thresholds)
    """
    vram = get_vram_usage()
    ram = get_ram_usage()
    
    vram_ok = vram["available"] and vram["usage_percent"] < vram_threshold
    ram_ok = ram["usage_percent"] < ram_threshold
    
    if vram_ok:
        recommendation = "gpu"
    elif ram_ok:
        recommendation = "cpu"
    else:
        recommendation = "recovering"  # Both exhausted
    
    return {
        "can_use_gpu": vram_ok,
        "can_use_cpu": ram_ok,
        "vram_usage_percent": vram["usage_percent"],
        "ram_usage_percent": ram["usage_percent"],
        "recommendation": recommendation,
    }
```

**Tests** in `tests/unit/components/platform/test_resource_monitor.py`:
- Mock nvidia-smi output → verify parsing
- Mock psutil output → verify usage calculation
- Test threshold logic (< 80%, ≥ 80% scenarios)
- Test TTL caching: verify subprocess NOT called within 1s window
- Test cache expiry: verify subprocess IS called after TTL expires

---

### Phase 2: Worker resource checks with health-contract-aligned recovery

**Modify** `nomarr/services/infrastructure/workers/discovery_worker.py`:

**Critical**: Workers must NOT embed backoff/restart policy. On resource exhaustion, worker transitions to `recovering` health state and reports exhaustion duration. Domain owner (WorkerSystemService) decides restart/backoff/fail based on policy.

```python
# Add imports
from nomarr.components.platform.resource_monitor_comp import check_resource_headroom

# Add constants
RESOURCE_RECOVERY_WINDOW_S = 30.0  # Report 'recovering' for 30s before checking if still exhausted

def run(self) -> None:
    # ... existing setup ...
    
    resource_exhaustion_start: float | None = None  # Track when exhaustion began
    
    try:
        while not self._stop_event.is_set():
            file_id = discover_and_claim_file(db, self.worker_id)
            
            if file_id is None:
                resource_exhaustion_start = None  # Reset on idle
                # ... existing cache eviction ...
                time.sleep(IDLE_SLEEP_S)
                continue
            
            # NEW: Check resources before processing (uses cached values, TTL=1s)
            # Pass thresholds from config (policy comes from caller, not probe)
            resources = check_resource_headroom(
                vram_threshold=config.resource_management.vram_threshold,
                ram_threshold=config.resource_management.ram_threshold,
            )
            
            if resources["recommendation"] == "recovering":
                # Both VRAM and RAM exhausted
                now = time.time()
                
                if resource_exhaustion_start is None:
                    resource_exhaustion_start = now
                    logger.warning(
                        "[%s] Resource exhaustion detected: VRAM %.1f%%, RAM %.1f%% - entering recovery",
                        self.worker_id,
                        resources["vram_usage_percent"] * 100,
                        resources["ram_usage_percent"] * 100,
                    )
                
                exhaustion_duration = now - resource_exhaustion_start
                
                # Report 'recovering' health state via health frames
                self._current_status = "recovering"
                
                release_claim(db, file_id)  # Release so other workers can try
                
                # If still exhausted after recovery window, log and wait for owner policy
                if exhaustion_duration > RESOURCE_RECOVERY_WINDOW_S:
                    logger.error(
                        "[%s] Persistent resource exhaustion for %.1fs (VRAM %.1f%%, RAM %.1f%%). "
                        "Owner will decide restart/backoff. Check config.yaml worker_count or batch_size.",
                        self.worker_id,
                        exhaustion_duration,
                        resources["vram_usage_percent"] * 100,
                        resources["ram_usage_percent"] * 100,
                    )
                    # Owner reads 'recovering' status and applies policy (restart, backoff, or fail)
                
                time.sleep(5.0)  # Brief wait before retry
                continue
            
            # Resources recovered
            if resource_exhaustion_start is not None:
                logger.info(
                    "[%s] Resources recovered after %.1fs",
                    self.worker_id,
                    time.time() - resource_exhaustion_start,
                )
                resource_exhaustion_start = None
                self._current_status = "healthy"
            
            # Determine device for this job
            device = "gpu" if resources["can_use_gpu"] else "cpu"
            
            if device == "cpu":
                logger.warning(
                    "[%s] VRAM %.1f%% > 80%% - using CPU (slow)",
                    self.worker_id,
                    resources["vram_usage_percent"] * 100,
                )
            
            # Reset resource failure counter
            resource_failures = 0
            
            # ... existing cache warmup ...
            
            # Process file WITH DEVICE
            result = process_file_workflow(
                path=file_path,
                config=config,
                db=db,
                device=device,  # NEW
            )
            
            # ... existing completion logic ...
```

---

### Phase 3: CPU-only enforcement via separate worker pools (RECOMMENDED)

**Critical requirement**: `tf.device("/CPU:0")` is a hint, NOT enforcement. TensorFlow may still place operations on GPU. Per-call toggling of `CUDA_VISIBLE_DEVICES` inside a running process is UNRELIABLE once TF is initialized.

**Recommended approach: Separate worker pools at process level**

1. **GPU worker pool**: Spawn `worker_count` workers with CUDA_VISIBLE_DEVICES inherited (sees GPU)
2. **CPU worker pool**: Spawn separate `cpu_worker_count` workers with `CUDA_VISIBLE_DEVICES=""` at process start (never sees GPU)
3. **Resource-based routing**: When VRAM > threshold, route files to CPU worker pool instead of GPU workers

**WorkerSystemService changes**:

```python
class WorkerSystemService:
    def start_workers(self, config: ProcessorConfig) -> None:
        # GPU worker pool (normal)
        for i in range(config.worker_count):
            worker = create_discovery_worker(
                worker_index=i,
                worker_type="gpu",  # NEW
                # ... existing params ...
            )
            worker.start()
        
        # CPU worker pool (CPU-only, optional)
        if config.cpu_worker_count > 0:
            for i in range(config.cpu_worker_count):
                # Set CUDA_VISIBLE_DEVICES="" BEFORE spawning process
                worker = create_discovery_worker(
                    worker_index=i,
                    worker_type="cpu",  # NEW
                    cuda_visible_devices="",  # NEW: hide GPU at process start
                    # ... existing params ...
                )
                worker.start()
```

**DiscoveryWorker changes**:

```python
class DiscoveryWorker(multiprocessing.Process):
    def __init__(
        self,
        worker_id: str,
        worker_type: str = "gpu",  # NEW: "gpu" or "cpu"
        cuda_visible_devices: str | None = None,  # NEW: set at process start
        # ... existing params ...
    ) -> None:
        super().__init__()
        self.worker_id = worker_id
        self.worker_type = worker_type
        self._cuda_visible_devices = cuda_visible_devices
        # ... existing fields ...
    
    def run(self) -> None:
        # Set CUDA_VISIBLE_DEVICES BEFORE any TensorFlow imports
        if self._cuda_visible_devices is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = self._cuda_visible_devices
            logging.info(f"[{self.worker_id}] CPU-only mode: CUDA_VISIBLE_DEVICES='{self._cuda_visible_devices}'")
        
        # ... existing setup ...
        # TensorFlow imports happen in ml components (after env var set)
```

**Alternative (NOT RECOMMENDED): Per-call CUDA_VISIBLE_DEVICES toggling**

This approach is fragile because:
- TensorFlow caches GPU device list at initialization
- Changing env vars mid-process may not take effect
- Requires TF session reset (expensive, unreliable)

**If you must use per-call toggling** (e.g., single worker pool with dynamic switching):

```python
# In ml_inference_comp.py (NOT RECOMMENDED)
def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
    device: str = "gpu",
) -> tuple[np.ndarray, float, str]:
    # ... existing code ...
    
    if emb_predictor is None and device == "cpu":
        # WARNING: This may not work reliably if TF already initialized on GPU
        original_cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        
        try:
            # Force TF session reset (expensive)
            import tensorflow as tf
            tf.keras.backend.clear_session()
            
            # Build CPU predictor
            emb_predictor = build_predictor(...)
        finally:
            if original_cuda is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda
            else:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
```

**Strongly prefer separate worker pools over per-call toggling.**

**Modify** `nomarr/components/ml/ml_cache_comp.py`:

Update backbone cache functions to include device in cache key:

```python
def backbone_cache_key(backbone: str, emb_graph: str, device: str = "gpu") -> str:
    """Generate cache key for backbone predictor (device-specific)."""
    return f"backbone::{backbone}::{emb_graph}::{device}"


def get_cached_backbone_predictor(backbone: str, emb_graph: str, device: str = "gpu") -> Any | None:
    """Get cached backbone predictor for specific device."""
    key = backbone_cache_key(backbone, emb_graph, device)
    return _BACKBONE_CACHE.get(key)


def cache_backbone_predictor(backbone: str, emb_graph: str, predictor: Any, device: str = "gpu") -> None:
    """Cache backbone predictor for specific device."""
    key = backbone_cache_key(backbone, emb_graph, device)
    with _CACHE_LOCK:
        _BACKBONE_CACHE[key] = predictor
        logging.debug(f"[cache] Cached {backbone} on {device}")
```

---

### Phase 4: Workflow device passthrough

**Modify** `nomarr/workflows/processing/process_file_wf.py`:

Add device parameter and pass through to ML functions:

```python
def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    db: Database,
    device: str = "gpu",  # NEW
) -> ProcessingResultDict:
    """Main file processing workflow."""
    
    # ... existing setup ...
    
    # Pass device to embedding computation
    embeddings_result = compute_embeddings_for_backbone(
        params=emb_params,
        device=device,  # NEW
    )
    
    # ... rest of workflow ...
```

---

### Phase 5: Configuration (optional)

Add resource management config to `config.yaml`:

```yaml
processing:
  # ... existing ...
  worker_count: 2  # GPU worker pool
  cpu_worker_count: 1  # CPU-only worker pool (CUDA_VISIBLE_DEVICES="", optional)
  
  resource_management:
    enabled: true
    vram_threshold: 0.80  # Route to CPU pool when VRAM > 80%
    ram_threshold: 0.80   # Transition to 'recovering' when RAM > 80%
    cache_ttl_s: 1.0      # Resource query cache TTL
```

Update `helpers/dto/processing_dto.py`:

```python
@dataclass
class ResourceConfig:
    enabled: bool = True
    vram_threshold: float = 0.80
    ram_threshold: float = 0.80
    cache_ttl_s: float = 1.0

@dataclass
class ProcessorConfig:
    # ... existing ...
    worker_count: int = 1  # GPU workers
    cpu_worker_count: int = 0  # CPU-only workers (0 = disabled)
    resource_management: ResourceConfig = field(default_factory=ResourceConfig)
```

---

## Performance Impact

**Normal (VRAM < 80%)**:
- No change (GPU as usual)
- ~1-2ms overhead per file (cached resource checks, TTL=1s)
- Subprocess calls (nvidia-smi/psutil) throttled to once per second

**High VRAM (VRAM ≥ 80%, RAM < 80%)**:
- CPU fallback: 10-30x slower (30-60s per file vs 2-3s)
- CUDA_VISIBLE_DEVICES="" enforcement adds ~50-100ms predictor construction overhead (one-time per cache key)
- No crashes
- Files still process (eventually)

**Exhausted (VRAM ≥ 80%, RAM ≥ 80%)**:
- Worker transitions to `recovering` health state
- Claims released (files rediscoverable by other workers)
- Domain owner (WorkerSystemService) decides restart/backoff based on policy
- Worker does NOT exit immediately (bounded recovery window = 30s)
- Clear error logs point to config.yaml changes

---

## Testing

**Unit tests (CI)** - `tests/unit/components/platform/test_resource_monitor.py`:
- Mock nvidia-smi output → verify VRAM parsing
- Mock psutil output → verify RAM parsing
- Test check_resource_headroom with various threshold configs
- Test TTL caching: verify subprocess NOT called within 1s window
- Test cache expiry: verify subprocess IS called after TTL expires
- Mock worker resource exhaustion → verify `recovering` health state transition

**CI testing scope**: Only unit tests run in CI (no GPU available). All GPU-dependent assertions must be mocked.

**Local/system tests (GPU host required)** - NOT in CI:
- Start GPU worker pool + CPU worker pool (separate processes)
- Process files with both pools → verify VRAM usage:
  - GPU workers: VRAM increases during processing
  - CPU workers: VRAM unchanged (CUDA_VISIBLE_DEVICES="" effective)
- Artificially exhaust VRAM (allocate large tensors) → verify resource monitor detects it
- Verify CPU workers produce same results as GPU workers (within floating-point tolerance)
- Monitor worker health transitions: `healthy` → `recovering` → `healthy`

**System test strategy**:
1. Deploy to GPU host (local or staging)
2. Configure `worker_count=1` (GPU) + `cpu_worker_count=1` (CPU)
3. Process test library (100 files) with both pools
4. Assert VRAM usage via `nvidia-smi` logs:
   - GPU worker: VRAM > 8GB during EffNet processing
   - CPU worker: VRAM unchanged (proves CUDA_VISIBLE_DEVICES="" works)
5. Compare tag outputs: GPU vs CPU results must match (within 1e-6 tolerance)

---

## Risks

**CPU too slow**: 30-60s per file may cause queue backups
- Mitigation: Workers continue making progress (slow > crash)
- Users can disable if needed (`enabled: false`)

**TensorFlow ignores tf.device() hint**: CPU fallback still uses GPU despite `tf.device("/CPU:0")`
- Mitigation: Use SEPARATE CPU WORKER POOL with `CUDA_VISIBLE_DEVICES=""` set at process start
- Per-call toggling of CUDA_VISIBLE_DEVICES is unreliable (TF caches GPU list at init)
- System tests on GPU host verify VRAM unchanged for CPU workers (proves enforcement)

**Container RAM reporting incorrect**: psutil reports host memory, not cgroup limit
- Mitigation: In Docker, consider reading `/sys/fs/cgroup/memory/memory.limit_in_bytes` instead
- Make RAM threshold configurable (default 0.80, but allow 0.95 if cgroup limits not detected)
- Phase 5 config should add `ram_threshold_mode: "host" | "cgroup" | "auto"`

**TTL cache too short/long**: 1s TTL may not suit all workloads
- Mitigation: Make `CACHE_TTL_S` configurable (range: 0.5-2.0s)
- Fast workers (2s/file) need short TTL (0.5s) for responsiveness
- Slow workers (60s/file) can tolerate longer TTL (2s) for less overhead

---

## Success Criteria

**Must have**:
- resource_monitor_comp is leaf probe (returns facts, accepts thresholds from caller)
- Workers check VRAM/RAM before each file (using TTL-cached queries, max 1 subprocess/sec)
- Separate CPU worker pool with CUDA_VISIBLE_DEVICES="" at process start (NOT per-call toggling)
- Workers transition to `recovering` health state when RAM > 80% (domain owner decides policy)
- No OOM crashes during normal operation
- CPU workers verified CPU-only via system tests on GPU host (VRAM unchanged assertion)

**Should have**:
- Device-specific cache keys (separate GPU/CPU predictors)
- Config options for thresholds (VRAM, RAM, TTL, recovery window)
- Container memory detection (cgroup limits vs host memory)
- Clear error logs guide users to config.yaml fixes

---

## Open Questions

1. **Check resources mid-job?** Current plan checks before each file only. Could add checks during long files (60s+ tracks). TTL caching makes mid-job checks cheap (<2ms).

2. **Cache both GPU and CPU predictors?** Current plan caches one device per key. Could cache both simultaneously (uses more RAM but allows instant switching). With CUDA_VISIBLE_DEVICES enforcement, GPU/CPU predictors are truly separate.

3. **Dynamic worker count?** Current plan uses fixed worker count from config. Could auto-reduce worker count when resources low (requires service layer changes + health monitor integration).

4. **RAM threshold too aggressive in containers?** If RAM reporting is host memory (not cgroup), 80% threshold may trigger false recoveries. Consider separate thresholds for host vs cgroup, or make RAM checks log-only by default until container semantics verified.

---

## Related Work

**Existing features**:
- GPU availability probe: `gpu_probe_comp.py` (nvidia-smi)
- GPU health monitor: `gpu_monitor_comp.py` (writes to DB)
- Cache idle eviction: `ml_cache_comp.py` (300s timeout)
- Lazy cache warmup: `discovery_worker.py` (waits for first file)

**Integration**:
- Resource monitor uses same nvidia-smi approach as GPU probe
- Resource checks complement GPU health monitoring
- Cache eviction already handles idle timeout (this adds VRAM pressure eviction)

---

**Document created**: 2026-01-20  
**Last updated**: 2026-01-20 (hardened for deployment + health contract alignment)  
**Status**: Not implemented  
**Estimated time**: 3-4 weeks  
**Files modified**: 6 (1 new, 5 modified)  
**Dependencies**: psutil>=5.9.0 (add to pyproject.toml, regenerate requirements.txt)  
**Deployment context**: Docker + nvidia-container-runtime + Python 3.12  
**Health contract**: Workers report `recovering` on resource exhaustion; domain owner decides restart/backoff/fail
