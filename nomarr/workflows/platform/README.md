# Platform Workflows

Workflows for database preparation, ML model registration, and vector index lifecycle management.

## Responsibilities

- Full database startup sequence (schema → migrations → model registration)
- ML model discovery and registration from ONNX files
- Hot→cold vector promotion with DB-level locking
- Vector index rebuild (drop + recreate without promotion)
- Idle-time vector promotion coordination across workers

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `prepare_database_wf.py` | Startup sequence — ensure schema, apply migrations, register models; fail-fast on error |
 | `register_ml_models_wf.py` | Walk models directory, introspect ONNX sessions, upsert model + output vertices, seed known labels |
 | `promote_and_rebuild_vectors_wf.py` | UPSERT hot→cold drain + vector index rebuild; convergent and idempotent |
 | `rebuild_vector_index_wf.py` | Drop and rebuild vector index on existing cold collection (no promotion) |
 | `idle_promotion_vectors_wf.py` | Worker idle-time promotion — find pending pairs, acquire DB locks, promote + rebuild |

## Patterns

- **Fail-fast startup**: `prepare_database_wf` calls `sys.exit()` on any step failure
- **Convergent promotion**: UPSERT semantics + unique _key prevent duplicate vectors
- **DB-level locking**: Idle promotion uses DB locks with stale lock reaping (>10 min)
- **Auto nlists**: Vector index nlists auto-calculated from cold collection size when not specified

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and delegate to components (`components/platform/*` for bootstrap, `components/ml/*` for model introspection). Vector operations use the `Database` vector abstraction.

## Dependencies

- **Called by**: `services/infrastructure/worker_system_svc.py`, `services/domain/vector_maintenance_svc.py`, `app.py` (startup)
- **Calls**: `components/platform/*` (schema, migrations, GPU), `components/ml/onnx/*` (model introspection), `persistence/` (via `Database`)
- **Receives**: `Database`, models_dir, backbone_id, library_key
