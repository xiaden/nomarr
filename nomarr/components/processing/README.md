# Processing

File-level write operations for persisting ML results to the database.

## Responsibilities

- Fetch file documents and resolve library roots for tag writing
- **Legacy/non-authoritative:** `save_mood_tags*` remains historical processing code and is not the mood persistence contract; the external prerequisite is the `LibraryTagsDb` owner API (`replace_mood_tags*`) with locator-addressed marker publication.
- Read and write Nomarr-namespaced mood tags (strict, regular, loose tiers) only through the approved owner boundary
- Track file write claims and projection state for concurrency control

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `file_write_comp` | File lookup (`get_file_for_writing`), library root resolution, mood tag read/write (single + batch), write claim release, and projection state recording |

## Patterns

- **Legacy/non-authoritative:** `save_mood_tags` and `save_mood_tags_batch` are retained as historical names only; D1 does not claim their migration or authorize generic `set_song_tags_batch` as a mood owner.
- **Owner prerequisite:** `LibraryTagsDb.replace_mood_tags*` must provide tier-complete replacement and marker ownership before caller migration; that migration belongs downstream.
- **Claim lifecycle:** `release_file_claim` swallows exceptions so error-path callers don't need try/except. `mark_file_written` records successful writes with mode and calibration hash.

## Dependencies

- **Upstream:** Called by ML tag-writing workflows and calibration pipelines
- **Downstream:** Calls the intent-level persistence facade (`db.library` / `db.app`) for tag writes, file reads, and claim management
- **External:** Standard library only
