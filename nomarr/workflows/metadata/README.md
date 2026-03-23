# Metadata Workflows

Workflows for entity (tag) graph maintenance — orphan cleanup and metadata cache rebuilding.

## Responsibilities

- Remove orphaned tags (tags with no incoming song edges) from the `tags` collection
- Rebuild derived metadata cache fields for all songs from `song_has_tags` edges

## Key Modules

| Module | Purpose |
|--------|---------|
| `cleanup_orphaned_entities_wf.py` | Count and optionally delete orphaned tags; supports dry-run mode |
| `rebuild_metadata_cache_wf.py` | Re-derive embedded cache fields from `song_has_tags` edges for all songs |

## Patterns

- **Dry-run support**: Cleanup workflow accepts `dry_run=True` to count without deleting
- **Batch processing**: Cache rebuild processes songs in batches for bounded memory

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and delegate to components and the persistence abstraction.

## Dependencies

- **Called by**: `services/domain/metadata_svc.py`
- **Calls**: `components/metadata/*` (entity cleanup, cache rebuild), `persistence/` (via `Database`)
- **Receives**: `Database`, optional limits
