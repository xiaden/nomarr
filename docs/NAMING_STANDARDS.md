# Naming Standards & Conventions

This document establishes consistent naming conventions for the Nomarr codebase to prevent API confusion and improve developer experience.

## Principles

1. **Clarity over brevity**: Use full descriptive names (`error_message` not `error_msg`, `error_text`, or `error`)
2. **Consistency**: Same concept should use same name everywhere (database columns, function parameters, API fields, class attributes)
3. **Python conventions**: Follow PEP 8 (snake_case for functions/variables, PascalCase for classes)
4. **No abbreviations**: Avoid shortened forms unless they're industry-standard (e.g., `id`, `api`, `url`)

## Naming Conventions by Category

### Database Columns

**Current Issues:**
- `error_text` vs `error_message` (inconsistent)
- Mixing styles across tables

**Standard:**
- Use full descriptive names: `error_message` (not `error_text`, `error_msg`, `err_msg`, or `error`)
- Use `_at` suffix for timestamps: `created_at`, `started_at`, `finished_at`
- Use `_id` suffix for foreign keys and job IDs: `job_id`, `scan_id`
- Use `_json` suffix for JSON columns: `results_json`, `tags_json`
- Boolean columns: `is_active`, `force` (no prefix for simple flags)

**Tables to standardize:**
- `queue` table: `error_text` → `error_message`
- `library_scans` table: `error_text` → `error_message`

### Function/Method Names

**Current Issues:**
- Inconsistent verb patterns (e.g., `add_job` vs `add`, `get_job` vs `get`)
- Unclear action verbs

**Standard:**
- **CRUD operations**: Use simple verbs without redundant suffixes
  - ✅ `add(job)` not `add_job(job)` (context is clear from class name `JobQueue`)
  - ✅ `get(job_id)` not `get_job(job_id)`
  - ✅ `list(...)` not `list_jobs(...)`
  - ✅ `update(job_id, ...)` not `update_job(...)`
  - ✅ `remove(job_id)` not `remove_job(...)` or `delete_job(...)`

- **Domain-specific operations**: Use descriptive verb+noun when action is non-standard
  - ✅ `mark_error(job_id, message)` (clear intent)
  - ✅ `mark_running(job_id)` (clear intent)
  - ✅ `flush(statuses)` (domain operation, not CRUD)
  - ✅ `queue_stats()` (getter for aggregate data)

- **Prefix patterns**:
  - `get_` for retrieving data: `get_meta()`, `get_library_file()`
  - `list_` for retrieving collections: `list_library_files()`, `list()` (context-dependent)
  - `create_` for creating new entities: `create_library_scan()`
  - `update_` for modifying existing: `update_library_scan()`
  - `delete_` for permanent removal: `delete_library_file()`
  - `remove_` for queue-like removals: `remove(job_id)` from queue

### Function Parameters

**Current Issues:**
- `error` vs `error_text` vs `error_message`
- `statuses` vs `status` (singular vs plural)

**Standard:**
- Use full descriptive names matching database columns:
  - ✅ `error_message` (matches DB column)
  - ✅ `results` (dict of results)
  - ✅ `statuses` (list/collection parameter)
  - ✅ `status` (single status value)

- Plural vs singular:
  - Plural for collections: `statuses: list[str]`, `paths: list[str]`
  - Singular for single values: `status: str`, `path: str`

### Class Attributes

**Current Issues:**
- Job class uses `error_text` (matches old DB schema)

**Standard:**
- Mirror database column names exactly for data classes:
  - ✅ `Job.error_message` (matches DB column `error_message`)
  - ✅ `Job.results` (matches concept, even though DB has `results_json`)

- Use descriptive names for computed/derived attributes:
  - ✅ `worker_enabled` (clear boolean flag)
  - ✅ `poll_interval` (clear timing value)

### API Request/Response Fields

**Current Issues:**
- API returns `error` but DB stores `error_text`
- Inconsistent field naming between layers

**Standard:**
- **External API (public/web)**: Use clean, simple names
  - ✅ `error` (simple for JSON responses)
  - ✅ `status`, `path`, `results`
  
- **Internal serialization**: Match database schema
  - ✅ `Job.to_dict()` returns `error_message` (matches DB)
  - API layer translates: `{"error": job.error_message}` for responses

- **Pydantic models**: Use clean external names
  - ✅ `TagRequest.path` (not `file_path`)
  - ✅ `FlushRequest.statuses` (plural for list)

### Constants & Configuration

**Standard:**
- All caps with underscores for true constants: `DEFAULT_POLL_INTERVAL`
- snake_case for config keys: `worker_enabled`, `blocking_mode`
- No abbreviations: `worker_count` (not `num_workers` or `worker_cnt`)

## Current Status

### ✅ Completed Refactoring (2025-11-01)
- ✅ Database schema: `error_text` → `error_message` (both `queue` and `library_scans` tables)
- ✅ Code layer: `Job.error_message`, `update_job(error_message=...)`, `mark_error(error_message=...)`
- ✅ API layer: External API uses `error`, internally translates from `job.error_message`
- ✅ Tests: All 86 tests updated and passing
- ✅ Tools: `scripts/check_naming.py` prevents regression
- ✅ Tools: `scripts/discover_api.py` shows actual API signatures

**Migration:** Pre-alpha software - delete and recreate database instead of migration scripts.

### ✅ Good Examples (Current Implementation)
- `JobQueue.add()`, `get()`, `list()` - clean CRUD methods
- `Database.update_job()`, `enqueue()`, `queue_stats()` - clear purpose
- `created_at`, `started_at`, `finished_at` - consistent timestamp pattern
- `worker_enabled`, `poll_interval` - clear boolean/config names
- `FlushRequest.statuses` - correct plural for collection
- `error_message` - standardized across all layers

### 🤔 Documentation Needed
- `depth()` - Returns count of pending + running jobs (sum of both statuses)
- `queue_stats()` - Returns dict with counts by status: `{"pending": n, "running": n, "done": n, "error": n}`
- `flush(statuses)` - Removes jobs by status list, protects "running" jobs

## Quick Reference

| Concept | Database Column | Function Parameter | Class Attribute | API Field (External) |
|---------|----------------|-------------------|-----------------|---------------------|
| Error info | `error_message` | `error_message` | `error_message` | `error` |
| Job status | `status` | `status` | `status` | `status` |
| File path | `path` | `path` | `path` | `path` |
| Results | `results_json` | `results` | `results` | `results` |
| Created time | `created_at` | N/A | `created_at` | `created_at` |
| Job ID | `id` | `job_id` | `id` | `id` or `job_id` |

## Review Checklist

When adding new features:
- [ ] Do method names follow CRUD verb patterns?
- [ ] Are parameters named consistently with database columns?
- [ ] Are plurals used for collections, singular for single values?
- [ ] Are timestamps suffixed with `_at`?
- [ ] Are IDs suffixed with `_id` in parameters (but just `id` in tables)?
- [ ] Do class attributes mirror database columns?
- [ ] Are API response fields simple and clean?
- [ ] No abbreviations except industry-standard?

---

**Tools for Maintaining Standards:**
- `scripts/check_naming.py` - Detect naming anti-patterns (error_text, err_msg, etc.)
- `scripts/discover_api.py <module>` - Show actual API signatures before writing code/tests
- `ruff check .` - Enforce PEP 8 naming conventions and code quality
