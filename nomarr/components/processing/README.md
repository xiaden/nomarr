# Processing

File-level write operations for persisting ML results to the database.

## Responsibilities

- Fetch file documents and resolve library roots for tag writing
- Read and write Nomarr-namespaced mood tags (strict, regular, loose tiers)
- Batch-write mood tags across multiple files in minimal AQL round-trips
- Track file write claims and projection state for concurrency control

## Key Modules

| Module | Purpose |
|--------|----------|
| `file_write_comp` | File lookup (`get_file_for_writing`), library root resolution, mood tag read/write (single + batch), write claim release, and projection state recording |

## Patterns

- **Tier-complete writes:** `save_mood_tags` always writes all three mood tiers (strict, regular, loose). Missing tiers are explicitly cleared to prevent stale data from previous calibrations.
- **Batch optimization:** `save_mood_tags_batch` collapses N files × 3 tiers into 3 AQL queries total via `set_song_tags_batch`.
- **Claim lifecycle:** `release_file_claim` swallows exceptions so error-path callers don't need try/except. `mark_file_written` records successful writes with mode and calibration hash.

## Dependencies

- **Upstream:** Called by ML tag-writing workflows and calibration pipelines
- **Downstream:** Calls persistence directly (ArangoDB tag operations via `db.tags`, file document reads, claim management)
- **External:** Standard library only
