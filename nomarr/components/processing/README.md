# Processing

File-level write operations for persisting ML results to the database.

## Responsibilities

- Fetch file documents and resolve library roots for tag writing
- Mood publication is owned solely by the external prerequisite `LibraryTagsDb.replace_mood_tags*` API with locator-addressed marker publication; no processing mood writer remains.
- Track file write claims for concurrency control

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `file_write_comp` | File lookup (`get_file_for_writing`), library root resolution, and write claim release |

## Patterns

- **Removed (Q3-J):** legacy `save_mood_tags`, `save_mood_tags_batch`, and `get_nomarr_tags` were deleted; mood persistence is exclusively `LibraryTagsDb.replace_mood_tags`.
- **Owner prerequisite:** `LibraryTagsDb.replace_mood_tags*` must provide tier-complete replacement and marker ownership before caller migration; that migration belongs downstream.
- **Claim lifecycle:** `release_file_claim` swallows exceptions so error-path callers don't need try/except. The claimant releases the file claim after the write path completes; there is no separate `mark_file_written` writer in this module.

## Dependencies

- **Upstream:** Called by ML tag-writing workflows and calibration pipelines
- **Downstream:** Calls the intent-level persistence facade (`db.library` / `db.app`) for tag writes, file reads, and claim management
- **External:** Standard library only
