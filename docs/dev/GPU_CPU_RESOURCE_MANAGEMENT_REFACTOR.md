# GPU/CPU Adaptive Resource Management

**Status**: Not implemented  
**Target**: Worker system + ML inference components  
**Deployment**: Python + Docker + nvidia-container-runtime (GPU passthrough)  
**Goal**: Workers monitor VRAM/RAM → spill backbone from GPU to CPU when VRAM > budget → transition to recovering health state when RAM > budget

**Architecture**: Single worker pool with per-worker backbone device selection (GPU preferred, CPU spill on VRAM pressure). Heads always remain on CPU (no device changes).

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

**Scope**: Resource management applies to **backbone models only**. Head models always remain on CPU (see Device Allocation Model below).

Workers check VRAM/RAM before processing each file (throttled via short-TTL cache):

1. **VRAM < budget** → Place backbone on GPU (normal: 2-3s per file)
   - Heads remain on CPU (no change)
2. **VRAM ≥ budget, RAM < budget** → Spill backbone to CPU (slow but safe: 30-60s per file)
   - Heads remain on CPU (no change)
3. **VRAM ≥ budget, RAM ≥ budget** → Cannot guarantee atomicity
   - Release file claim, transition to `recovering` health state
   - Domain owner decides restart/backoff policy

**What "backoff" means**:
- Spilling backbone predictor from VRAM to RAM/CPU
- **Does NOT** mean: moving head models (always CPU), rerouting workers, or changing head device placement

**Resource exhaustion response**:
- Worker enters `recovering` state with bounded recovery window
- Worker does NOT thrash or repeatedly probe
- Domain owner (WorkerSystemService) decides restart/reduce-workers policy

```
Worker claims file
    │
    ▼
Check VRAM usage (cached, TTL=1s)
    │
    ├─ < 80%  → Use backbone on GPU (2-3s per file)
    │            [heads always remain on CPU]
    │
    └─ ≥ 80%  → Check RAM usage (cached, TTL=1s)
                    │
                    ├─ < 80%  → Spill backbone to CPU (30-60s per file, but no crash)
                    │            [heads always remain on CPU]
                    │
                    └─ ≥ 80%  → Release claim, report 'recovering',
                                wait for recovery window or owner policy
```

---

## Device Allocation Model (Split-Device Architecture)

Nomarr uses split-device ML: backbones may use GPU or CPU, heads are always CPU.

**Backbone models** (embedding extractors):
- May run on GPU (preferred: 2-3s/file) or CPU (fallback: 30-60s/file)
- Examples: EffNet (~8GB), MusiCNN (~4GB), YAMNet (~2GB)
- Per-worker cache: ~2 backbones in VRAM (~12GB total)

**Head models** (tag classifiers):
- **MUST ALWAYS run on CPU** (existing architecture via `tf.device("/CPU:0")`)
- **NEVER place on GPU** (wastes VRAM, monopolizes GPU)
- Examples: ~100MB each, ~16-24 heads cached per worker (~2GB RAM)

**"GPU → CPU fallback" means**: When VRAM > budget, place backbone on CPU (not GPU). Heads always remain on CPU (no change). Same file, slower processing.

---

## GPU Support Scope (NVIDIA CUDA Only)

**Supported GPU acceleration**: NVIDIA CUDA only.

**GPU capability confirmation**:
- In Docker deployments, GPU availability depends on correct `nvidia-docker` device/runtime injection.
- A successful `nvidia-smi` execution inside the container is the capability proof that CUDA was passed into the container.
- If `nvidia-smi` is unavailable or fails, the system treats the container as NOT GPU-capable.

**Behavior when GPU unavailable**:
- Disable all GPU tiers (Tier 0, 1, 2).
- Force CPU-only execution (Tier 3 or Tier 4 if insufficient RAM).
- Log clear message: "NVIDIA GPU not detected (nvidia-smi failed). Running CPU-only (Tier 3)."

**Non-goals for this refactor**:
- **AMD ROCm**: Out of scope (not testable in current dev environment).
- **Intel GPU acceleration**: Out of scope (not testable in current dev environment).
- Do NOT add fallback hooks, placeholders, or partial detection logic for AMD/Intel.
- Do NOT document untestable AMD/Intel behavior.

**Rationale**: This refactor targets NVIDIA CUDA because:
1. Current dev/test environment uses NVIDIA hardware only.
2. AMD/Intel GPU support would require hardware access for validation.
3. Pre-alpha policy permits breaking changes; AMD/Intel can be added post-1.0 if demand exists.

---

## GPU Capability Gate (Docker)

**Problem**: In Docker, GPU availability is NOT guaranteed even if host has GPU. Container must receive correct device/runtime injection.

**Solution**: Distinguish GPU **capability** ("GPU is available in-container") from GPU **telemetry** ("VRAM usage readings").

### Capability vs Telemetry

**GPU Capability** (required before any GPU tier):
- **What it proves**: NVIDIA CUDA is available inside the container.
- **How to detect**: Successful `nvidia-smi` execution inside container.
- **When to check**: Once at startup (before ML Capacity Probe).
- **On failure**: Disable GPU tiers (Tier 0/1/2), force CPU-only (Tier 3).

**GPU Telemetry** (used only after capability confirmed):
- **What it provides**: VRAM usage, per-PID memory readings.
- **How to query**: `nvidia-smi --query-compute-apps=pid,used_memory`.
- **When to check**: Per-file (with TTL cache) during Tier 0/1/2 execution.
- **On failure**: Should not happen (capability already confirmed), but treat as transient error.

### Capability Gate in Tier Selection

**Updated tier selection flow**:

```python
def select_execution_tier(
    capacity_estimate: dict,
    vram_budget_mb: int,
    ram_budget_mb: int,
    gpu_capable: bool,  # NEW: from capability probe
) -> int:
    """Select highest-performance tier that fits within budgets.
    
    Args:
        gpu_capable: True if nvidia-smi succeeded (NVIDIA CUDA available in-container).
    """
    
    # GPU capability gate: If GPU not available, skip GPU tiers entirely
    if not gpu_capable:
        logging.info("[tier-selection] GPU not capable (nvidia-smi failed). Skipping GPU tiers.")
        # Force CPU-only tier selection
        tier3_ram = int(capacity_estimate["measured_backbone_vram_mb"] * 0.6 + 
                        capacity_estimate["estimated_worker_ram_mb"] * 0.4)
        if ram_budget_mb >= tier3_ram:
            return 3  # CPU-only
        else:
            return 4  # Refuse (insufficient RAM for CPU execution)
    
    # GPU is capable, proceed with normal tier ladder
    backbone_vram_mb = capacity_estimate["measured_backbone_vram_mb"]
    worker_ram_mb = capacity_estimate["estimated_worker_ram_mb"]
    
    # Tier 0: Full cache, multi-worker (requires GPU)
    tier0_vram = backbone_vram_mb * 2
    tier0_ram = worker_ram_mb * 2
    if vram_budget_mb >= tier0_vram and ram_budget_mb >= tier0_ram:
        return 0
    
    # Tier 1: Reduced cache, reduced workers (requires GPU)
    tier1_vram = backbone_vram_mb
    tier1_ram = worker_ram_mb
    if vram_budget_mb >= tier1_vram and ram_budget_mb >= tier1_ram:
        return 1
    
    # Tier 2: Sequential GPU (requires GPU)
    tier2_vram = int(backbone_vram_mb * 0.5)
    tier2_ram = int(worker_ram_mb * 0.4)
    if vram_budget_mb >= tier2_vram and ram_budget_mb >= tier2_ram:
        return 2
    
    # Tier 3: Sequential CPU (no GPU required)
    tier3_ram = int(backbone_vram_mb * 0.6 + worker_ram_mb * 0.4)
    if ram_budget_mb >= tier3_ram:
        return 3
    
    # Tier 4: Cannot satisfy minimum requirements
    return 4
```

**Capability probe location**: Phase 1 (resource_monitor_comp.py).

**Capability probe frequency**: Once at startup, cached for lifetime of service.

**Capability probe failure modes**:
- `nvidia-smi` not found → Not GPU-capable (expected in CPU-only deployments)
- `nvidia-smi` found but returns error → Not GPU-capable (Docker device injection failed)
- `nvidia-smi` timeout → Not GPU-capable (transient, but safer to assume no GPU)

---

## Atomicity / All-or-Nothing Invariant

ML processing must either complete fully or not run at all. Workers check resources before claiming files:

**Requirements**: Worker must guarantee sufficient RAM for:
1. All required head models (~2GB)
2. Backbone graphs (if VRAM pressure forces CPU spill: ~8GB)

**If both VRAM and RAM exhausted**:
- Do NOT claim/process file (cannot guarantee atomicity)
- Release any claims, transition to `recovering` health state
- Do NOT write partial ML results

**Rationale**: Partial results corrupt DB (indistinguishable from legitimate no-match results).

---

## Execution Tiers (Resource-Adaptive Degradation)

**Purpose**: When capacity probe indicates VRAM+RAM exhaustion, degrade execution mode rather than crash or refuse all work.

### Tier Definitions

**Tier 0: Fast Path** (Normal operation)
- Cached per-model TF graphs: 2 backbones in GPU VRAM (~12GB), 16-24 heads in RAM (~2GB)
- Multi-worker (admission control calculates safe count from probe)
- Processing speed: 2-3s/file
- **Heads: CPU-only** (NEVER on GPU)

**Tier 1: Reduced Cache / Reduced Concurrency**
- Smaller backbone cache: 1 backbone in VRAM (~8GB)
- Smaller head cache: 8-12 heads in RAM (~1GB)
- Reduced worker count (e.g., max_workers // 2)
- Processing speed: 3-5s/file (cache thrashing overhead)
- **Heads: CPU-only** (NEVER on GPU)

**Tier 2: Sequential GPU Execution**
- No large persistent caches
- Load one backbone graph at a time on GPU, execute, unload
- Load heads as needed per file
- Single worker (concurrency = 1)
- Processing speed: 5-10s/file (graph loading overhead)
- **Heads: CPU-only** (NEVER on GPU)

**Tier 3: Sequential CPU Execution** (CPU spill fallback)
- Load one backbone graph at a time on CPU, execute, unload
- Load heads as needed per file
- Single worker (concurrency = 1)
- Processing speed: 30-60s/file (CPU inference + graph loading)
- **Heads: CPU-only** (always, no change from other tiers)

**Tier 4: Refuse Execution**
- Even Tier 3 cannot satisfy RAM floor (minimum for one backbone + heads)
- Worker transitions to `health-dead`
- Domain owner decides: wait for resources, reduce model set, or fail
- No partial processing

### Immutable Invariants Across All Tiers

1. **Heads are CPU-only**: MUST NEVER run on GPU in any tier
2. **Atomic per-file processing**: All required steps persist or none do (no partial results)
3. **Health contract**: Workers report status, domain owner decides lifecycle actions

### Tier Selection Logic

**Deterministic mapping** from GPU capability + probe metrics + user budgets:

```python
def select_execution_tier(
    capacity_estimate: dict,
    vram_budget_mb: int,
    ram_budget_mb: int,
    gpu_capable: bool,  # NEW: from GPU capability probe (nvidia-smi check)
) -> int:
    """Select highest-performance tier that fits within budgets.
    
    Args:
        gpu_capable: True if NVIDIA GPU is available (nvidia-smi succeeded in-container).
    """
    
    # GPU capability gate: If NVIDIA GPU not available, skip GPU tiers entirely
    if not gpu_capable:
        logging.info("[tier-selection] NVIDIA GPU not detected. Forcing CPU-only tiers.")
        # Force CPU-only tier selection
        tier3_ram = int(capacity_estimate["measured_backbone_vram_mb"] * 0.6 + 
                        capacity_estimate["estimated_worker_ram_mb"] * 0.4)
        if ram_budget_mb >= tier3_ram:
            return 3  # CPU-only
        else:
            return 4  # Refuse (insufficient RAM for CPU execution)
    
    # NVIDIA GPU is capable, proceed with normal tier ladder
    backbone_vram_mb = capacity_estimate["measured_backbone_vram_mb"]  # e.g., 8192 for EffNet
    worker_ram_mb = capacity_estimate["estimated_worker_ram_mb"]      # e.g., 2457 with margin
    
    # Tier 0: Full cache, multi-worker (requires NVIDIA GPU)
    tier0_vram = backbone_vram_mb * 2  # Cache 2 backbones
    tier0_ram = worker_ram_mb * 2      # 2 workers minimum
    if vram_budget_mb >= tier0_vram and ram_budget_mb >= tier0_ram:
        return 0
    
    # Tier 1: Reduced cache, reduced workers (requires NVIDIA GPU)
    tier1_vram = backbone_vram_mb      # Cache 1 backbone
    tier1_ram = worker_ram_mb          # 1 worker, reduced head cache
    if vram_budget_mb >= tier1_vram and ram_budget_mb >= tier1_ram:
        return 1
    
    # Tier 2: Sequential GPU (requires NVIDIA GPU)
    tier2_vram = int(backbone_vram_mb * 0.5)  # Minimal graph overhead
    tier2_ram = int(worker_ram_mb * 0.4)      # Minimal heads + overhead
    if vram_budget_mb >= tier2_vram and ram_budget_mb >= tier2_ram:
        return 2
    
    # Tier 3: Sequential CPU (no NVIDIA GPU required)
    tier3_ram = int(backbone_vram_mb * 0.6 + worker_ram_mb * 0.4)  # Backbone on CPU + heads
    if ram_budget_mb >= tier3_ram:
        return 3
    
    # Tier 4: Cannot satisfy minimum requirements
    return 4
```

**Tier selection ownership**: Infrastructure/services layer (WorkerSystemService). NOT domain workflows.

**GPU capability check**: See "GPU Capability Gate (Docker)" section above for capability vs telemetry distinction.

### How Tiers Map to Worker Behavior

**Tier 0-1**: Normal cache-based execution (existing workflow)
- Workers claim files, check resources, process via cached graphs
- Tier 1 reduces cache sizes and worker count (config-driven)

**Tier 2-3**: Sequential execution (new workflow mode)
- Worker loads graph, processes file, unloads graph (explicit cache eviction)
- Tier 3 uses `prefer_gpu=False` for all backbone calls
- Single-threaded (max_workers=1 enforced by admission control)

**Tier 4**: No execution
- Workers do not start (admission control spawns 0 workers)
- Or workers transition to `health-dead` if tier degrades at runtime
- Log error: "Insufficient resources for any execution tier. Check config budgets or reduce model set."

### Example Tier Selection

**Scenario**: EffNet backbone (8GB VRAM, 2GB worker RAM with heads)

| GPU Capable | VRAM Budget | RAM Budget | Selected Tier | Worker Count | Behavior |
|-------------|-------------|------------|---------------|--------------|----------|
| ✅ Yes      | 20 GB       | 8 GB       | 0             | 4            | Full cache, multi-worker (fast) |
| ✅ Yes      | 10 GB       | 4 GB       | 1             | 2            | Reduced cache, fewer workers |
| ✅ Yes      | 6 GB        | 2 GB       | 2             | 1            | Sequential GPU, no cache |
| ✅ Yes      | 0 GB        | 12 GB      | 3             | 1            | Sequential CPU (slow fallback) |
| ✅ Yes      | 0 GB        | 1 GB       | 4             | 0            | Refuse (insufficient RAM) |
| ❌ No       | 20 GB       | 12 GB      | 3             | 1            | Force CPU-only (nvidia-smi failed) |
| ❌ No       | 20 GB       | 1 GB       | 4             | 0            | Refuse (no GPU + insufficient RAM) |

---

---

## ML Capacity Probe (One-Time Measurement)

Measures per-worker resource consumption for admission control. Runs **once** per `model_set_hash` (not per-worker, not on startup).

### Probe Lock (Race Prevention)

Uses ArangoDB unique constraint on `ml_capacity_probe_locks` collection:
1. Worker attempts insert: `{"_key": model_set_hash, "status": "in_progress", "worker_id": ...}`
2. **Insert succeeds** → This worker performs probe
3. **Insert fails** → Another worker owns lock → Poll `ml_capacity_estimates` (5s interval, 60s timeout)
4. **Timeout** → Fall back to conservative `max_workers=1`

**Worker behavior during probe**: May claim non-ML work; MUST NOT claim ML work until probe completes.

### Probe Procedure

1. Acquire probe lock (see above)
2. Process one real file (backbone + heads)
3. Measure per-process usage:
   - VRAM: `nvidia-smi --query-compute-apps=pid,used_memory`
   - RAM: `psutil.Process(os.getpid()).memory_info().rss`
4. Persist estimate to `ml_capacity_estimates`:
   ```python
   {"_key": model_set_hash, "measured_backbone_vram_mb": 8192,
    "measured_process_ram_mb": 2048, "estimated_worker_ram_mb": 2457,
    "timestamp": ..., "backbone_models": [...], "head_count": 24}
   ```
5. Update lock `status: "complete"`
6. **Tier selection**: Service layer calls `select_execution_tier()` using probe metrics + config budgets

**Invalidation**: When `model_set_hash` changes or user triggers recalibration.

---

## Admission Control (Worker Scaling)

Determines execution tier and spawns appropriate worker count. Uses tier selection to degrade gracefully instead of crashing.

**Mechanism**:
1. **Check GPU capability**: `gpu_capable = check_nvidia_gpu_capability()` (once at startup)
2. Wait for capacity estimate (blocks on first run, 120s timeout)
3. **Select execution tier**: `tier = select_execution_tier(capacity, vram_budget, ram_budget, gpu_capable)`
4. Calculate worker count based on tier:
   - **Tier 0**: `min(vram_budget // (2*backbone_vram), ram_budget // (2*worker_ram), max_workers)`
   - **Tier 1**: `min(vram_budget // backbone_vram, ram_budget // worker_ram, max_workers // 2)`
   - **Tier 2-3**: Force `max_workers = 1` (sequential execution)
   - **Tier 4**: `max_workers = 0` (refuse execution, log error)
4. Spawn workers with 2-3s stagger, configured for selected tier
5. Workers self-regulate via resource checks (may degrade tier at runtime if resources change)

```python
def start_workers(self, config: ProcessorConfig) -> None:
    # Check NVIDIA GPU capability once at startup
    gpu_capable = check_nvidia_gpu_capability()  # nvidia-smi probe
    
    if not gpu_capable:
        logging.warning(
            "[admission] NVIDIA GPU not detected (nvidia-smi failed). "
            "Running CPU-only (Tier 3)."
        )
    
    capacity = self._wait_for_capacity_estimate(model_set_hash, timeout_s=120)
    
    if capacity is None:
        target_workers = 1  # Conservative fallback
        execution_tier = 3 if not gpu_capable else 2  # Force CPU-only if no GPU
    else:
        # Select tier based on GPU capability + probe + budgets
        execution_tier = select_execution_tier(
            capacity,
            config.resource_management.vram_budget_mb,
            config.resource_management.ram_budget_mb,
            gpu_capable,  # NEW: pass GPU capability signal
        )
        
        if execution_tier == 0:
            # Full cache, multi-worker
            safe_vram = vram_budget_mb // (capacity["measured_backbone_vram_mb"] * 2)
            safe_ram = ram_budget_mb // (capacity["estimated_worker_ram_mb"] * 2)
            target_workers = min(safe_vram, safe_ram, config.max_workers)
        elif execution_tier == 1:
            # Reduced cache, fewer workers
            safe_vram = vram_budget_mb // capacity["measured_backbone_vram_mb"]
            safe_ram = ram_budget_mb // capacity["estimated_worker_ram_mb"]
            target_workers = min(safe_vram, safe_ram, config.max_workers // 2, 2)
        elif execution_tier in (2, 3):
            # Sequential execution (Tier 2: GPU, Tier 3: CPU)
            target_workers = 1
        else:  # execution_tier == 4
            # Refuse execution
            logging.error(
                f"[admission] Tier 4 (refuse): Insufficient resources. "
                f"VRAM budget: {vram_budget_mb}MB, RAM budget: {ram_budget_mb}MB. "
                f"Required: VRAM ~{capacity['measured_backbone_vram_mb'] * 0.5}MB, "
                f"RAM ~{capacity['estimated_worker_ram_mb'] * 0.6}MB minimum."
            )
            target_workers = 0
    
    logging.info(f"[admission] Selected Tier {execution_tier}, spawning {target_workers} workers")
    
    for i in range(target_workers):
        worker = self._spawn_worker(
            config, 
            worker_index=i,
            execution_tier=execution_tier,  # NEW: pass tier to worker
        )
        worker.start()
        time.sleep(2.0)
```

**Result**: Graceful degradation through tiers instead of crash/refuse.

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

**Capability vs Telemetry**:
- **GPU Capability**: `check_nvidia_gpu_capability()` runs once at startup, cached forever (or until service restart).
- **GPU Telemetry**: `get_vram_usage()` runs per-file with TTL cache (only after capability confirmed).

```python
"""Resource monitoring with TTL caching. Leaf probe returning raw facts."""
import logging
import subprocess
import time
from typing import Any

CACHE_TTL_S = 1.0
_vram_cache: dict[str, Any] | None = None
_vram_cache_ts: float = 0.0
_ram_cache: dict[str, Any] | None = None
_ram_cache_ts: float = 0.0
_gpu_capable_cache: bool | None = None  # NEW: cached forever (checked once at startup)


def check_nvidia_gpu_capability() -> bool:
    """Check if NVIDIA GPU is available in-container (capability signal, not telemetry).
    
    This is the GPU CAPABILITY GATE for Docker deployments.
    - Runs once at startup (cached forever).
    - A successful nvidia-smi execution proves NVIDIA CUDA is available in-container.
    - If nvidia-smi fails, treat container as NOT GPU-capable → force CPU-only tiers.
    
    Returns:
        True if nvidia-smi succeeded (NVIDIA GPU available).
        False if nvidia-smi failed or not found (CPU-only mode).
    """
    global _gpu_capable_cache
    
    # Return cached result (checked once at startup)
    if _gpu_capable_cache is not None:
        return _gpu_capable_cache
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=True,
        )
        gpu_name = result.stdout.strip()
        logging.info(f"[resource] NVIDIA GPU detected: {gpu_name}")
        _gpu_capable_cache = True
        return True
    except FileNotFoundError:
        logging.info("[resource] nvidia-smi not found. Running CPU-only (Tier 3).")
        _gpu_capable_cache = False
        return False
    except subprocess.CalledProcessError as e:
        logging.warning(
            f"[resource] nvidia-smi failed (exit code {e.returncode}). "
            "Possible Docker device injection issue. Running CPU-only (Tier 3)."
        )
        _gpu_capable_cache = False
        return False
    except subprocess.TimeoutExpired:
        logging.warning(
            "[resource] nvidia-smi timeout (5s). "
            "Assuming no GPU available. Running CPU-only (Tier 3)."
        )
        _gpu_capable_cache = False
        return False
    except Exception as e:
        logging.error(f"[resource] Unexpected error checking GPU capability: {e}")
        _gpu_capable_cache = False
        return False


def get_vram_usage() -> dict[str, Any]:
    """Query VRAM via nvidia-smi (GPU TELEMETRY, cached 1s TTL).
    
    IMPORTANT: Only call this AFTER confirming GPU capability via check_nvidia_gpu_capability().
    This provides VRAM usage telemetry for budget enforcement, NOT capability detection.
    
    Returns: {total_mb, used_mb, free_mb, usage_percent, available, error}
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


def get_ram_usage(ram_detection_mode: str = "auto") -> dict[str, Any]:
    """
    Query current RAM usage via psutil or cgroup (cached with 1s TTL).
    
    **Container semantics**: In Docker/k8s deployments, psutil.virtual_memory() reports
    host memory, NOT container cgroup limits. For accurate container RAM detection:
    - cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes, memory.usage_in_bytes
    - cgroup v2: /sys/fs/cgroup/memory.max, memory.current
    
    Args:
        ram_detection_mode:
            - "auto": prefer cgroup if present, else host
            - "cgroup": force cgroup (fail if not found)
            - "host": force host memory (psutil)
    
    Returns dict:
        - total_mb: int
        - used_mb: int
        - free_mb: int
        - usage_percent: float (0.0-1.0)
        - detection_mode: str ("cgroup_v1", "cgroup_v2", or "host")
        - error: str | None
    """
    global _ram_cache, _ram_cache_ts
    
    # Return cached value if within TTL
    now = time.time()
    if _ram_cache is not None and (now - _ram_cache_ts) < CACHE_TTL_S:
        return _ram_cache
    
    try:
        detection_mode_used = "host"
        
        # Try cgroup detection if requested
        if ram_detection_mode in ("auto", "cgroup"):
            # Try cgroup v2 first
            if os.path.exists("/sys/fs/cgroup/memory.max"):
                with open("/sys/fs/cgroup/memory.max") as f:
                    limit_str = f.read().strip()
                with open("/sys/fs/cgroup/memory.current") as f:
                    usage_str = f.read().strip()
                
                if limit_str != "max":  # "max" means no limit
                    total_bytes = int(limit_str)
                    used_bytes = int(usage_str)
                    total_mb = int(total_bytes / (1024 ** 2))
                    used_mb = int(used_bytes / (1024 ** 2))
                    free_mb = total_mb - used_mb
                    usage_percent = used_mb / total_mb if total_mb > 0 else 0.0
                    detection_mode_used = "cgroup_v2"
            
            # Try cgroup v1
            elif os.path.exists("/sys/fs/cgroup/memory/memory.limit_in_bytes"):
                with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
                    total_bytes = int(f.read().strip())
                with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
                    used_bytes = int(f.read().strip())
                
                # cgroup v1 may report huge limit if not set (e.g., 9223372036854771712)
                if total_bytes < (1024 ** 5):  # < 1 PB (sanity check)
                    total_mb = int(total_bytes / (1024 ** 2))
                    used_mb = int(used_bytes / (1024 ** 2))
                    free_mb = total_mb - used_mb
                    usage_percent = used_mb / total_mb if total_mb > 0 else 0.0
                    detection_mode_used = "cgroup_v1"
            
            elif ram_detection_mode == "cgroup":
                raise FileNotFoundError("Cgroup RAM detection requested but cgroup files not found")
        
        # Fall back to host RAM if cgroup not used/found
        if detection_mode_used == "host":
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
            "detection_mode": detection_mode_used,
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
            "detection_mode": "error",
            "error": "psutil not installed",
        }
    except Exception as e:
        logging.warning(f"[resource] Failed to query RAM: {e}")
        return {
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "detection_mode": "error",
            "error": str(e),
        }


def check_resource_headroom(
    vram_budget_mb: int,
    ram_budget_mb: int,
    vram_estimate_mb: int,
    ram_estimate_mb: int,
) -> dict[str, Any]:
    """
    Check if sufficient resources for backbone GPU placement.
    
    **Layering**: This function derives recommendations from config-provided budgets.
    The raw probe functions (get_vram_usage, get_ram_usage) return facts only.
    
    **Scope**: This applies to BACKBONE placement only. Heads always remain on CPU.
    
    **Budget semantics**: Budgets are MAXIMUM ML usage caps (not "minimum free").
    - vram_budget_mb: maximum VRAM ML is allowed to consume
    - ram_budget_mb: maximum RAM ML is allowed to consume
    - Logic: used_mb + estimate_mb <= budget_mb
    
    Args:
        vram_budget_mb: VRAM budget in MB (from config)
        ram_budget_mb: RAM budget in MB (from config)
        vram_estimate_mb: Estimated VRAM for one additional backbone (from capacity probe)
        ram_estimate_mb: Estimated RAM for one additional worker (heads + backbone spill, from capacity probe)
    
    Returns dict:
        - can_use_gpu: bool (VRAM usage + estimate <= budget)
        - can_use_cpu: bool (RAM usage + estimate <= budget)
        - vram_used_mb: int
        - vram_free_mb: int
        - ram_used_mb: int
        - ram_free_mb: int
        - recommendation: str ("gpu", "cpu", or "recovering" - derived from budgets)
    """
    vram = get_vram_usage()
    ram = get_ram_usage()
    
    # Budget semantics: used + estimate <= budget
    vram_ok = vram["available"] and (vram["used_mb"] + vram_estimate_mb <= vram_budget_mb)
    ram_ok = ram["used_mb"] + ram_estimate_mb <= ram_budget_mb
    
    if vram_ok:
        recommendation = "gpu"
    elif ram_ok:
        recommendation = "cpu"  # Spill backbone to CPU/RAM
    else:
        recommendation = "recovering"  # Both exhausted, cannot guarantee atomicity
    
    return {
        "can_use_gpu": vram_ok,
        "can_use_cpu": ram_ok,
        "vram_used_mb": vram["used_mb"],
        "vram_free_mb": vram["free_mb"],
        "ram_used_mb": ram["used_mb"],
        "ram_free_mb": ram["free_mb"],
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

**Critical**: Workers must NOT embed backoff/restart policy. On resource exhaustion, worker transitions to `recovering` health state and suggests recovery duration. Domain owner (WorkerSystemService) decides restart/backoff/fail based on policy.

**NEW**: Workers accept `execution_tier` parameter and adapt behavior:
- **Tier 0-1**: Cache-based execution (existing workflow)
- **Tier 2-3**: Sequential execution (load graph, process file, unload graph)
- Runtime tier degradation: If resources exhausted mid-operation, worker may downgrade tier

```python
from nomarr.components.platform.resource_monitor_comp import check_resource_headroom

def __init__(self, worker_id: str, execution_tier: int = 0, ...):
    self.execution_tier = execution_tier  # NEW
    # ... existing fields ...

def run(self) -> None:
    # Load capacity estimate (or use conservative defaults)
    capacity = self._db.get_capacity_estimate(compute_model_set_hash(self.config))
    vram_estimate_mb = capacity["measured_backbone_vram_mb"] if capacity else 8192
    ram_estimate_mb = capacity["estimated_worker_ram_mb"] if capacity else 4096
    
    resource_exhaustion_start: float | None = None
    
    while not self._stop_event.is_set():
        file_id = discover_and_claim_file(db, self.worker_id)
        if file_id is None:
            resource_exhaustion_start = None
            # Tier 2-3: Explicit cache eviction between files
            if self.execution_tier >= 2:
                evict_all_cached_graphs()  # Free VRAM/RAM
            time.sleep(IDLE_SLEEP_S)
            continue
        
        # Check resources (applies to backbone placement only, heads always CPU)
        resources = check_resource_headroom(
            vram_budget_mb=config.resource_management.vram_budget_mb,
            ram_budget_mb=config.resource_management.ram_budget_mb,
            vram_estimate_mb=vram_estimate_mb,
            ram_estimate_mb=ram_estimate_mb,
        )
        
        # Atomicity check: both VRAM and RAM exhausted?
        if resources["recommendation"] == "recovering":
            if resource_exhaustion_start is None:
                resource_exhaustion_start = time.time()
                logger.warning(f"[{self.worker_id}] Tier {self.execution_tier}: Resource exhaustion")
            
            exhaustion_duration = time.time() - resource_exhaustion_start
            self.report_health("recovering", recover_for_s=min(exhaustion_duration * 2, 60.0))
            release_claim(db, file_id)
            time.sleep(2.0)
            continue
        
        # Resources recovered
        if resource_exhaustion_start is not None:
            logger.info(f"[{self.worker_id}] Resources recovered")
            resource_exhaustion_start = None
            self.report_health("healthy")
        
        # Determine device preference
        # Tier 0-2: Prefer GPU if VRAM available
        # Tier 3: Force CPU (prefer_gpu=False)
        prefer_gpu = (self.execution_tier < 3) and resources["can_use_gpu"]
        
        if not prefer_gpu and self.execution_tier < 3:
            logger.warning(f"[{self.worker_id}] Tier {self.execution_tier}: VRAM pressure - spilling backbone to CPU")
        
        result = process_file_workflow(
            path=file_path,
            config=config,
            db=db,
            prefer_gpu=prefer_gpu,
            cache_mode="sequential" if self.execution_tier >= 2 else "normal",  # NEW
        )
        
        # Tier 2-3: Explicit cache eviction after file
        if self.execution_tier >= 2:
            evict_all_cached_graphs()  # Free resources immediately
        
        # ... existing completion logic ...
```

**Health contract integration**:
- Worker calls `self.report_health("recovering", recover_for_s=X)` when resources exhausted
- HealthMonitor clamps `recover_for_s` per policy
- If resources recover, worker calls `self.report_health("healthy")` immediately
- If no recovery, health transitions to `health-dead` per HealthMonitor policy
- WorkerSystemService may decide to restart workers at lower tier

**Health contract integration**:
- Worker calls `self.report_health("recovering", recover_for_s=X)` when resources exhausted
- HealthMonitor clamps `recover_for_s` per policy (e.g., max 60s)
- If resources recover earlier, worker calls `self.report_health("healthy")` immediately (no waiting)
- If resources do NOT recover, health state transitions to `health-dead` per HealthMonitor policy
- WorkerSystemService decides restart/reduce-workers/fail based on health state

### How Resource Pressure Maps to Health States

**Normal operation** (VRAM/RAM within budget):
- Health state: `healthy`
- Worker processes files normally

**VRAM pressure, RAM okay** (VRAM > budget, RAM < budget):
- Health state: `healthy` (degraded performance, not failure)
- Worker spills backbone to CPU (slow but functional)
- Logs warning, continues processing

**Both exhausted** (VRAM > budget AND RAM > budget):
- Health state: `recovering` with suggested `recover_for_s`
- Worker releases claims, waits for resources
- If resources recover: return to `healthy` immediately
- If no recovery: HealthMonitor transitions to `health-dead` per policy
- WorkerSystemService decides next action (restart, reduce workers, etc.)

**Policy reference**: See existing HealthMonitor configuration for:
- Max recovery duration (default: 60s)
- Transition rules (`recovering` → `health-dead` after max duration)
- Restart/backoff thresholds

---

### Phase 3: Backbone device selection (GPU vs CPU spill)

**Scope**: This phase addresses **backbone model placement only**. Head models are ALWAYS on CPU (existing architecture, no changes).

**Architecture**: Single worker pool with per-worker backbone device selection based on VRAM pressure. When VRAM exceeds budget, worker spills backbone to CPU/RAM within same process. Heads always remain on CPU (no change).

**Device placement note**: `tf.device("/CPU:0")` is a hint, not enforcement. TensorFlow may still place operations on GPU if it determines the hint is suboptimal. For CPU spill to be reliable, validate device placement via logging or assertions during development/testing. Per-call toggling of `CUDA_VISIBLE_DEVICES` is unreliable once TF is initialized and should NOT be used.

**Modify** `nomarr/components/ml/ml_inference_comp.py`:

Add backbone device selection logic:

```python
def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
    prefer_gpu: bool = True,
) -> tuple[np.ndarray, float, str]:
    backend_essentia.require()
    emb_output = get_embedding_output_node(params.backbone)
    emb_predictor = get_cached_backbone_predictor(params.backbone, params.emb_graph)
    
    if emb_predictor is None:
        logging.debug(f"Building {params.backbone} (prefer {'GPU' if prefer_gpu else 'CPU'})")
        
        # Use tf.device() hint for CPU spill
        device_ctx = tf.device("/CPU:0") if (HAVE_TF and not prefer_gpu) else contextlib.nullcontext()
        
        with device_ctx:
            if params.backbone == "yamnet":
                emb_predictor = TensorflowPredictVGGish(graphFilename=params.emb_graph, ...)
            elif params.backbone == "effnet":
                emb_predictor = TensorflowPredictEffnetDiscogs(graphFilename=params.emb_graph, ...)
            # ... other backbones ...
        
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_predictor)
    
    return emb_predictor(audio_result.waveform.astype(np.float32))
    # ... existing normalization ...
```

**Note**: TensorFlow device placement is a hint and may be ignored. Validate CPU placement during testing by:
- Enabling TF device placement logging: `TF_CPP_MIN_LOG_LEVEL=0`
- Monitoring VRAM usage via nvidia-smi during CPU spill operations
- System tests that verify VRAM unchanged when prefer_gpu=False

---

### Phase 4: Workflow device passthrough

**Modify** `nomarr/workflows/processing/process_file_wf.py`:

Add prefer_gpu and cache_mode parameters:

```python
def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    db: Database,
    prefer_gpu: bool = True,
    cache_mode: str = "normal",  # NEW: "normal" or "sequential"
) -> ProcessingResultDict:
    """Main file processing workflow.
    
    Args:
        cache_mode: "normal" (Tier 0-1, use caching) or "sequential" (Tier 2-3, load/unload per file)
    """
    
    # ... existing setup ...
    
    # Pass prefer_gpu and cache_mode to embedding computation
    embeddings_result = compute_embeddings_for_backbone(
        params=emb_params,
        prefer_gpu=prefer_gpu,
        cache_mode=cache_mode,  # NEW
    )
    
    # ... rest of workflow ...
```
    
    # ... rest of workflow ...
```

---

### Phase 5: Configuration (absolute MB budgets)

Config uses absolute MB (not percentages). Budgets are MAXIMUM ML usage caps.

```yaml
processing:
  max_workers: 4
  resource_management:
    enabled: true
    vram_budget_mb: 12288  # 12 GiB max for ML
    ram_budget_mb: 16384   # 16 GiB max for ML
    ram_detection_mode: "auto"  # "auto" | "cgroup" | "host"
    cache_ttl_s: 1.0
```

**Budget logic**: `used_mb + estimate_mb <= budget_mb`

```python
@dataclass
class ResourceConfig:
    enabled: bool = True
    vram_budget_mb: int = 12288
    ram_budget_mb: int = 16384
    ram_detection_mode: str = "auto"
    cache_ttl_s: float = 1.0

@dataclass
class ProcessorConfig:
    max_workers: int = 4
    resource_management: ResourceConfig = field(default_factory=ResourceConfig)
```

---

## Performance Impact

Performance varies by execution tier:

**Tier 0: Fast Path** (Normal operation):
- Processing speed: 2-3s/file
- Multi-worker (4-8 workers typical)
- Full cache (2 backbones in VRAM, 16-24 heads in RAM)
- ~1-2ms overhead per file (cached resource checks, TTL=1s)
- Subprocess calls (nvidia-smi/psutil) throttled to once per second

**Tier 1: Reduced Cache**:
- Processing speed: 3-5s/file
- Reduced worker count (2-4 workers typical)
- Smaller cache (1 backbone in VRAM, 8-12 heads in RAM)
- Cache thrashing overhead, but no crashes

**Tier 2: Sequential GPU**:
- Processing speed: 5-10s/file
- Single worker (concurrency=1)
- No persistent cache (load/unload graphs per file)
- Graph loading overhead, but still GPU acceleration

**Tier 3: Sequential CPU** (CPU spill fallback):
- Processing speed: 30-60s/file (10-30x slower than GPU)
- Single worker (concurrency=1)
- Backbone on CPU (tf.device("/CPU:0") hint)
- Heads always on CPU (no change from other tiers)
- No crashes, files still process (eventually)

**Tier 4: Refuse**:
- Processing speed: N/A (no execution)
- Workers do not start (admission control spawns 0)
- OR workers transition to `health-dead` if tier degrades at runtime
- Clear error logs point to config.yaml changes (increase budgets or reduce model set)

**Resource exhaustion (runtime tier degradation)**:
- Worker may degrade from Tier 0/1 → Tier 2/3 if resources change mid-operation
- Worker transitions to `recovering` health state when both VRAM and RAM exhausted
- Claims released (files rediscoverable by other workers)
- Domain owner (WorkerSystemService) decides restart/backoff based on policy
- Worker suggests recovery duration via health contract (clamped by policy)

---

## Testing

**Unit tests (CI)**: 
- Mock nvidia-smi/psutil/cgroup files
- Test budget semantics (`used + estimate <= budget`)
- Test TTL caching
- Test health state transitions
- **Test tier selection logic**: Verify `select_execution_tier()` returns correct tier for various VRAM/RAM budget combinations
- **Test tier degradation**: Verify worker can downgrade from Tier 0→1→2→3 when resources change at runtime

**System tests (GPU host, not CI)**:
- Process files, monitor VRAM via nvidia-smi (verify backbone spill behavior)
- Verify CPU spill produces same results as GPU (within 1e-6 tolerance)
- Test health transitions: `healthy` → `recovering` → `healthy`
- Validate capacity probe lock (prevents duplicates), admission control calculation
- **Test tier transitions**: Start with Tier 0 budgets, reduce budgets via config reload, verify workers degrade to lower tiers
- **Test Tier 2/3 sequential execution**: Verify explicit cache eviction frees resources between files
- **Test Tier 4 refusal**: Set budgets below minimum, verify admission control spawns 0 workers and logs clear error

---

## Risks

**CPU too slow** (30-60s/file): Workers continue making progress (slow > crash). Users can disable.

**TensorFlow ignores tf.device()**: Validate via TF device logging (`TF_CPP_MIN_LOG_LEVEL=0`) and system tests.

**Container RAM incorrect**: Phase 1 implements cgroup v1/v2 detection with configurable `ram_detection_mode`.

**Capacity probe timeout**: Falls back to conservative `max_workers=1`. Manual recalibration available.

---

## Success Criteria

**Must have**:
- **GPU capability gate implemented**: `check_nvidia_gpu_capability()` runs once at startup, gates all GPU tiers
- **GPU capability vs telemetry distinction**: nvidia-smi used as capability signal (Docker gate), not just optional telemetry
- **NVIDIA CUDA scope enforced**: GPU tiers (0/1/2) require NVIDIA GPU; no AMD/Intel fallback hooks
- **CPU-only fallback**: When nvidia-smi fails, force Tier 3 (CPU-only) or Tier 4 (refuse)
- resource_monitor_comp is leaf probe (returns facts, accepts budgets from caller)
- Container RAM detection implemented (cgroup v1/v2 support in Phase 1)
- Workers check VRAM/RAM before each file (using TTL-cached queries, max 1 subprocess/sec)
- Budget semantics: `used_mb + estimate_mb <= budget_mb` (no percentage confusion)
- Single worker pool with per-worker backbone device selection (GPU vs CPU spill)
- Capacity probe with DB lock mechanism (prevents race conditions)
- Admission control calculates safe worker count (no slow serial startup)
- Workers transition to `recovering` health state via health contract (no hard-coded recovery windows)
- **5-tier execution model implemented** (Tier 0-4 with deterministic selection)
- **Tier-aware admission control**: Spawns appropriate worker count for selected tier
- **Tier-aware workers**: Accept `execution_tier` parameter, perform tier-specific behavior (cache modes, explicit eviction)
- **Tier 4 refusal**: Clear error logs when budgets insufficient, spawns 0 workers
- No OOM crashes during normal operation
- CPU spill validated via system tests on GPU host (VRAM behavior monitored)

**Should have**:
- Config options for budgets (absolute MB), RAM detection mode, TTL
- Clear error logs guide users to config.yaml fixes
- Capacity probe timeout with fallback (conservative max_workers=1)
- Manual recalibration support (delete estimate document)
- **Runtime tier degradation**: Workers can downgrade from Tier 0→1→2→3 when resources change mid-operation

---

## Future Work (Out of Scope)

**These items are intentionally deferred and NOT part of this refactor:**

1. **Check resources mid-job**: Current plan checks before each file only. Long files (60s+ tracks) could benefit from mid-job checks. TTL caching makes this cheap (<2ms), but adds complexity to worker loop.

2. **Dynamic worker count adjustment**: Current plan uses fixed worker count calculated at startup. Could auto-reduce worker count when resources become persistently exhausted (requires service layer changes + health monitor integration). Health contract already supports this via `recovering` → `health-dead` transitions; domain layer just needs to implement policy.

**Answered questions (removed from this section)**:

- ~~Cache both GPU and CPU predictors?~~ → Answered: Single-process backbone spill uses same cached predictor with tf.device() hint. No separate GPU/CPU cache keys needed.
- ~~RAM threshold too aggressive in containers?~~ → Answered: Phase 1 implements container RAM detection (cgroup v1/v2) with configurable `ram_detection_mode`.

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

## Tech Debt Created

**Intentional new artifacts (justified)**:

1. **ML capacity estimate documents** (`ml_capacity_estimates` collection)
   - Justification: Required for admission control to calculate safe worker count
   - Invalidated automatically when `model_set_hash` changes
   - Minimal storage (one document per model set configuration)

2. **Probe lock documents** (`ml_capacity_probe_locks` collection)
   - Justification: Prevents race condition (duplicate probes by concurrent workers)
   - Uses DB unique constraint (atomic, no distributed coordination)
   - Cleaned up after probe completes (`status: "complete"`)

3. **Container RAM detection logic** (cgroup v1/v2 file reading)
   - Justification: Required for correctness in Docker/k8s deployments
   - psutil reports host memory (incorrect in containers)
   - Configurable via `ram_detection_mode` (user can force host if needed)

4. **Resource check overhead** (1-2ms per file)
   - Justification: Prevents OOM crashes (small cost for stability)
   - Mitigated by TTL caching (max 1 subprocess/sec)
   - Negligible compared to ML inference time (2-60s per file)

5. **5-tier execution model** (Tier 0-4 with selection logic)
   - Justification: Enables graceful degradation instead of crash/refuse
   - Deterministic tier selection from probe metrics + budgets
   - Adds complexity (tier-specific worker behavior, cache modes)
   - Trade-off: System continues operating in degraded mode vs. complete failure

**Removed tech debt**:
- ~~Separate CPU worker pool~~ → Not needed (single-process backbone spill)
- ~~Device-specific cache keys~~ → Not needed (same predictor, tf.device() hint)
- ~~Per-call CUDA_VISIBLE_DEVICES toggling~~ → Not needed (unreliable, not used)
- ~~Hard-coded recovery windows~~ → Not needed (health contract handles it)

---

**Document created**: 2026-01-20  
**Last updated**: 2026-01-20 (added 5-tier execution model for graceful degradation)  
**Status**: Not implemented  
**Estimated time**: 4-5 weeks (increased from 3-4 weeks due to tier system complexity)  

**Files modified**: 6 (1 new, 5 modified)  
**Dependencies**: psutil>=5.9.0 (add to pyproject.toml, regenerate requirements.txt)  
**Deployment context**: Docker + nvidia-container-runtime + Python 3.12  
**Health contract**: Workers report `recovering` on resource exhaustion; domain owner decides restart/backoff/fail
