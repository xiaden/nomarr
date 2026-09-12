# Metadata Workflows

Workflows for tag-graph maintenance — orphaned tag cleanup.

## Responsibilities

- Detect and optionally delete orphaned tags (tags no longer referenced by any song) via the `tags` table

The metadata cache writer was removed by ADR-045; no workflow re-derives or
persists embedded metadata cache fields. The remaining metadata computation
helpers (`build_song_tag_assignments`, `extract_entity_tag_mapping`,
`compute_metadata_cache_fields`) are pure, compute-only functions under
`components/metadata/` and are called directly by their callers, not through a
workflow.

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `cleanup_orphaned_entities_wf.py` | `cleanup_orphaned_entities_workflow(db, dry_run=False)` — counts orphaned tags via `count_orphaned_tags` (dry run) or deletes them via `cleanup_orphaned_tags`; delegates to `components/tagging/tag_cleanup_comp.py` |

## Patterns

- **Dry-run support**: `cleanup_orphaned_entities_workflow` accepts `dry_run=True` to count without deleting
- **Workflow boundary branching**: the workflow branches on `dry_run` and delegates both paths to the `components/tagging/tag_cleanup_comp` intents (`count_orphaned_tags` / `cleanup_orphaned_tags`)

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and delegate to components and the persistence abstraction.

## Dependencies

- **Called by**: `workflows/library/scan_library_quick_wf.py` and `workflows/library/scan_library_full_wf.py` (post-scan orphan cleanup)
- **Calls**: `components/tagging/tag_cleanup_comp.py` (`count_orphaned_tags`, `cleanup_orphaned_tags`)
- **Receives**: `Database`, optional `dry_run`
- **Not called by `services/domain/metadata_svc.py`**: that service and `interfaces/cli/commands/cleanup_cli.py` perform orphan cleanup by calling `components/tagging/tag_cleanup_comp` directly (the CLI reaches it through `metadata_svc.cleanup_orphaned_entities`), not this workflow.
