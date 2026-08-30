---
name: time-unit-conventions
description: Nomarr timestamp unit conventions — wall-clock timestamps persisted to PostgreSQL (created_at, updated_at, registered_at, scanned_at, heartbeat) are INTEGER MILLISECONDS since epoch, produced via now_ms().value or int(time.time()*1000). The ML persistence repos (ml_inference_repo, model_repo, vector_repo, output_repo, calibration_repo, embedding_stream_repo) wrote SECONDS via int(time.time()) — the known unit-inconsistency bug. Load when touching ML repo timestamps, adding a timestamp column, comparing timestamps, or writing data-migration SQL for timestamp columns.
description_expanded: |
  ## Mental Model
  Nomarr stores wall-clock timestamps as integer milliseconds since epoch in BigInteger columns. Storage is unit-agnostic (BigInteger); the unit convention is enforced purely in code. time_helper.py is the canonical time module: now_ms()/now_s() = wall clock, internal_ms()/internal_s() = monotonic. Raw time.time/time.time_ns is banned outside time_helper.py. Monotonic values must NEVER be persisted (absolute value meaningless); wall-clock ms is the only acceptable DB timestamp unit. Conversion helpers: s_to_ms(Seconds) -> Milliseconds, now_s().value*1000 for seconds-sourced values.

  ## Coverage
  **Documented:** The ms convention; the full list of second-writing ML repos (the bug); the ms-writing reference implementations; consumers broken by the mismatch (calibration staleness); fix shape including data backfill.
  **Not yet documented:** Whether frontend consumers interpret ML timestamps (e.g. calibration last_updated, model created_at/updated_at) as ms. The backend API surfaces raw ints; if any frontend displays them, verify it divides by 1000.
  **Last extended:** 2026-08-19

  ## Key Findings

  ### Canonical convention: persisting wall-clock timestamps = milliseconds
  - **Location:** `nomarr/helpers/time_helper.py:76-99` (`now_ms()`, `now_s()`), module docstring lines 1-23
  - **What:** Wall-clock ms via `now_ms()` (time.time_ns() // NS_PER_MS). Docstring: "Use wall-clock time for: Database timestamps, Heartbeats". Ruff bans raw time sources outside this file.
  - **Why it matters:** The canonical call for ANY DB timestamp is `now_ms().value`. A seconds-source must be converted (`s_to_ms()` or `* 1000`), as `keys_svc.py:286` does (`int(now_s().value * 1000)`).

  ### Reference implementations that write ms correctly
  - `nomarr/persistence/database/tag_repo.py:111,154` — `int(time.time() * 1000)`
  - `nomarr/persistence/database/song_state_repo.py:120,149,199,277` — `int(time.time() * 1000)`
  - `nomarr/persistence/database/song_tag_repo.py:103,140,167` — `int(time.time() * 1000)`
  - `nomarr/persistence/database/pipeline_repo.py:63,99` — `int(time.time() * 1000)`
  - `nomarr/components/workers/worker_crash_comp.py:49` — `int(time.time() * 1000)`
  - Component layer already passes ms: `ml_model_registry_comp.py:73,84,91,123,138` (`now_ms().value`), `ml_calibration_state_comp.py:107,177`.
  - API layer: `library_types.py:77-87` formats int timestamps as `datetime.fromtimestamp(created_at / 1000)` — proof the wire format is ms.

  ### The bug: ML repos write SECONDS into ms columns
  Affected files (all `int(time.time())`, should be `now_ms().value`):
  - `nomarr/persistence/database/ml_inference_repo.py:92,101` — `ml_output_streams.created_at`, `embeddings.created_at/updated_at`
  - `nomarr/persistence/database/output_repo.py:85,160` — `ml_model_outputs.created_at`, `ml_output_streams.created_at`
  - `nomarr/persistence/database/model_repo.py:131,158` — `ml_models.created_at/updated_at`. NOTE: `upsert_model` OVERWRITES caller-supplied ms `updated_at` with seconds (line 133), clobbering the ms value passed by `ml_model_registry_comp.upsert_registered_model` (line 84).
  - `nomarr/persistence/database/vector_repo.py:85,169` — `embeddings.created_at/updated_at`, `drain_hot_to_cold` `updated_at`
  - `nomarr/persistence/database/calibration_repo.py:78,162` — `calibration_states.updated_at`, `calibration_history.created_at`
  - `nomarr/persistence/database/embedding_stream_repo.py:80` — `ml_embedding_streams.created_at`
  - `ml_models.registered_at` (ms, written by `ml_model_registry_comp.py:91`) is the mixed-unit table: seconds in created_at/updated_at next to ms in registered_at.

  ### Live consumer bug caused by the mismatch
  - **Location:** `nomarr/services/domain/calibration_svc.py:456-457` → `count_recent_calibration_states` (`ml_calibration_state_comp.py:35-38`)
  - **What:** `recent_threshold = now_ms().value - 24h_ms (~1.7e12)` is compared against `calibration_states.updated_at` (~1.7e9, seconds). `doc["updated_at"] >= threshold` is ALWAYS false → `completed_heads` always 0 and `remaining_heads` always total, in `GET /api/web/calibration/histogram/status` (`calibration_if.py:126-133`).
  - Surfaces via `HistogramGenerationStatusResponse.last_updated`/`completed_heads`.

  ## Critical Invariants
  - NEVER store monotonic time (`internal_ms()/internal_s()`) in the DB — absolute values are meaningless and appear to jump after restarts.
  - DB timestamp columns are unit-agnostic BigInteger — the code alone owns the ms unit. Any new write must use ms.
  - `ModelRepo.upsert_model` clobbers `updated_at`/`created_at` from payloads — callers passing ms must not be overwritten by seconds.
  - Existing rows written in seconds (~1.7e9 magnitude) are 1000x too small; a data backfill (`UPDATE ... SET created_at = created_at * 1000` where plausible seconds) is required for a complete fix — decide in the fix plan whether to gate on magnitude (< 1e11).

  ## Sources
  - `nomarr/helpers/time_helper.py` (canonical module)
  - All affected repos listed above; schema models `nomarr/persistence/models/{ml_model,embedding,ml_output_stream,ml_model_output,ml_embedding_stream,calibration_state,calibration_history}.py`
  - Alembic: `alembic/versions/001_current_schema_baseline.py` (BigInteger defs)
  - Tests: `tests/unit/persistence/database/test_{ml_inference,model,vector,output,calibration,embedding_stream}_repo.py` — assertions are only `> 0`, no unit assertions
  - Consumer: `nomarr/services/domain/calibration_svc.py:413-472`, `nomarr/components/ml/calibration/ml_calibration_state_comp.py`, `nomarr/interfaces/api/web/calibration_if.py:126-133`