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

- **Mood ownership:** `LibraryTagsDb.replace_mood_tags*` owns locator-addressed mood-tag replacement, including tier-complete replacement and marker publication; processing has no mood persistence writer.
- **Claim lifecycle:** `release_file_claim` swallows exceptions so error-path callers don't need try/except. The claimant releases the file claim after the write path completes; there is no separate `mark_file_written` writer in this module.

## Dependencies

- **Upstream:** Called by ML tag-writing workflows and calibration pipelines
- **Downstream:** Calls the intent-level persistence facade (`db.library` / `db.app`) for tag writes, file reads, and claim management
- **External:** Standard library only
