# Storage Architecture & Cache Rules

Storage boundaries, cache layout, module ownership, and known DB violations.

---

## Storage Boundary

**DuckDB stores metrics and scalar summaries only.** Raw vectors, pooled embedding tensors, and head activation streams are **never** written to DuckDB. They live on the filesystem.

**Existence check = file/directory exists.** Never query the DB to check whether vector or head data exists. Use `Path(...).exists()`.

**One file per song.** Do not aggregate multiple songs into a single file. Load multiple files when needed.

---

## Canonical Cache Layout

`{OUTPUT_ROOT}/cache/{backbone}/{strategy}/{threshold}/{song_id}`

| Data type | `{strategy}` | `{threshold}` | `{song_id}` |
|-----------|-------------|---------------|-------------|
| Flat pooled vec | `{pool_strategy}` (e.g. `mean`) | `flat` | `{id}.npy` |
| Flat PTC head act | `heads/{head_name}/{pool_strategy}` | `ptc` | `{id}.npy` |
| Flat CTP head act | `heads/{head_name}/{pool_strategy}` | `ctp` | `{id}.npy` |
| Binned PTC vec | `{bin_mode}` (e.g. `temporal_global`) | `{thresh:.3f}` | `{id}/` (directory) |
| Binned CTP head act | `heads/{head_name}/{bin_mode}` | `{thresh:.3f}` | `{id}.npy` |

---

## Module Owners

| Data | Owner | Path Pattern |
|------|-------|-------------|
| Flat pooled vecs | `strategy_flat._cache` | `cache/{backbone}/{pool_strategy}/flat/{id}.npy` |
| Flat head acts | `cache.flat_heads` | `cache/{backbone}/heads/{head}/{strat}/{pathway}/{id}.npy` |
| Binned PTC vecs | `strategy_binned._cache` | Legacy `binned_ptc_cache/`; migration pending |
| Binned CTP acts | DB violation | `binned_classify_ctp` table; migration to `cache/` pending |

---

## Known DB Violations (do not add more)

- `binned_classify_ctp` — stores CTP per-bin activations as BLOBs; pending migration to filesystem
- `binned_ctp_vecs` — stores CTP per-bin vectors as BLOBs; pending migration to filesystem

**Target migration:** `cache/{backbone}/heads/{head_name}/{bin_mode}/{threshold:.3f}/{song_id}.npy`

---

## Legacy Paths

`flat_cache/` is the old flat-vec root. Run `strategy_flat._cache.migrate_flat_cache()` to move existing data to `cache/{backbone}/{strategy}/flat/`. Code reads both paths transparently during transition.

---

## Cache Rules — Per Type

### Flat Vecs

`{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy`
- Not in DuckDB. Never add a DB write for pooled vectors.
- `save_pooled` always casts to `float32`.
- `is_done` may delete corrupt files as a side effect.
- Legacy root `flat_cache/` is still supported for reads; call `migrate_flat_cache()` to upgrade.

### Flat Head Acts

`{OUTPUT_ROOT}/cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy`
- Not in DuckDB. `head_results` table is effectively dead — shims in `db/flat.py` redirect to `cache.flat_heads`.
- Done signal: both `ptc/` and `ctp/` files exist → `cache.flat_heads.is_done()`.

### Binned PTC

`{OUTPUT_ROOT}/binned_ptc_cache/{cache_semantics_tag()}/{backbone}/{bin_mode}/{threshold:.3f}/{song_id}.npz`
- Bump `cache_semantics_tag()` when algorithm semantics change.
- `medoid` is excluded from `AGG_METHODS` — handled by `_build_medoid_payload`, not `_BIN_POOL_STRATEGIES`.
- `load_norm_pair` returns unit-normalised tensors. Do not pass raw tensors where unit tensors are expected.

### Binned CTP (DB violation — pending migration)

- `binned_classify_ctp` and `binned_ctp_vecs` tables in DuckDB.
- These are known violations of the storage boundary rule.
- Do not add more code that writes vectors or activations to these tables.
