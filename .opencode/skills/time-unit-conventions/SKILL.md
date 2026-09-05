---
name: time-unit-conventions
description: Nomarr timestamp unit conventions — wall-clock timestamps persisted to PostgreSQL (created_at, updated_at, registered_at, scanned_at, heartbeat, finished_at) are INTEGER MILLISECONDS since epoch, produced via now_ms().value or int(time.time()*1000). Load when touching DB timestamps, adding a timestamp column, comparing timestamps, or writing data-migration SQL for timestamp columns.
---

# Time Unit Conventions

## Mental Model

Nomarr stores wall-clock timestamps as **integer milliseconds since epoch** in BigInteger columns. Storage is unit-agnostic (BigInteger); the ms unit convention is enforced purely in code. `nomarr/helpers/time_helper.py` is the canonical time module: `now_ms()`/`now_s()` = wall clock, `internal_ms()`/`internal_s()` = monotonic. Ruff bans raw `time.time`/`datetime.now` outside `time_helper.py`. Monotonic values must NEVER be persisted (absolute value is meaningless); wall-clock ms is the only acceptable DB timestamp unit. Conversion helpers: `s_to_ms(Seconds)` -> Milliseconds.

## Coverage

**Documented:** The integer-ms convention; canonical wall-clock entry points; reference implementations; the wire format (backend divides ms by 1000 before emitting); the historical ML-repo seconds bug and its fix.

**Not yet documented:** Whether every frontend consumer that displays an ML/calibration timestamp divides by 1000.

**Last extended:** 2026-09-04

## Key Findings

### Canonical convention: persisting wall-clock timestamps = milliseconds
- **Location:** `nomarr/helpers/time_helper.py` — `now_ms()` (wall clock, `time.time_ns() // NS_PER_MS`), `now_s()`, monotonic `internal_ms()`/`internal_s()`. Module docstring (lines 1-23): "Use wall-clock time for: Database timestamps, Heartbeats."
- **Why it matters:** The canonical call for ANY DB timestamp is `now_ms().value`. A seconds-source must be converted (`s_to_ms()` or `* 1000`).
- Wire format proof: `nomarr/interfaces/api/types/library_types.py` formats persisted ints as `datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()` — i.e. the DB/wire unit is ms and the API layer divides by 1000.

### Reference implementations that write ms
- `nomarr/helpers/time_helper.py` `now_ms()` — canonical wall-clock ms producer.
- ML persistence repos (now all ms): the six data repos `nomarr/persistence/database/ml_inference_repo.py`, `nomarr/persistence/database/model_repo.py`, `nomarr/persistence/database/vector_repo.py`, `nomarr/persistence/database/output_repo.py`, `nomarr/persistence/database/calibration_repo.py`, `nomarr/persistence/database/embedding_stream_repo.py` write `created_at`/`updated_at`/`registered_at` via `now_ms().value`.
- Component layer passes ms: e.g. `nomarr/components/ml/calibration/ml_calibration_state_comp.py` (`updated_at=now_ms().value`), and consumers compare against `now_ms().value - window_ms`.
- General repos also write ms via `int(time.time() * 1000)`: `nomarr/persistence/database/tag_repo.py`, `nomarr/persistence/database/song_tag_repo.py`, `nomarr/persistence/database/song_state_repo.py`, `nomarr/persistence/database/pipeline_repo.py`.

### Historical bug (FIXED): ML repos wrote SECONDS into ms columns
- Previously the six ML data repos `nomarr/persistence/database/ml_inference_repo.py`, `nomarr/persistence/database/output_repo.py`, `nomarr/persistence/database/model_repo.py`, `nomarr/persistence/database/vector_repo.py`, `nomarr/persistence/database/calibration_repo.py`, `nomarr/persistence/database/embedding_stream_repo.py` wrote `int(time.time())` (seconds) into ms `created_at`/`updated_at` columns, and `ModelRepo.upsert_model` clobbered caller-supplied ms `updated_at` with seconds.
- **Resolved by commit `4215277a` ("Use millisecond timestamps in ML repositories").** All those repos now write `now_ms().value`. Verify with live code before asserting any repo still writes seconds.
- A live consumer symptom (calibration `recent_threshold = now_ms().value - 24h_ms` compared against seconds `calibration_states.updated_at`, making `completed_heads` always 0) is likewise **resolved**: the writer and threshold are both ms today (`calibration_svc.py` `now_ms().value - 24*60*60*1000` vs `ml_calibration_state_comp.py` `updated_at=now_ms().value`).
- Data backfill consideration: rows actually written while the seconds bug was live are 1000x too small; a magnitude-gated backfill (`UPDATE ... SET created_at = created_at * 1000 WHERE created_at < 1e11`) was under consideration at fix time — check the current data-migration state before assuming any backfill ran.

## Critical Invariants
- NEVER store monotonic time (`internal_ms()/internal_s()`) in the DB — absolute values are meaningless and appear to jump after restarts.
- DB timestamp columns are unit-agnostic BigInteger — code alone owns the ms unit. Any new write must use ms (`now_ms().value` or `int(time.time() * 1000)`).
- `now_ms()`/`now_s()` are wall clock and correct for DB timestamps and heartbeats; use `internal_ms()` only for intervals/elapsed-time, never persistence.

## Sources
- `nomarr/helpers/time_helper.py` (canonical module)
- ML persistence repos: `nomarr/persistence/database/ml_inference_repo.py`, `nomarr/persistence/database/model_repo.py`, `nomarr/persistence/database/vector_repo.py`, `nomarr/persistence/database/output_repo.py`, `nomarr/persistence/database/calibration_repo.py`, `nomarr/persistence/database/embedding_stream_repo.py`
- General ms writers: `nomarr/persistence/database/tag_repo.py`, `nomarr/persistence/database/song_tag_repo.py`, `nomarr/persistence/database/song_state_repo.py`, `nomarr/persistence/database/pipeline_repo.py`
- Wire format: `nomarr/interfaces/api/types/library_types.py`
- Schema: `alembic/versions/001_current_schema_baseline.py` (BigInteger defs)
- Fix commit: `4215277a` "Use millisecond timestamps in ML repositories"
- Tests: `tests/unit/persistence/database/test_{ml_inference,model,vector,output,calibration,embedding_stream}_repo.py`
