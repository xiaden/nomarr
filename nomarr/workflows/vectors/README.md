# Vector Workflows

Workflow for retrieving track vectors from cold (promoted) collections.

## Responsibilities

- Resolve a file's owning library and fetch its promoted vector from the cold collection

## Key Modules

| Module | Purpose |
|--------|---------|
| `get_track_vector_wf.py` | Resolve file → library → cold collection → vector document; returns `None` if not found |

## Patterns

- **Library resolution**: Determines owning library from file_id before accessing the library-scoped cold collection
- **Cold-only reads**: Only searches promoted (cold) vectors; hot collections are write-only

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** The workflow receives `Database` and uses its vector abstraction to access cold collections.

## Dependencies

- **Called by**: `services/domain/vector_search_svc.py`
- **Calls**: `persistence/` (via `Database` vector operations)
- **Receives**: `Database`, file_id, backbone_id
