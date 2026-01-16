# Calibration System Refactor: DB-Histogram Percentile Computation

**Status:** Design Document - Alpha (no backward compatibility)  
**Goal:** Replace queue-based calibration with DB-histogram percentile computation to avoid OOM on large libraries

---

## Overview

Calibration in Nomarr normalizes ML model outputs (e.g., mood predictions) to a consistent 0-1 scale by computing percentile thresholds (p5/p95) across a library's music collection.

### Current Implementation

**File:** `nomarr/components/ml/ml_calibration_comp.py::generate_minmax_calibration()`

**Current behavior:**
1. Scans all library files
2. Reads `file_tags` with `nomarr_only=True` filter
3. Accumulates predictions per tag key in memory (e.g., `nom_mood_happy`, `nom_genre_rock`)
4. Computes p5/p95 percentiles from in-memory arrays
5. Writes sidecar JSON files (e.g., `effnet_mood_happy-calibration-v5.json`)

**Problems:**
- **Memory explosion**: Materializes all float predictions in memory (600k tracks × 50 heads = ~30M floats = ~120MB minimum, more with Python overhead)
- **Not scalable**: Large libraries (500k+ tracks) risk OOM
- **Sidecar-first design**: Filesystem is source of truth, not DB
- **Queue overhead**: Separate recalibration queue/worker system for applying calibrations

### Proposed Design

**DB-driven percentile computation via histogram counts per head.**

**Key principles:**
1. **DB is source of truth**: Percentile computation uses DB queries, not in-memory aggregation
2. **Histogram-based**: Compute bin counts via AQL GROUP BY, derive p5/p95 from cumulative distribution
3. **Memory-bounded**: Never materialize all float values; only bin counts (fixed size per head)
4. **Idempotent**: Generation can be re-run without partial state; no "included" markers needed
5. **Sidecars are export artifacts**: Generated from DB state, optional for distribution

**Benefits:**
- Scales to millions of tracks without OOM
- Simple, stateless generation (always derived from current DB state)
- DB-backed correctness (results computed from stored head outputs)
- Enables future online calibration distribution (import/export DB state)

---

## Data Model: DB as Source of Truth

### Core Collections

#### 1. `library_files` (existing, no calibration-generation changes)

```javascript
{
  _key: "file_123",
  path: "/music/song.mp3",
  library_id: "lib_001",
  
  // EXISTING: Track which calibration definition versions have been applied to tags
  // Used for tag recalibration detection, NOT for generation filtering
  calibration_hash: null  // hash of calibration definition (for tag recalibration)
}
```

**Purpose:**
- `calibration_hash`: String - which calibration definition versions have been applied to this file's tags (for recalibration detection only).
- **No `included_in_calibration` field**: Calibration generation queries all eligible file_tags; no per-file tracking needed.

---

#### 2. `calibration_state` (new collection)

**One document per head** (e.g., one for `effnet_mood_happy`, one for `musicnn_genre`, etc.)

**Identity strategy:** `_key = "{model_key}:{head_name}"` (stable). When calibration definition changes (version bump), overwrite existing document. History collection captures drift over time.

```javascript
{
  _key: "effnet-discogs-effnet-1:mood_happy",  // Stable key: model_key:head_name
  model_key: "effnet-discogs-effnet-1",
  head_name: "mood_happy",
  
  // Identity
  calibration_def_hash: "abc123...",  // MD5 of (model_key, head_name, version) - stored for reference
  version: 5,  // calibration version from head metadata
  
  // Histogram specification (uniform binning strategy)
  histogram: {
    lo: 0.0,        // lower bound of calibrated range
    hi: 1.0,        // upper bound of calibrated range
    bins: 10000,    // number of uniform bins (fixed: 10,000 per head)
    bin_width: 0.0001  // (hi - lo) / bins = 0.0001
  },
  
  // Derived calibration results (computed from histogram counts via AQL)
  p5: 0.123,   // 5th percentile
  p95: 0.876,  // 95th percentile
  n: 12345,    // total number of values included in histogram
  
  // Out-of-range tracking (when clamp_policy == "track_overflow")
  underflow_count: 45,   // values < lo
  overflow_count: 23,    // values > hi
  
  // Metadata
  created_at: 1234567890,
  updated_at: 1234567899,
  last_computation_at: 1234567899  // when p5/p95 last computed
}

// _key is model_key:head_name (stable identity)
// No additional unique index needed - _key uniqueness is sufficient
```

**Purpose:**
- Single document per calibration definition
- `histogram` defines uniform binning strategy (10,000 bins per head)
- `p5`/`p95` are **derived results** computed via sparse AQL histogram query
- `underflow_count`/`overflow_count` track out-of-range values for diagnostics
- **No aggregate array**: Results computed on-demand from `file_tags` collection

**Histogram specification:**
- **Uniform bins**: 10,000 bins per head (fixed resolution)
- **Bin width**: 0.0001 (sufficient to make binning error negligible relative to model noise)
- **Calibrated range**: `[0.0, 1.0]` (typical for normalized model outputs)
- **Sparse results**: Only bins with non-zero counts are returned by DB query
- **Clamp policy**: Values outside [lo, hi] are counted separately as underflow/overflow

---

#### 3. `calibration_history` (new collection, optional)

**Append-only snapshots** for tracking calibration drift over time.

```javascript
{
  _key: "effnet_mood_happy_20260116_001",
  calibration_key: "effnet_mood_happy",  // FK to calibration_state
  
  snapshot_at: 1234567890,
  
  // Snapshot of derived calibration
  p5: 0.123,
  p95: 0.876,
  n: 12345,
  underflow_count: 45,
  overflow_count: 23,
  
  // Drift metrics (compare to previous snapshot)
  p5_delta: 0.002,
  p95_delta: -0.001,
  n_delta: 123
}
```

**Purpose:**
- Track calibration stability over time
- Detect drift as library content changes
- Not required for correctness (derived from `file_tags`)

---

### Sidecars: Export Artifacts Only

**Sidecar files** (e.g., `effnet_mood_happy-calibration-v5.json`) are **generated from DB state**, not the source of truth.

**Export format:**
```json
{
  "model": "effnet-discogs-effnet-1",
  "head": "mood_happy",
  "version": 5,
  "p5": 0.123,
  "p95": 0.876,
  "n": 12345,
  "underflow_count": 45,
  "overflow_count": 23,
  "generated_at": "2026-01-16T12:00:00Z"
}
```

**Use cases:**
1. **Export**: Generate sidecar from DB for distribution/backup
2. **Import**: Bootstrap DB from downloaded calibration (future: online distribution)
3. **Cache**: Local filesystem cache to avoid DB reads during processing

**Critical:**
- Sidecar write failures **must not** affect DB correctness
- DB always wins conflicts (import is one-time hydration, not sync)

---

## Histogram Query Algorithm

**Critical requirement:** Head outputs must be stored as **numeric fields** (float/double) in `file_tags` for histogram queries to work correctly. String representations will cause AQL type errors or expensive conversions.

### High-Level Flow

**One query per head** (not 10,000 queries). Query returns sparse histogram: only bins with non-zero counts.

```
For each head (model_key + head_name):
  1. Run single AQL histogram query:
     - **Eligibility filter**: file_tags with matching model_key, head_name, nomarr_only=true, IS_NUMBER(value)
       (only files that have a numeric ML output for this specific head)
     - **Compute integer bin index**: bin_idx = FLOOR((value - lo) / bin_width)
     - **GROUP BY bin index**: one row per unique bin that has data
     - **Aggregate counts**: count per bin, plus total n, underflow_count, overflow_count
     - **Return sparse histogram**: {min_val: float, count: int}[] where min_val = lo + (bin_idx * bin_width)
       Only bins with count > 0 are returned (typically hundreds to thousands of bins, not all 10,000)
  
  2. Derive p5/p95 from sparse cumulative distribution (workflow code):
     - Sort sparse bins by min_val
     - Accumulate counts until cumulative ≥ p * n
     - Return min_val as percentile estimate (approximation error bounded by bin_width = 0.0001)
  
  3. Upsert calibration_state document with:
     - p5, p95, n, underflow_count, overflow_count
     - updated_at, last_computation_at
  
  4. Optionally: create calibration_history snapshot
  
  5. Optionally: export sidecar file from calibration_state
```

**Key invariants:**
- **Idempotent**: No partial state; can re-run anytime
- **Memory-bounded**: No raw float arrays; sparse bins only (≤10,000 rows per head)
- **DB-derived**: Results computed from current `file_tags` contents

### AQL Histogram Query

**Single query per head** returning sparse histogram (10,000 uniform bins, only non-zero bins returned).

**Histogram parameters:** `lo = 0.0`, `hi = 1.0`, `bins = 10000`, `bin_width = 0.0001`

```javascript
// Single query: compute sparse histogram + overflow stats
FOR ft IN file_tags
  FILTER ft.model_key == "effnet-discogs-effnet-1"
  FILTER ft.head_name == "mood_happy"
  FILTER ft.nomarr_only == true    // Only ML-generated outputs
  FILTER IS_NUMBER(ft.value)        // Eligibility: numeric value required
  
  // Histogram parameters (from calibration_state or known globally)
  LET lo = 0.0
  LET hi = 1.0
  LET bin_width = 0.0001  // Fixed: (hi - lo) / 10000
  
  LET value = ft.value
  
  // Compute integer bin index (avoid floating-point drift)
  LET bin_idx_raw = FLOOR((value - lo) / bin_width)
  LET bin_idx = MIN(MAX(bin_idx_raw, 0), 9999)  // Clamp to [0, 9999]
  
  // Out-of-range flags
  LET is_underflow = value < lo
  LET is_overflow = value > hi
  
  // Group by integer bin index only (sparse: only bins with data)
  COLLECT bin_index = bin_idx
  AGGREGATE 
    count = COUNT(1),
    underflow_count = SUM(is_underflow ? 1 : 0),
    overflow_count = SUM(is_overflow ? 1 : 0)
  
  // Derive min_val from integer bin index (stable floating-point)
  LET min_val = lo + (bin_index * bin_width)
  
  RETURN {
    min_val: min_val,       // Lower bound of bin
    count: count,           // Number of values in this bin
    underflow_count: underflow_count,
    overflow_count: overflow_count
  }
```

**Query output (sparse histogram):**
```javascript
[
  {min_val: 0.0234, count: 156, underflow_count: 0, overflow_count: 0},
  {min_val: 0.0456, count: 289, underflow_count: 0, overflow_count: 0},
  {min_val: 0.0789, count: 412, underflow_count: 0, overflow_count: 0},
  ...
  {min_val: 0.9876, count: 203, underflow_count: 0, overflow_count: 0}
]
// Total rows: ≤10,000 (typically hundreds to thousands)
// Only bins with count > 0 are returned
// underflow_count/overflow_count are per-bin aggregates (sum to get totals)
```

**Post-query aggregation (in workflow code):**
```python
# Sum overflow stats across all bins
total_n = sum(row["count"] for row in result)
underflow_total = sum(row["underflow_count"] for row in result)
overflow_total = sum(row["overflow_count"] for row in result)
```

**Critical semantics:**
- **Integer bin index**: Bins computed via `FLOOR((value - lo) / bin_width)` to avoid drift
- **min_val derivation**: `min_val = lo + (bin_idx * bin_width)` ensures stable floating-point
- **Sparse result**: Only bins with `count > 0` returned (not dense 10,000-row array)
- **Upper bound**: Implicit `max_val = min_val + bin_width` (not returned)
```

### Percentile Derivation (Workflow Code)

**Extract percentiles from sparse histogram via cumulative distribution.**

```python
def derive_percentiles_from_sparse_histogram(
    sparse_bins: list[dict[str, Any]],
    lo: float = 0.0,
    hi: float = 1.0,
    bin_width: float = 0.0001,
    p5_target: float = 0.05,
    p95_target: float = 0.95
) -> dict[str, Any]:
    """
    Derive p5/p95 from sparse histogram (only non-zero bins).
    
    Args:
        sparse_bins: AQL query result - list of {min_val: float, count: int, underflow_count: int, overflow_count: int}
        lo: Histogram lower bound (0.0)
        hi: Histogram upper bound (1.0)
        bin_width: Uniform bin width (0.0001)
        p5_target: 5th percentile threshold (0.05)
        p95_target: 95th percentile threshold (0.95)
    
    Returns:
        {p5: float, p95: float, n: int, underflow_count: int, overflow_count: int}
        
    Note:
        Approximation error bounded by bin_width.
        Exact quantiles are not a goal; bin-level precision is sufficient.
    """
    # Sort sparse bins by min_val (already sorted if query used ORDER BY)
    sorted_bins = sorted(sparse_bins, key=lambda x: x["min_val"])
    
    # Aggregate overflow stats
    total_n = sum(b["count"] for b in sorted_bins)
    underflow_count = sum(b["underflow_count"] for b in sorted_bins)
    overflow_count = sum(b["overflow_count"] for b in sorted_bins)
    
    # Build cumulative distribution (start with underflow as < lo)
    cumsum = underflow_count
    p5_value = None
    p95_value = None
    
    for bin_data in sorted_bins:
        min_val = bin_data["min_val"]
        count = bin_data["count"]
        cumsum += count
        
        # p5: first bin where cumsum >= 5% of total
        if p5_value is None and cumsum >= total_n * p5_target:
            p5_value = min_val  # Lower bound of bin
        
        # p95: first bin where cumsum >= 95% of total
        if p95_value is None and cumsum >= total_n * p95_target:
            p95_value = min_val  # Lower bound of bin
            break  # Can stop once p95 found
    
    # Handle edge cases (all values in tails)
    if p5_value is None:
        p5_value = lo  # All values below 5% threshold
    if p95_value is None:
        p95_value = hi  # All values above 95% threshold
    
    return {
        "p5": p5_value,
        "p95": p95_value,
        "n": total_n,
        "underflow_count": underflow_count,
        "overflow_count": overflow_count
    }
```

### Out-of-Range Handling

**Head outputs outside calibrated range [0.0, 1.0]:**

**Clamp policy:**

Values outside [lo, hi] are **not clamped** during binning. Instead:
- **In-range values** (0.0 ≤ value ≤ 1.0): Binned normally via integer bin index
- **Underflow values** (value < 0.0): Counted separately, not binned
- **Overflow values** (value > 1.0): Counted separately, not binned

Percentiles (p5/p95) are computed from in-range bins only. Underflow values are logically placed below p5 in cumulative distribution.

**Why track overflow:**
- **Model drift detection**: Sudden increase in overflow_count indicates model output shift
- **Range validation**: Confirms [0.0, 1.0] covers actual data distribution
- **Debugging**: Helps diagnose model issues (e.g., producing values > 1.0)
- **Histogram adjustment**: If overflow > 5%, consider expanding range

**Example diagnostic:**
```python
if overflow_count / n > 0.05:
    logger.warning(f"High overflow for {head_name}: {overflow_count}/{n} ({overflow_count/n*100:.1f}%)")
    # Consider expanding histogram range or investigating model outputs
```

---

## Memory & Performance Guarantees

**Why histogram-based calibration scales to large libraries:**

### Memory Bounds

**No raw float arrays materialized:**
- Old approach: 600k tracks × 50 heads × 8 bytes = 240 MB raw + ~1 GB Python overhead
- New approach: ≤10,000 sparse bins per head × 16 bytes = ≤160 KB per head
- **50 heads × 160 KB = ~8 MB total** (vs. ~1 GB old)
- **Memory reduction: ~100x**

**Sparse histogram results:**
- Typical: 1,000-3,000 non-zero bins per head (not 10,000)
- Worst case: 10,000 bins if data uniformly distributed
- Memory usage independent of library size (depends only on data distribution)

**Per-head processing:**
- Heads processed sequentially (one query at a time)
- Python memory usage: sparse bins + cumulative sum (~1 MB peak per head)
- No cross-head aggregation required

### Query Performance

**Single GROUP BY per head:**
- AQL scans `file_tags` once per head
- GROUP BY integer bin index (efficient hash grouping)
- Typical: 500k documents, 100-500ms per head (with indexes)
- 50 heads × 300ms avg = **15 seconds total**

**Index requirements:**
```javascript
// Composite index for histogram queries
db.file_tags.ensureIndex({
  type: "persistent",
  fields: ["model_key", "head_name", "nomarr_only"],
  name: "idx_file_tags_histogram"
});
```

**Bottleneck:**
- DB grouping dominates (not Python memory)
- Scales to millions of tracks without OOM
- Query cost amortized across all percentile computations

---

## Idempotency & Crash Behavior

**Generation is fully idempotent:**

1. **No partial state**: Query always runs against current `file_tags` contents
2. **Re-run safe**: Can regenerate calibration anytime without side effects
3. **Crash recovery**: Just re-run generation workflow; no cleanup needed
4. **Stateless**: Each generation computes from scratch; results are deterministic from DB contents

**When to regenerate calibration:**
1. After adding new files to library (and tagging them)
2. After updating model versions
3. To refresh sidecar files
4. On-demand via admin interface

---

## Progress Reporting: Per-Head Completion

**No file-level progress tracking.** Progress is measured by heads completed.

```python
def get_calibration_progress(db: Database, library_id: str) -> dict[str, Any]:
    """
    Get calibration generation progress.
    
    Returns:
        {
          "total_heads": 50,           # heads discovered from models
          "completed_heads": 35,        # heads with up-to-date calibration_state
          "remaining_heads": 15,
          "last_updated": 1234567890    # most recent calibration_state.updated_at
        }
    """
    # Discover all heads from models
    heads = discover_heads(models_dir)
    total_heads = len(heads)
    
    # Count heads with recent calibration_state
    recent_threshold = now_ms() - (24 * 60 * 60 * 1000)  # 24 hours
    completed = db.aql.execute("""
        RETURN COUNT(
            FOR c IN calibration_state
                FILTER c.updated_at >= @threshold
                RETURN 1
        )
    """, bind_vars={"threshold": recent_threshold}).next()
    
    # Most recent calibration timestamp
    last_updated = db.aql.execute("""
        FOR c IN calibration_state
            SORT c.updated_at DESC
            LIMIT 1
            RETURN c.updated_at
    """).next()
    
    return {
        "total_heads": total_heads,
        "completed_heads": completed,
        "remaining_heads": total_heads - completed,
        "last_updated": last_updated
    }
```

**No distributed state tracking:**
- Each service process computes progress independently
- No "is generation running" flag (check timestamps + thread state)
- Thread execution is service-local implementation detail

---

## Execution Model

### Service Layer

```python
import threading
from typing import Callable

class CalibrationService:
    def __init__(self, db_factory: Callable[[], Database], config: CalibrationConfig):
        self._db_factory = db_factory
        self.config = config
        self._generation_thread: threading.Thread | None = None
    
    def start_calibration_generation(self, library_id: str) -> None:
        """
        Start calibration generation in background thread.
        
        Process:
        1. Discover all heads from models
        2. For each head:
           - Run histogram query via AQL
           - Derive p5/p95 from bin counts
           - Upsert calibration_state
           - Optionally: create history snapshot
        3. Export sidecars (optional, non-blocking)
        """
        if self._generation_thread and self._generation_thread.is_alive():
            raise RuntimeError("Calibration generation already in progress")
        
        self._generation_thread = threading.Thread(
            target=self._run_generation,
            args=(library_id,),
            daemon=True,
            name=f"calibration-gen-{library_id}"
        )
        self._generation_thread.start()
    
    def _run_generation(self, library_id: str) -> None:
        """Background thread: histogram-based calibration generation."""
        db = self._db_factory()  # Fresh connection
        
        # Discover heads
        heads = discover_heads(self.config.models_dir)
        logger.info(f"Generating calibration for {len(heads)} heads")
        
        for head_info in heads:
            try:
                # Get or create calibration_state with histogram spec
                calib_key = f"{head_info.model_key}_{head_info.head_name}"
                histogram_spec = self._get_or_create_histogram_spec(db, calib_key, head_info)
                
                # Run histogram query
                bin_counts = self._query_histogram(db, head_info, histogram_spec)
                
                # Derive percentiles
                results = derive_percentiles_from_histogram(bin_counts, histogram_spec)
                
                # Upsert calibration_state
                db.calibration_state.upsert(calib_key, {
                    "model_key": head_info.model_key,
                    "head_name": head_info.head_name,
                    "calibration_def_hash": compute_calibration_def_hash(head_info),
                    "version": head_info.calibration_version,
                    "histogram": histogram_spec,
                    "p5": results["p5"],
                    "p95": results["p95"],
                    "n": results["n"],
                    "underflow_count": results["underflow_count"],
                    "overflow_count": results["overflow_count"],
                    "updated_at": now_ms(),
                    "last_computation_at": now_ms()
                })
                
                logger.info(f"Generated calibration for {calib_key}: p5={results['p5']:.4f}, p95={results['p95']:.4f}, n={results['n']}")
                
            except Exception as e:
                logger.error(f"Failed to generate calibration for {head_info.head_name}: {e}")
                continue
        
        # Final: export sidecars (non-critical)
        try:
            self._export_sidecars(db)
        except Exception as e:
            logger.warning(f"Sidecar export failed (non-critical): {e}")
    
    def _query_histogram(
        self, 
        db: Database, 
        head_info: HeadInfo, 
        histogram_spec: dict[str, Any]
    ) -> list[dict[str, int]]:
        """
        Run AQL histogram query for given head.
        
        Returns list of {bin: int, count: int, underflow: bool, overflow: bool}
        """
        query = """
            LET lo = @lo
            LET hi = @hi
            LET bins = @bins
            
            FOR ft IN file_tags
              FILTER ft.model_key == @model_key
              FILTER ft.head_name == @head_name
              FILTER ft.nomarr_only == true
              
              LET value = ft.value
              LET bin_raw = FLOOR((value - lo) / (hi - lo) * bins)
              LET bin = MIN(MAX(bin_raw, 0), bins - 1)
              LET is_underflow = value < lo
              LET is_overflow = value > hi
              
              COLLECT 
                bin_index = bin,
                underflow = is_underflow,
                overflow = is_overflow
              AGGREGATE count = COUNT(1)
              
              RETURN {
                bin: bin_index,
                count: count,
                underflow: underflow,
                overflow: overflow
              }
        """
        
        cursor = db.aql.execute(query, bind_vars={
            "model_key": head_info.model_key,
            "head_name": head_info.head_name,
            "lo": histogram_spec["lo"],
            "hi": histogram_spec["hi"],
            "bins": histogram_spec["bins"]
        })
        
        return list(cursor)
```

**Key points:**
- Thread is **service-local** (not distributed system state)
- Progress queries work across processes (stateless AQL)
- Idempotent: can re-run generation without side effects

---

## Removal of Old System

**The following are REMOVED (direct replacement, no migration):**

**Sequencing note:** Remove old collections and modules **after** all call sites have migrated to new calibration system. Do not delete collections/code before migration is complete to avoid breaking active code paths.

### Deleted Files
- `nomarr/persistence/database/calibration_queue_aql.py` - Queue operations
- `nomarr/services/infrastructure/workers/recalibration.py` - Recalibration worker (if exists)
- All calibration queue/worker references

### Deleted Collections
```javascript
// Drop in ArangoDB
db._drop("calibration_queue");
db._drop("calibration_runs");  // Old per-run tracking
```

### New Collections
```javascript
// Create calibration_state
db._create("calibration_state");
// No additional indexes needed - _key is model_key:head_name (stable identity)

// Create calibration_history (optional)
db._create("calibration_history");
```

---

## Tag Recalibration (Applying Calibrations)

**Separate concern from generation.**

Calibration generation computes p5/p95 via histogram query and stores in `calibration_state`.
Tag recalibration applies those p5/p95 values to normalize raw predictions.

**Detection:** `calibration_hash` mismatch
```javascript
// Compute expected hash from current calibration definitions
expected_hash = MD5("effnet_mood_happy:v5|musicnn_genre:v3|...")

// Find files needing recalibration
FOR f IN library_files
    FILTER f.calibration_hash == null 
        OR f.calibration_hash != @expected_hash
    RETURN f
```

**Process:**
1. Load current calibrations from `calibration_state` (p5/p95 computed via histogram method)
2. Read file's raw predictions from `file_tags`
3. Apply normalization: `(value - p5) / (p95 - p5)`
4. Update normalized tags in `file_tags`
5. Update `f.calibration_hash = expected_hash`

**Not part of generation** - separate workflow, direct iteration (no queue).

**Workflow signature:**
```python
def recalibrate_library_direct_wf(
    db: Database,
    library_id: str,
    expected_hash: str,
    models_dir: str,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool,
) -> dict[str, Any]:
    """
    Recalibrate all files needing recalibration in library.
    
    Loads p5/p95 from calibration_state (computed via histogram query).
    Applies normalization to raw predictions in file_tags.
    """
    # Load calibrations from calibration_state
    calibrations = db.calibration_state.get_all()
    calib_map = {c["_key"]: c for c in calibrations}
    
    # Get files needing recalibration
    files = db.library_files.get_files_needing_recalibration(library_id, expected_hash)
    
    for file_doc in files:
        try:
            # Apply calibrations from calibration_state
            apply_calibrations_to_file(db, file_doc["_key"], calib_map, namespace)
            
            # Update calibration hash
            db.library_files.update_calibration_hash(file_doc["_key"], expected_hash)
            
        except Exception as e:
            logger.error(f"Recalibration failed for {file_doc['path']}: {e}")
            continue
```

---

## Future: Online Calibration Distribution

### Export Calibration Package

```python
def export_calibration_package(db: Database, output_dir: str) -> None:
    """
    Export all calibrations as distributable package.
    
    Creates:
      - calibrations.json (metadata + all p5/p95 values + histogram specs)
      - Individual sidecar files (backward compat)
    """
    calibrations = db.calibration_state.get_all()
    
    package = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "method": "histogram",
        "calibrations": [
            {
                "key": c["_key"],
                "model": c["model_key"],
                "head": c["head_name"],
                "version": c["version"],
                "p5": c["p5"],
                "p95": c["p95"],
                "n": c["n"],
                "underflow_count": c["underflow_count"],
                "overflow_count": c["overflow_count"],
                "histogram": c["histogram"]
            }
            for c in calibrations
        ]
    }
    
    # Write package
    with open(f"{output_dir}/calibrations.json", "w") as f:
        json.dump(package, f, indent=2)
    
    # Write individual sidecars
    for c in calibrations:
        write_sidecar(output_dir, c)
```

### Import Calibration Package

```python
def import_calibration_package(db: Database, package_path: str) -> None:
    """
    Import calibrations from package (one-time bootstrap).
    
    WARNING: Overwrites existing calibration state.
    Use for fresh installs or when adopting community calibrations.
    """
    with open(package_path) as f:
        package = json.load(f)
    
    for calib in package["calibrations"]:
        db.calibration_state.upsert(calib["key"], {
            "model_key": calib["model"],
            "head_name": calib["head"],
            "version": calib["version"],
            "calibration_def_hash": compute_calibration_def_hash_from_calib(calib),
            "histogram": calib["histogram"],
            "p5": calib["p5"],
            "p95": calib["p95"],
            "n": calib["n"],
            "underflow_count": calib.get("underflow_count", 0),
            "overflow_count": calib.get("overflow_count", 0),
            "imported": True,
            "imported_at": now_ms(),
            "updated_at": now_ms(),
            "last_computation_at": now_ms()
        })
```

**Use case:** Download calibrations trained on large community libraries, use as starting point for local library.

---

## Implementation Phases

### Phase 1: Data Model
- Create `calibration_state` collection with histogram spec
- Create `calibration_history` collection (optional)
- Create indexes
- Drop `calibration_queue`, `calibration_runs`

```javascript
// ArangoDB setup
db._create("calibration_state");
db.calibration_state.ensureIndex({
  type: "persistent",
  fields: ["calibration_def_hash"],
  name: "idx_calibration_def_hash",
  unique: true
});

db._create("calibration_history");

db._drop("calibration_queue");
db._drop("calibration_runs");
```

### Phase 2: Persistence Layer
- `calibration_state_aql.py` (new):
  - `query_histogram(model_key, head_name, histogram_spec)`
  - `upsert_calibration(calib_key, data)`
  - `get_calibration(calib_key)`
  - `get_all_calibrations()`
- No changes to `library_files_aql.py` for generation (only recalibration uses `calibration_hash`)

### Phase 3: Component Layer
- `ml_calibration_comp.py`:
  - Refactor `generate_minmax_calibration()` to histogram model
  - Add `derive_percentiles_from_histogram(bin_counts, histogram_spec)`
  - Add `compute_calibration_def_hash()` (from model/head metadata)
  - Add default histogram specs per head type

### Phase 4: Service Layer
- `calibration_svc.py`:
  - Replace queue/worker logic with threading.Thread pattern
  - Implement `start_calibration_generation()` (histogram-based)
  - Implement `get_generation_progress()` (per-head completion)

### Phase 5: Remove Old Code
- Delete calibration queue files
- Remove worker references
- Update interfaces to use new service methods

### Phase 6: Export/Import
- Add sidecar generation from `calibration_state`
- Add package import/export for distribution

---

## Memory & Performance Analysis

### Old Approach (In-Memory Accumulation)
```
600,000 tracks × 50 heads × 8 bytes/float = 240 MB
+ Python overhead (~3x) = 720 MB
+ Temporary arrays, sorting = 1-2 GB peak
```

### New Approach (Histogram Query)
```
Per-head histogram: 1000 bins × 8 bytes = 8 KB
50 heads × 8 KB = 400 KB
+ Python overhead = ~2 MB total
+ AQL query result transfer = depends on bin count, typically < 10 KB/head
```

**Memory reduction: ~1000x**

**Query performance:**
- AQL histogram query: O(N) scan of `file_tags` with GROUP BY
- Typical: 600k documents, 50ms-500ms per head depending on indexes
- Total generation time: 50 heads × 200ms avg = 10 seconds
- Acceptable for background thread, scales to millions of tracks

**Index recommendations:**
```javascript
// Composite index for histogram queries
db.file_tags.ensureIndex({
  type: "persistent",
  fields: ["model_key", "head_name", "nomarr_only"],
  name: "idx_file_tags_histogram"
});
```

---

## Crash Recovery & Edge Cases

### Crash During Generation

**Scenario:** Process crashes mid-generation

**Behavior:**
- Some heads have updated `calibration_state`, others don't
- Next generation: Re-runs histogram query for all heads (idempotent)
- No partial state, no cleanup needed

**Guarantee:** Generation is fully idempotent.

### Histogram Range Misconfiguration

**Scenario:** Actual head outputs exceed histogram [lo, hi]

**Detection:**
- `overflow_count` / `n` ratio indicates percentage of out-of-range values
- If > 5%, consider adjusting histogram spec

**Response:**
1. Update histogram spec in `calibration_state` (wider lo/hi or more bins)
2. Re-run generation
3. Check overflow_count again

**Example:**
```javascript
// Adjust histogram for head with high overflow (e.g., 10% of values > 1.0)
db.calibration_state.update("effnet-discogs-effnet-1:mood_happy", {
  histogram: {
    lo: -0.1,     // expanded from 0.0
    hi: 1.1,      // expanded from 1.0
    bins: 10000,
    bin_width: 0.00012  // (1.1 - (-0.1)) / 10000
  }
});

// Re-run calibration computation
calibration_service.start_calibration_generation(library_id)
```

### Sidecar Write Failure

**Scenario:** Filesystem full, permission denied

**Behavior:**
- DB upsert commits successfully
- Sidecar export logs warning
- Calibration continues (DB is truth)
- Regenerate sidecar later: `export_calibration_package()`

**No correctness impact.**

---

## Summary

**Old System (Removed):**
- In-memory accumulation of all predictions (~1 GB for 600k tracks)
- OOM risk on large libraries (500k+ tracks)
- Sidecar files as source of truth
- Queue/worker for recalibration

**New System (Alpha Replacement):**
- **Sparse uniform histogram** (10,000 bins per head, only non-zero bins returned)
- **One query per head** (AQL GROUP BY integer bin index)
- **Memory-bounded** (~8 MB for 50 heads vs. ~1 GB old)
- **DB as source of truth** (`calibration_state` collection)
- **Stateless computation** (always derived from current file_tags)
- **Idempotent** (no partial state, can re-run anytime)
- **Per-head progress** (completion tracked by head)
- **Sidecars as export artifacts**

**Key invariants:**
- Calibration percentiles (p5/p95) computed from DB histogram counts
- Generation queries all eligible file_tags; no per-file inclusion tracking
- Histogram queries return sparse results: `{min_val: float, count: int}[]`
- Bin width = 0.0001 (binning error negligible relative to model noise)

**Benefits:**
- ~100x memory reduction (1 GB → 8 MB)
- Scales to millions of tracks without OOM
- Simpler architecture (no queue/workers, stateless computation)
- DB-backed correctness (results derived from stored head outputs)
- Foundation for community calibration sharing
