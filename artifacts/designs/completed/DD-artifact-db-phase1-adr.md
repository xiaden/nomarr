# Artifact DB Phase 1 — ADR Migration to ArangoDB — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-09  

**Related Documents:**

- [DD-code-intel-arangodb-migration](artifacts/designs/pending/DD-code-intel-arangodb-migration.md) —
- [ADR-004 Schema Refactor V1 Graph Normalization](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) —
- [ADR-005 Agent System Architecture](artifacts/decisions/ADR-005-agent-system-architecture-and-artifact-management.md) —
- [rnd-manager log L49-L51](artifacts/logs/rnd-manager.md) —

---

## Scope

Migrate ADR (Architecture Decision Records) artifact storage from file-based markdown to ArangoDB. Covers: ADR vertex collection, tag vertex collection, sequence infrastructure, two edge collections, all 4 registered ADR MCP tools (`adr_suggest`, `adr_commit`, `adr_search`, `adr_read`), helper refactoring, DB infrastructure foundation, ingest script, and testing strategy. Note: `adr_create.py` exists as dead code (not registered in `server.py`) and is out of scope. Does NOT cover other artifact types (Log, ASR, DD, Plan), cross-type reference edges, ArangoSearch views, or the existing DD-code-intel-arangodb-migration.

---

## Problem Statement

The code-intel MCP server stores ADRs as markdown files in `artifacts/decisions/`. This has four structural problems:

1. **No queryability.** Searching ADRs by tag requires parsing every `ADR-*.md` file. `adr_search` does `decisions_dir.glob("ADR-*.md")` and parses each file in a Python loop.
2. **Race-condition numbering.** `adr_commit` calls `next_adr_number()` which scans filenames for the max number, then retries up to 3 times on `FileExistsError`. This is fragile.
3. **No graph relationships.** `supersedes` is a list of strings in frontmatter (`["ADR-001", "ADR-003"]`). There is no traversable relationship — finding "what superseded ADR-001?" requires scanning all ADRs.
4. **Tags are embedded arrays.** Finding "all ADRs tagged `database`" requires parsing every file. Tags cannot be shared or discovered across artifact types.

ArangoDB is already the project's database. Phase 1 migrates ADRs first because ADRs validate the most graph patterns needed by all future phases: typed edges (supersedes), shared tag vertices, auto-numbering sequences, multi-field search, and document lifecycle (draft → committed).

---

## Architecture

## Section 1: Artifact Selection Rationale

ADR is chosen as the Phase 1 migration target over Log, ASR, DD, and Plan:

 | Candidate | Verdict | Rationale |
 | ----------- | --------- | ----------- |
 | **ADR** | **Selected** | Validates typed edges (supersedes), shared tags, auto-numbering, multi-field search, draft lifecycle. `adr_supersedes_adr` is self-referential — no dependency on other types being migrated. |
 | Log | Too simple | No edges. Proves nothing about the graph model. High raw safety score but zero pattern coverage. |
 | ASR | Blocked | `linked_adrs` field creates a dependency on ADRs already existing in DB. Must come after ADR. |
 | DD | Poor fit | Variable-keyed sections, unstructured `related_documents`. Low graph validation value. |
 | Plan | Too complex | Plan steps and annotations require deep decomposition. Analysis recommends embedding everything. |

Tags established here as shared vertices become the reuse pattern for all future phases. The `adr_has_tag` edge pattern is replicated as `asr_has_tag`, `log_has_tag`, etc. in Phase 2+.

---

## Section 2: Complete ArangoDB Schema

### Hard Constraints (User-Defined ASRs)

These constraints drove every schema decision below:

1. **ASR #1:** Tool calls compose the product from multiple documents (traversal, not single-doc read)
2. **ASR #2:** No foreign keys in document collections — zero. No embedded arrays of IDs referencing other collections.
3. **ASR #3:** Edge collections use single direction, single FROM/TO collection type
4. **ASR #4:** Edges contain no mutable or filterable fields (pure structural connectors)
5. **ASR #5:** No polymorphic edges

### Document Collections (3)

#### `adrs` — ADR vertex documents

 | Field | Type | Notes |
 | ------- | ------ | ------- |
 | `_key` | string | Slugified title (e.g., `"use-onnx-runtime-for-ml-inference"`). Stable from suggest through commit. |
 | `number` | int \ | null | `null` for drafts; assigned at commit via `sequences` collection |
 | `title` | string | Human-readable title |
 | `status` | string | `"Proposed"` \ | `"Accepted"` \ | `"Deprecated"` \ | `"Superseded"` |
 | `is_draft` | boolean | `true` during suggest, `false` after commit |
 | `date` | string | ISO 8601 date (e.g., `"2026-04-09"`) |
 | `source_log` | string \ | null | `"{agent}#L{N}"` format. String for Phase 1; becomes edge when Logs migrate in Phase 2. `""` from tools stored as `null`. |
 | `sections` | object | `{"Context": "...", "Decision": "...", "Consequences": "...", "References": "...", "{ExtraHeading}": "..."}` |
 | `created_at` | string | ISO 8601 timestamp, set on insert |
 | `updated_at` | string | ISO 8601 timestamp, updated on modify |

**NOT on the ADR document:** `tags` array (ASR #2 — no embedded arrays of references), `supersedes` array (ASR #2 — no embedded IDs referencing other documents). These are modeled as edges.

**Indexes:**

- Sparse unique on `number` — null values excluded, allowing multiple drafts
- Persistent on `status` — for filtered searches
- Persistent on `date` — for date-ordered queries
- Persistent on `is_draft` — for draft/committed filtering

#### `tags` — Shared tag vertices (reused by future phases)

 | Field | Type | Notes |
 | ------- | ------ | ------- |
 | `_key` | string | Normalized tag name: `tag.strip().lower()` |

No other fields. The `_key` IS the tag. Deduplication is automatic via `_key` uniqueness. This collection is shared across all artifact types — `adr_has_tag`, `asr_has_tag`, `log_has_tag` edges all point TO this same collection.

#### `sequences` — Auto-numbering infrastructure

 | Field | Type | Notes |
 | ------- | ------ | ------- |
 | `_key` | string | `"adrs"` (one document per numbered artifact type) |
 | `value` | int | Highest assigned number |

Seeded with `{ _key: "adrs", value: 0 }` on bootstrap. Extended in future phases with `_key: "asrs"`, etc.

### Edge Collections (2)

#### `adr_has_tag` — ADR → Tag

 | Property | Value |
 | ---------- | ------- |
 | FROM | `adrs` |
 | TO | `tags` |
 | Fields | None (pure structural connector — ASR #4 compliance) |
 | Unique index | Compound on `(_from, _to)` — prevents duplicate tag assignments |

#### `adr_supersedes_adr` — ADR → ADR (newer supersedes older)

 | Property | Value |
 | ---------- | ------- |
 | FROM | `adrs` |
 | TO | `adrs` |
 | Fields | None (pure structural connector — ASR #4 compliance) |
 | Unique index | Compound on `(_from, _to)` — prevents duplicate supersedes declarations |

### Schema Totals

 | Type | Count | Collections |
 | ------ | ------- | ------------- |
 | Document | 3 | `adrs`, `tags`, `sequences` |
 | Edge | 2 | `adr_has_tag`, `adr_supersedes_adr` |
 | **Total** | **5** | |

---

## Section 3: Field-by-Field Mapping

 | Current Field | Source Format | Destination | Collection | Transformation |
 | -------------- | -------------- | ------------- | ------------ | ---------------- |
 | `number` (from filename `ADR-NNN`) | int | `number` field | `adrs` | `null` for drafts |
 | `title` | string | `title` | `adrs` | Unchanged |
 | `status` | enum string | `status` + `is_draft` | `adrs` | Unchanged; add `is_draft = false` for committed ADRs |
 | `date` | ISO date string | `date` | `adrs` | Unchanged |
 | `tags[]` | `["api", "database"]` | `tags._key` + `adr_has_tag` edges | `tags` + `adr_has_tag` | Each tag → UPSERT tag vertex, INSERT edge |
 | `source_log` | `"rnd-ddauthor#L42"` or `""` | `source_log` | `adrs` | `""` → `null`; kept as string in Phase 1 |
 | `supersedes[]` | `["ADR-001", "ADR-003"]` | `adr_supersedes_adr` edges | `adr_supersedes_adr` | Resolve `ADR-NNN` → slug via number index, INSERT edge |
 | `context` section | markdown text | `sections.Context` | `adrs` | Embedded in sections dict |
 | `decision` section | markdown text | `sections.Decision` | `adrs` | Embedded in sections dict |
 | `consequences` section | markdown text | `sections.Consequences` | `adrs` | Embedded in sections dict |
 | `references` section | markdown text (optional) | `sections.References` | `adrs` | Embedded if present |
 | `extra_sections[{heading, content}]` | list of `{heading, content}` dicts | `sections[heading]` | `adrs` | Merged into sections dict with heading as key |

---

## Section 4: Example AQL Queries

### Read single ADR (by slug)

```aql
WITH adrs, tags
LET doc = DOCUMENT('adrs', @slug)
FILTER doc != null
LET adr_tags = (
    FOR v IN 1..1 OUTBOUND doc._id adr_has_tag
    RETURN v._key
)
LET superseded = (
    FOR v IN 1..1 OUTBOUND doc._id adr_supersedes_adr
    RETURN v.number != null ? CONCAT('ADR-', RIGHT(CONCAT('000', TO_STRING(v.number)), 3)) : v._key
)
RETURN MERGE(
    UNSET(doc, ["_id", "_rev"]),
    { tags: adr_tags, supersedes: superseded }
)
```

### Read single ADR (by number)

```aql
WITH adrs, tags
FOR doc IN adrs
    FILTER doc.number == @number
    LET adr_tags = (
        FOR v IN 1..1 OUTBOUND doc._id adr_has_tag
        RETURN v._key
    )
    LET superseded = (
        FOR v IN 1..1 OUTBOUND doc._id adr_supersedes_adr
        RETURN v.number != null ? CONCAT('ADR-', RIGHT(CONCAT('000', TO_STRING(v.number)), 3)) : v._key
    )
    RETURN MERGE(
        UNSET(doc, ["_id", "_rev"]),
        { tags: adr_tags, supersedes: superseded }
    )
```

### Search ADRs (tag, status, text query)

Maps to current `adr_search` behavior: filter by status, tag (case-insensitive substring match), and free-text query across title + tags + ALL section values. Results sorted by number descending, limited.

**Behavioral notes:**

- Tag matching uses `CONTAINS()` (substring), not exact `IN`, to preserve current behavior where tag `"api"` is matched by query `"ap"`.
- Text query searches ALL section values (including References and extra sections), not just Context/Decision/Consequences.
- The query returns a `total` count of all matching results before `LIMIT` is applied.

```aql
WITH adrs, tags
LET all_matches = (
FOR doc IN adrs
    FILTER doc.is_draft == false
    FILTER LENGTH(@status) == 0 OR doc.status == @status
    LET adr_tags = (
        FOR v IN 1..1 OUTBOUND doc._id adr_has_tag
        RETURN v._key
    )
    FILTER LENGTH(@tag) == 0 OR (
        LENGTH(adr_tags) > 0 AND
        LENGTH(FOR t IN adr_tags FILTER CONTAINS(t, LOWER(@tag)) RETURN 1) > 0
    )
    FILTER LENGTH(@query) == 0 OR (
        CONTAINS(LOWER(doc.title), LOWER(@query))
        OR LENGTH(FOR t IN adr_tags FILTER CONTAINS(t, LOWER(@query)) RETURN 1) > 0
        OR CONTAINS(LOWER(CONCAT_SEPARATOR(' ', VALUES(doc.sections))), LOWER(@query))
    )
    SORT doc.number DESC
    RETURN {
        number: doc.number,
        title: doc.title,
        status: doc.status,
        date: doc.date,
        tags: adr_tags,
        key: doc._key
    }
)
RETURN {
    results: SLICE(all_matches, 0, @limit),
    total: LENGTH(all_matches)
}
```

### Create draft (adr_suggest)

Two-step operation:

**Step 1:** UPSERT ADR vertex with `is_draft: true`, `number: null` (overwrites existing draft, rejects committed ADR)

```aql
UPSERT { _key: @slug }
INSERT {
    _key: @slug,
    number: null,
    title: @title,
    status: @status,
    is_draft: true,
    date: @date,
    source_log: @source_log,
    sections: @sections,
    created_at: @now,
    updated_at: @now
}
UPDATE {
    title: @title,
    status: @status,
    date: @date,
    source_log: @source_log,
    sections: @sections,
    updated_at: @now
}
IN adrs
OPTIONS { keepNull: false }
LET wasCommitted = OLD != null AND OLD.is_draft == false
RETURN { wasCommitted, key: NEW._key }
```

If `wasCommitted` is `true`, the tool rolls back and returns `{"error": "already_committed", ...}`.

**Step 2:** For each tag, UPSERT tag vertex + INSERT edge (idempotent)

```aql
UPSERT { _key: @tag_key }
INSERT { _key: @tag_key }
UPDATE {} IN tags
```

```aql
INSERT { _from: CONCAT('adrs/', @slug), _to: CONCAT('tags/', @tag_key) }
INTO adr_has_tag
OPTIONS { overwriteMode: "ignore" }
```

### Commit ADR (adr_commit)

**Step 1:** Atomic sequence increment

```aql
UPDATE "adrs" WITH { value: OLD.value + 1 } IN sequences
RETURN NEW.value
```

**Step 2:** Update ADR document

```aql
UPDATE @slug WITH {
    number: @number,
    is_draft: false,
    updated_at: @now
} IN adrs
RETURN NEW
```

### Supersede

Transaction: UPDATE old ADR status → `"Superseded"`, INSERT edge.

```aql
UPDATE @old_slug WITH { status: "Superseded", updated_at: @now } IN adrs
```

```aql
INSERT { _from: CONCAT('adrs/', @new_slug), _to: CONCAT('adrs/', @old_slug) }
INTO adr_supersedes_adr
OPTIONS { overwriteMode: "ignore" }
```

### List all tags with ADR counts

```aql
FOR t IN tags
    LET count = LENGTH(
        FOR e IN adr_has_tag FILTER e._to == t._id RETURN 1
    )
    SORT t._key ASC
    RETURN { tag: t._key, adr_count: count }
```

---

## Section 5: MCP Tool Changes

### Current Tool Inventory

All tools are in `code-intel/src/mcp_code_intel/tools/`. Helper module: `code-intel/src/mcp_code_intel/helpers/adr_md.py`.

**Registered MCP tools (4):** `adr_suggest`, `adr_commit`, `adr_search`, `adr_read`. These are the only ADR tools registered in `server.py`.

**Not registered:** `adr_create.py` exists as a file but is NOT imported or registered in `server.py`. It is dead code — not an exposed MCP tool. It is out of scope for this design.

### Tool-by-Tool Changes

#### `adr_suggest` (adr_suggest.py)

**Current behavior:** Validates inputs, builds `ADR` dataclass, calls `generate_adr()` to produce markdown, writes draft file to `artifacts/decisions/drafts/DRAFT-{slug}.md`. Returns `{markdown, title, draft_id, draft_path, word_count}`.

**New behavior:**

1. Same input validation (title, status, tags, sections)
2. Same `_unescape_literal_newlines` processing
3. Build sections dict (same logic)
4. UPSERT ADR vertex into `adrs` with `is_draft: true`, `number: null` (overwrites existing draft; rejects if committed ADR exists with same slug)
5. UPSERT each tag into `tags`, INSERT `adr_has_tag` edges
6. If `supersedes` provided, INSERT `adr_supersedes_adr` edges (resolve `ADR-NNN` → slug via number index)
7. Return `{title, draft_id (= _key/slug), word_count, status: "staged"}` — no markdown in response, no file path. Callers use `adr_read(draft_id)` to review the full draft content.

**Removed:** File I/O to `artifacts/decisions/drafts/`, markdown generation.

**New dependency:** `db: StandardDatabase` parameter injected by server.py.

**Response Contract:**

 | Field | Current | DB Version | Breaking? |
 | ------- | --------- | ------------ | ----------- |
 | `markdown` | Full ADR markdown text | **Removed** — not generated | **YES** — callers that display the markdown must use `adr_read` on the `draft_id` instead |
 | `title` | ADR title string | Unchanged | No |
 | `draft_id` | Slugified title (e.g., `"use-onnx-runtime"`) | Unchanged — equals `_key` | No |
 | `draft_path` | `"artifacts/decisions/drafts/DRAFT-{slug}.md"` | **Removed** — no file exists | **YES** — see Draft Review section below |
 | `word_count` | Word count across body sections | Unchanged — computed from input sections | No |
 | `status` | *(not returned)* | **Added**: `"staged"` | No (additive) |

**Draft Review (replacing `draft_path`):** With DB storage, there is no file to link for agent/user review. The DB version removes `markdown` and `draft_path` from the response. Instead, the `draft_id` can be passed to `adr_read` to retrieve the full draft content for review. The `adr_read` tool will return drafts when queried by slug `_key`. This preserves the review workflow (suggest → read draft → approve → commit) without requiring temporary files.

#### `adr_commit` (adr_commit.py)

**Current behavior:** Loads draft file from `artifacts/decisions/drafts/DRAFT-{draft_id}.md`, parses it, scans filesystem for next number (retry-on-collision loop × 3), writes final `ADR-NNN-{slug}.md` to `artifacts/decisions/`, deletes draft file. Checks for `source_log` duplicates by scanning all existing ADR files.

**New behavior:**

1. Look up draft by `_key` in `adrs` where `is_draft == true`
2. Atomic sequence increment: `UPDATE "adrs" WITH { value: OLD.value + 1 } IN sequences RETURN NEW.value`
3. UPDATE ADR document: set `number`, `is_draft: false`, `updated_at`
4. If `supersedes` provided: UPDATE each referenced ADR's status to `"Superseded"`, INSERT `adr_supersedes_adr` edges
5. `source_log` duplicate check: AQL query instead of file scan
6. Return `{number, title, key}`

**Removed:** File I/O, retry-on-collision loop, markdown generation, `next_adr_number()` filesystem scan. The `_MAX_RETRIES` pattern is eliminated entirely — atomic sequence increment cannot collide.

**Response Contract:**

 | Field | Current | DB Version | Breaking? |
 | ------- | --------- | ------------ | ----------- |
 | `path` | `"artifacts/decisions/ADR-NNN-slug.md"` | **Removed** — no file written | **YES** — callers using path for linking |
 | `number` | ADR number (int) | Unchanged | No |
 | `title` | ADR title string | Unchanged | No |
 | `markdown` | Full ADR markdown text | **Removed** — not generated | **YES** |
 | `content_warning` | Optional word-count warning | Unchanged — computed from input | No |
 | `source_log_warning` | Optional duplicate source_log warning | Unchanged — AQL check replaces file scan | No |
 | `key` | *(not returned)* | **Added**: ADR `_key`/slug | No (additive) |

**Fallback parameters:** The tool currently accepts all content parameters (title, status, tags, context, etc.) for the "no draft" fallback path. In DB mode, this creates-then-commits in a single transaction (INSERT + sequence increment + UPDATE).

#### `adr_search` (adr_search.py)

**Current behavior:** Calls `decisions_dir.glob("ADR-*.md")`, iterates all files, parses each (metadata-only when no text query, full parse when text query needed), filters in Python, sorts by number descending, limits results.

**New behavior:**

1. Single AQL query with bind params for `@status`, `@tag`, `@query`, `@limit`
2. All filtering done in AQL (see Section 4 query)
3. Return same shape: `{results: [...], total: N}`

**Removed:** All file I/O, `parse_adr` / `parse_adr_metadata` calls, Python-side filtering loop.

**Response Contract:**

 | Field | Current (per result) | DB Version | Breaking? |
 | ------- | --------------------- | ------------ | ----------- |
 | `number` | ADR number (int) | Unchanged | No |
 | `title` | ADR title string | Unchanged | No |
 | `status` | Status string | Unchanged | No |
 | `date` | ISO date string | Unchanged | No |
 | `tags` | Tag list | Unchanged | No |
 | `path` | `"artifacts/decisions/ADR-NNN-slug.md"` | **Removed** | **YES** |
 | `key` | *(not returned)* | **Added**: ADR `_key`/slug | No (additive) |

Envelope: `{results: [...], total: N}` — unchanged. The `total` field represents the count of *all* matching results before `LIMIT` is applied. See Section 4 for the count mechanism.

#### `adr_read` (adr_read.py)

**Current behavior:** Resolves name via `_resolve_adr_path()` which accepts:

- Full filename: `"ADR-003-use-edges.md"` or `"ADR-003-use-edges"` (strips `.md`)
- Numeric (with or without `ADR-` prefix): `"003"`, `"3"`, `"ADR-003"` → globs for `ADR-003-*.md`
- ADR-prefixed stem: `"ADR-003-use-edges"` → tries exact match in decisions dir

Does NOT support arbitrary slug lookup (e.g., `"use-edges"` without ADR prefix won't match). After resolution, reads file and calls `parse_adr()`. Returns `{number, title, status, date, tags, source_log, sections, path}`. Note: `supersedes` is parsed by `parse_adr()` into the ADR dataclass but is NOT included in the `adr_read` response dict (omission in current implementation).

**New behavior:**

1. If input is numeric (or `ADR-NNN` format): AQL query by `number` field
2. If input is a slug/name: direct `DOCUMENT('adrs', slug)` lookup
3. Traversal for tags and supersedes (see Section 4 read queries)
4. Return same shape minus `path`, plus `key` and `supersedes`

**Compatibility shim:** The DB version accepts the same input formats as today:

- `"ADR-001"` or `"1"` or `"001"` → extract number, query by `number` field
- `"ADR-001-use-onnx-runtime"` → strip prefix + number to get slug, query by `_key`
- `"use-onnx-runtime"` → direct `_key` lookup (NEW — not supported in file-based version)

Input parsing logic lives in the tool function, not in `db_persistence.py`.

**Response Contract:**

 | Field | Current | DB Version | Breaking? |
 | ------- | --------- | ------------ | ----------- |
 | `number` | ADR number (int) | Unchanged (null for drafts) | No |
 | `title` | ADR title string | Unchanged | No |
 | `status` | Status string | Unchanged | No |
 | `date` | ISO date string | Unchanged | No |
 | `tags` | Tag list | Unchanged (now from traversal) | No |
 | `source_log` | Source log string or null | Unchanged | No |
 | `sections` | Dict of section heading → content | Unchanged | No |
 | `path` | `"artifacts/decisions/ADR-NNN-slug.md"` | **Removed** | **YES** |
 | `supersedes` | *(not returned — omission in current impl)* | **Added**: list of `"ADR-NNN"` strings | No (additive — fixes omission) |
 | `key` | *(not returned)* | **Added**: ADR `_key`/slug | No (additive) |
 | `is_draft` | *(not returned)* | **Added**: boolean | No (additive) |

**Removed:** `_resolve_adr_path()` with its glob/filename matching. File I/O.

#### `adr_create` (adr_create.py — NOT a registered MCP tool)

**Current status:** This file exists but is NOT imported or registered in `server.py`. It is dead code.

**Phase 1 decision:** Out of scope. Do not migrate, do not register. If a "create without draft" convenience is needed in the future, it can be added as a new registered tool. The `adr_commit` fallback path (providing all content params directly without a `draft_id`) already serves this use case for callers that know about it.

### Helper Changes

**`adr_md.py`** — Parsing/serialization helpers (`parse_adr`, `parse_adr_metadata`, `generate_adr`, `next_adr_number`, `make_adr_filename`, `_slugify`, etc.) become irrelevant for DB operations. Kept temporarily for the ingest script (Section 7). After ingest is stable, `adr_md.py` can be deprecated — the ingest script can vendor its own copy if needed later.

**New helpers** (see Section 6):

- `db_client.py` — connection factory
- `db_schema.py` — idempotent schema bootstrap
- `db_persistence.py` — AQL execution helpers for ADR operations

---

## Section 6: Infrastructure Foundation

Phase 1 establishes shared infrastructure used by all future artifact migration phases.

### New Files

All in `code-intel/src/mcp_code_intel/helpers/`:

#### `db_client.py` — Connection Factory

```python
def connect_artifact_db(config: dict) -> StandardDatabase:
    """Create an ArangoDB connection for artifact storage.
    
    Creates the target database if it doesn't exist (connects to _system first).
    """
    client = ArangoClient(hosts=config["url"])
    # Ensure the database exists
    sys_db = client.db(
        "_system",
        username=config["username"],
        password=config["password"],
    )
    if not sys_db.has_database(config["database"]):
        sys_db.create_database(config["database"])
    # Connect to the artifact database
    return client.db(
        config["database"],
        username=config["username"],
        password=config["password"],
    )
```

Responsibilities: ArangoClient creation, database auto-creation, database connection, health check. Returns `StandardDatabase` handle.

**Dependency:** Requires `python-arango` package. Must be added to `code-intel/pyproject.toml` dependencies:

```toml
dependencies = [
    # ... existing deps ...
    "python-arango>=8.0.0",
]
```

#### `db_schema.py` — Idempotent Schema Bootstrap

```python
def ensure_adr_schema(db: StandardDatabase) -> None:
    """Create ADR collections and indexes if they don't exist."""
```

Creates:

- Document collections: `adrs`, `tags`, `sequences`
- Edge collections: `adr_has_tag`, `adr_supersedes_adr`
- All indexes (see Section 2)
- Seeds `sequences` with `{ _key: "adrs", value: 0 }` if not present

Idempotent — safe to call on every startup. Uses `has_collection()` checks.

#### `db_persistence.py` — AQL Execution Helpers

Functions:

- `next_adr_number(db) -> int` — atomic sequence increment
- `upsert_tag(db, tag_key: str) -> None` — UPSERT tag vertex
- `insert_tag_edges(db, adr_key: str, tag_keys: list[str]) -> None` — batch edge insert
- `insert_supersedes_edges(db, from_key: str, to_keys: list[str]) -> None` — batch edge insert
- `read_adr_by_key(db, key: str) -> dict | None` — read with tag/supersedes traversal
- `read_adr_by_number(db, number: int) -> dict | None` — read with tag/supersedes traversal
- `search_adrs(db, status, tag, query, limit) -> list[dict]` — parameterized search
- `insert_adr(db, doc: dict) -> str` — INSERT vertex, returns `_key`
- `update_adr(db, key: str, fields: dict) -> dict` — partial UPDATE

### Config Additions

In `config_loader.py`, add to `DEFAULT_CONFIG`:

```python
"artifact_db": {
    "url": "http://localhost:8529",
    "database": "nomarr_artifacts",
    "username": "root",
    "password": "",
}
```

Environment variable overrides:

- `ARTIFACT_DB_URL` → `artifact_db.url`
- `ARTIFACT_DB_NAME` → `artifact_db.database`
- `ARTIFACT_DB_USER` → `artifact_db.username`
- `ARTIFACT_DB_PASSWORD` → `artifact_db.password`

**Precedence:** Environment variables override config file values. `config_loader.py` reads the config file first, then applies env var overrides on top. This is consistent with the existing config loading pattern in the codebase.

### Server Startup (`server.py`)

Add `_init_artifact_db()` at startup:

```python
_artifact_db: StandardDatabase | None = None

def _init_artifact_db() -> StandardDatabase | None:
    try:
        db = connect_artifact_db(config["artifact_db"])
        ensure_adr_schema(db)
        return db
    except (ConnectionError, ArangoServerError) as e:
        logger.warning("Artifact DB unavailable: %s", e)
        return None
```

All artifact tool wrappers inject `db=_artifact_db`. If `_artifact_db is None`, tools return:

```json
{"error": "db_unavailable", "message": "ArangoDB unreachable. Check: docker compose ps nomarr-arangodb"}
```

Non-artifact tools (file editing, code analysis, linting) are completely unaffected.

### Docker Integration

- Reuse existing `nomarr-arangodb` container (already in `docker/compose.yaml`)
- `nomarr_artifacts` = separate database in same ArangoDB instance
- No Docker Compose changes needed for development
- Add env vars to `docker/nomarr.env.example` for production documentation:

  ```
  ARTIFACT_DB_URL=http://nomarr-arangodb:8529
  ARTIFACT_DB_NAME=nomarr_artifacts
  ARTIFACT_DB_USER=root
  ARTIFACT_DB_PASSWORD=
  ```

---

## Section 7: Ingest Script

### Location

`code-intel/scripts/ingest_adrs.py`

### Purpose

One-time migration of existing file-based ADRs to ArangoDB. Must be idempotent (safe to re-run).

### Algorithm

1. Connect to artifact DB using config
2. Run `ensure_adr_schema(db)` (idempotent)
3. Read all `artifacts/decisions/ADR-*.md` files
4. Parse each using existing `adr_md.parse_adr()` helper
5. For each parsed ADR:
   a. UPSERT ADR document into `adrs` collection (`_key` = slugified title, `is_draft = false`)
   b. UPSERT each tag into `tags` collection
   c. INSERT `adr_has_tag` edges (skip if edge exists)
   d. Track `supersedes` references for second pass
   e. Track max number seen
6. Second pass: resolve `supersedes` references (e.g., `"ADR-001"` → look up by number → get slug → INSERT `adr_supersedes_adr` edge)
7. Update `sequences/adrs.value` to max number seen (only if current value is lower)
8. Handle drafts in `artifacts/decisions/drafts/DRAFT-*.md` separately: parse, UPSERT with `is_draft: true`, `number: null`
9. Report summary: ADRs ingested, tags created, edges created, errors encountered

### Idempotency

- ADR UPSERT keyed on `_key` (slug) — re-running updates existing docs
- Tag UPSERT keyed on `_key` — safe to re-run
- Edge INSERT with duplicate check (unique compound index on `_from, _to` prevents duplicates; catch `UniqueViolationError` and skip)
- Sequence update uses `MAX(current, scanned)` — never decrements

---

## Section 8: File-Based Code Disposition

### Phase 1 Approach: Hard Cutover

No dual-write. No fallback to files. Once DB tools are deployed:

 | Component | Disposition |
 | ----------- | ------------- |
 | `adr_md.py` helpers | Kept temporarily for ingest script. Deprecated after Phase 1 stabilizes. |
 | `artifacts/decisions/ADR-*.md` files | Kept as read-only archive. No longer written to by tools. |
 | `artifacts/decisions/drafts/` | No longer used. Drafts live in `adrs` collection with `is_draft: true`. |
 | Tool implementations (4 registered tools) | Rewritten to use ArangoDB exclusively via `db_persistence.py` helpers. `adr_create.py` is dead code — not migrated. |
 | `_slugify()` | Moved to `db_persistence.py` (still needed for `_key` generation). |
 | `validate_status()`, `validate_source_log()` | Kept in a shared validation module (used by both old and new code). |
 | `_unescape_literal_newlines()` | Kept (MCP transport concern, not storage concern). |

### Helper Function Disposition (`adr_md.py`)

 | Function | Disposition | Notes |
 | ---------- | ------------ | ------- |
 | `_slugify()` | **move** | Moved to `db_persistence.py` — still needed for `_key` generation |
 | `_unescape_literal_newlines()` | **keep** | MCP transport concern, stays in tool layer or shared utils |
 | `validate_status()` | **keep** | Shared validation, used by DB tools identically |
 | `validate_source_log()` | **keep** | Shared validation, used by DB tools identically |
 | `generate_adr()` | **remove** | Tools write to DB, not markdown. Ingest script reads, not writes. |
 | `parse_adr()` | **ingest-only** | Used by ingest script to read existing files. Not used by tools after migration. |
 | `parse_adr_metadata()` | **ingest-only** | Lightweight version of `parse_adr()` — same disposition. |
 | `next_adr_number()` | **remove** | Replaced by `sequences` collection atomic increment |
 | `make_adr_filename()` | **remove** | No files written — function has no purpose |
 | `today_iso()` | **keep** | Pure utility, still needed for `date` field on insert |
 | `ADR` (dataclass) | **ingest-only** | Used by `parse_adr()` during ingest. Not used by DB tools (they work with dicts). |
 | `ADR_STATUSES` (constant) | **keep** | Used by `validate_status()` |
 | `SOURCE_LOG_PATTERN` (constant) | **keep** | Used by `validate_source_log()` |
 | `DECISIONS_DIR` (constant) | **ingest-only** | Only needed for file-based ingest script |
 | `DRAFTS_DIR` (constant) | **remove** | No draft files in DB mode |
 | `ADR_PREFIX` (constant) | **keep** | Used by `adr_read` input parsing shim (stripping `ADR-` prefix) |
 | `TITLE_PATTERN`, `DRAFT_TITLE_PATTERN`, `META_PATTERN`, `SECTION_PATTERN` (regex) | **ingest-only** | Used by parsers, only needed for ingest |
 | `_STANDARD_SECTIONS` (constant) | **ingest-only** | Used by parsers |

### Failure Mode

If DB is unavailable at startup: `_artifact_db = None`, all ADR tools return `{"error": "db_unavailable", ...}`. No silent fallback to file-based operations. This is intentional — dual-read paths risk serving stale data and complicate debugging.

### Cleanup Timeline

After Phase 1 is stable and ingest has been validated:

1. `adr_md.py` parsing helpers can be removed (ingest script vendors its own copy if ever needed again)
2. `generate_adr()` and `make_adr_filename()` can be removed entirely
3. `next_adr_number()` filesystem scanner removed (replaced by `sequences` collection)

---

## Section 9: Testing Strategy

### Unit Tests

Test each AQL operation pattern against a test database:

- **Tag UPSERT idempotency:** Insert tag "database", UPSERT "database" again → still one vertex
- **Auto-numbering atomicity:** Concurrent sequence increments return unique sequential numbers
- **Search filter combinations:** Status-only, tag-only, query-only, all three, none
- **Supersedes edge creation:** Insert edge, verify old ADR status updated to "Superseded"
- **Draft lifecycle:** suggest (draft) → commit (numbered) → verify `is_draft` flag, `number` assigned
- **Slug generation:** Verify `_slugify()` produces valid ArangoDB `_key` values
- **Read by key vs. read by number:** Both paths return identical results

### Integration Tests

Test full tool round-trips through the MCP tool functions:

- `adr_suggest()` → `adr_commit()` → `adr_search()` → verify data consistency
- `adr_suggest()` → `adr_commit(supersedes=["ADR-001"])` → verify supersedes edge + old ADR status
- Tag deduplication: Two ADRs with overlapping tags → verify shared tag vertices, correct edge counts
- `adr_read()` by number and by slug → verify identical results
- `adr_commit()` (fallback path, no draft_id) → verify creates committed ADR in one step
- Error cases: commit non-existent draft, read non-existent ADR, suggest with duplicate slug

### Ingest Tests

- Run ingest script against the actual `artifacts/decisions/` corpus
- Verify: all ADRs present, all tags present, all supersedes edges present
- Verify: sequence counter equals max ADR number
- Re-run ingest → verify idempotency (no duplicates, no errors)

### Infrastructure Tests

- DB connection failure → tools return `db_unavailable` error
- Schema bootstrap idempotency → `ensure_adr_schema()` called twice, no errors
- Schema bootstrap on empty database → all collections and indexes created

### Test Fixtures

- Dedicated `nomarr_artifacts_test` database, separate from `nomarr_artifacts`
- Created at test session start, dropped at session end
- Each test function gets a clean schema via `ensure_adr_schema()`

---

## Section 10: Design Decisions

### Slug Collision Strategy

**Problem:** Two ADRs with the same title produce the same `_key` (slug). Since `_key` is immutable in ArangoDB, collision must be handled at insert time.

**Decision:** Error on collision and require unique titles.

**Rationale:**

- ADR titles should be unique by nature — they describe distinct decisions
- Appending a number suffix (e.g., `use-onnx-runtime-002`) obscures the slug's meaning
- Appending a timestamp creates unpredictable keys that break human-readable references
- The ingest script may encounter near-duplicate titles from historical ADRs; it should fail loudly so the operator can resolve the conflict manually
- ArangoDB returns `UniqueViolationError` on duplicate `_key` — the tool surfaces this as `{"error": "duplicate_key", "message": "An ADR with slug '{slug}' already exists. Use a more specific title."}`

### Draft Overwrite Semantics

**Problem:** If `adr_suggest` is called twice with the same title (same slug), what happens?

**Decision:** Overwrite the existing draft (UPSERT semantics). Error if a non-draft ADR with that slug already exists.

**Rationale:**

- Current file-based behavior overwrites the same `DRAFT-{slug}.md` file — this preserves that behavior
- Drafts are work-in-progress; overwriting is the expected user intent when re-running `adr_suggest`
- Committed ADRs are protected: if `_key` exists with `is_draft: false`, the tool returns `{"error": "already_committed", "message": "ADR '{slug}' is already committed. Use a different title or edit the existing ADR."}`

**Implementation:** Use UPSERT with a filter:

```aql
UPSERT { _key: @slug }
INSERT { ... all fields ..., is_draft: true }
UPDATE { ... all fields except _key ..., updated_at: @now }
IN adrs
FILTER OLD == null OR OLD.is_draft == true
```

If the UPSERT matches a committed ADR, the UPDATE filter prevents modification and the tool detects this via the return value.

### Error Handling

 | Error Scenario | Detection | Response |
 | ---------------- | ----------- | ---------- |
 | Duplicate `_key` on insert (committed ADR exists) | `UniqueViolationError` or UPSERT filter check | `{"error": "already_committed", "message": "..."}` |
 | Nonexistent supersedes target | Pre-check: `DOCUMENT('adrs', @target_slug)` returns null | `{"error": "supersedes_not_found", "message": "Cannot supersede '{target}': ADR not found"}` |
 | Commit of non-draft or already-committed ADR | Check `is_draft == true` before commit | `{"error": "not_a_draft", "message": "ADR '{slug}' is not a draft or does not exist"}` |
 | Partial failure (vertex inserted, edge insert fails) | Wrap vertex + edge operations in an ArangoDB transaction | Transaction rolled back on any failure — no partial state |
 | Sequence increment without successful commit | Sequence incremented but ADR update fails | **Acceptable gap.** Sequence gaps are harmless — ADR numbers need not be contiguous. The alternative (transactional sequence) adds complexity for no user benefit. |
 | DB connection lost mid-operation | `ArangoServerError` / `ConnectionError` | `{"error": "db_error", "message": "Database operation failed: {details}"}` |

**Transaction scope:** The `adr_commit` operation (sequence increment + document update + supersedes edges) runs inside a single ArangoDB stream transaction. The `adr_suggest` operation (ADR insert/upsert + tag upserts + tag edges) also uses a transaction to prevent orphaned edges.

---

## Design Goals

1. **Validate the graph model.** ADR migration proves that typed edges, shared tag vertices, auto-numbering sequences, and document lifecycle work correctly before migrating the remaining 4 artifact types.
2. **Establish infrastructure.** DB connection factory, config, schema bootstrap, and Docker integration are built once and reused by Phase 2+.
3. **Eliminate fragile patterns.** Replace filesystem-scan numbering (retry-on-collision) with atomic sequence increment. Replace per-file parsing loops with indexed AQL queries.
4. **Maintain tool contract stability.** MCP tool parameters and response shapes change minimally — agents see the same interface with different (better) backing storage.
5. **Hard cutover, not dual-write.** File-based code is deprecated, not maintained in parallel. Complexity of dual-read paths is avoided.

---

## Constraints

1. **ASR #1 — Traversal composition:** Tags and supersedes relationships MUST be resolved via graph traversal, not embedded arrays.
2. **ASR #2 — No foreign keys:** The `adrs` document MUST NOT contain `tags[]` or `supersedes[]` arrays referencing other collections.
3. **ASR #3 — Typed edges:** `adr_has_tag` (adrs→tags) and `adr_supersedes_adr` (adrs→adrs) each have a single, fixed FROM/TO type.
4. **ASR #4 — Stateless edges:** Edge documents contain only `_from` and `_to`. No mutable or filterable fields.
5. **ASR #5 — No polymorphic edges:** Each edge collection serves exactly one relationship type.
6. **Anonymous graph traversal:** Named graphs are not used — `has_tag` edges from multiple source types violate named graph constraints (per existing DD analysis).
7. **Separate database:** `nomarr_artifacts` database, not the nomarr application database.
8. **Hard failure:** If DB unavailable, tools return error. No silent fallback to files.
9. **source_log stays string:** Converts to edge in Phase 2 when Logs migrate.
10. **No ArangoSearch:** Full-text indexing deferred to future optimization phase.

---

## Open Questions

1. ~~**`adr_create` disposition:**~~ **Resolved.** `adr_create.py` is dead code (not registered in `server.py`). Out of scope for Phase 1. The `adr_commit` fallback path already serves the "create without draft" use case.
2. **Markdown export:** Should there be a reverse-export tool that regenerates markdown from DB for git-trackable snapshots? The existing DD proposes `export_artifacts.py` — may be needed if users want artifact markdown in git.
3. **Schema versioning:** Should `db_schema.py` track a schema version for future migrations, or is idempotent ensure-on-startup sufficient for Phase 1?
4. ~~**Concurrent agent access:**~~ **Resolved.** Stream transactions wrap all multi-step operations (suggest, commit, supersede). Sequence increments are atomic. Concurrent agents get unique numbers.

---
