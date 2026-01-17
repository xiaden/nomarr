# Documentation Audit Report

**Generated:** January 17, 2026  
**Scope:** SQLite → ArangoDB migration verification, outdated references, and general documentation quality  
**Last Updated:** January 17, 2026 (post initial fixes)

---

## Executive Summary

The project migrated from **SQLite to ArangoDB** but many documentation files still contain SQLite-specific references, SQL syntax examples, configuration paths, and outdated concepts. This audit identifies specific issues requiring updates.

**Overall Status:**
- Files reviewed: 18
- Files fully fixed: 4 (queues.md, architecture.md, api_reference.md, navidrome.md)
- Files partially fixed: 2 (getting_started.md, deployment.md)
- Files still needing updates: 6 (health.md, services.md, workers.md, calibration.md, statebroker.md)
- Files OK (no changes needed): 6 (index.md, naming.md, qc.md, versioning.md, mui-integration.md, modelsinfo.md)
- Critical remaining issues: SQLite CLI commands in health.md, outdated Database construction patterns

**Fixes Applied Today (Jan 17):**
- ✅ docs/dev/queues.md - Updated schema, concurrency, debugging sections
- ✅ docs/dev/architecture.md - Updated persistence examples and worker connections
- ✅ docs/user/getting_started.md - Updated database troubleshooting section
- ✅ docs/user/deployment.md - Updated backup and optimization sections
- ✅ docs/user/api_reference.md - Removed db_path from config response
- ✅ docs/user/navidrome.md - Updated flow diagram

---

## File-by-File Audit

### docs/index.md

**Status:** `OK`

**Notes:**
- No SQLite references
- References to other docs are valid
- Lidarr reference on line 59 may want to be generalized but is a minor concern

---

### docs/dev/naming.md

**Status:** `OK`

**Notes:**
- Generic naming standards, no database-specific content
- Well-structured and up-to-date

---

### docs/dev/queues.md

**Status:** `PARTIALLY_FIXED`

**Fixed Today:**
- ✅ Added note at top about SQL being conceptual
- ✅ Updated schema section to show ArangoDB document format
- ✅ Updated concurrency section with AQL examples
- ✅ Updated debugging section with arangosh commands

**Remaining Issues:**

| Line | Issue | Details |
|------|-------|---------|
| 112-127 | SQL CREATE INDEX syntax | Should show AQL index creation or note these are conceptual |
| 200-246 | SQL UPDATE/INSERT examples | Marked as conceptual but could be updated to AQL |
| 340 | Lidarr reference | Minor - could be generalized to "webhooks" |
| 734 | Port 8888 in curl example | Should be 8356 (INTERNAL_PORT) |

**Recommended Action:** Lower priority - most critical sections already fixed.

---

### docs/dev/qc.md

**Status:** `OK`

**Notes:**
- Generic QC processes
- No database-specific content
- Security section mentions "parameterized queries" with SQL example (line ~150) - minor, conceptually valid

---

### docs/dev/versioning.md

**Status:** `OK`

**Notes:**
- Versioning strategy is database-agnostic
- No SQLite references

---

### docs/user/navidrome.md

**Status:** `FIXED`

**Fixed (Commit 274df7f):**
- ✅ Updated integration flow diagram to show ArangoDB container
- ✅ Document correctly references "Tag Storage (ArangoDB)"

**Remaining Issues (Low Priority):**

| Line | Issue | Details |
|------|-------|---------|
| 649, 653, 662 | Port 8888 in examples | These are the public/external ports, may be intentional |

**Notes:** The internal port is 8356, but 8888 may be the mapped public port in docker-compose.

---

### docs/user/getting_started.md

**Status:** `PARTIALLY_FIXED`

**Fixed (Commit 274df7f):**
- ✅ Database troubleshooting updated for ArangoDB
- ✅ Config reference shows ArangoDB password storage

**Remaining Issues:**

| Line | Issue | Details |
|------|-------|---------|
| 114 | `database: path: "/data/nomarr.db"` | **CRITICAL**: SQLite path config - should be ArangoDB connection config |
| 141 | Port 8888 | Verify correct port |
| 164 | Port mapping `8888:8888` | Verify correct port |
| 294 | `path: "./data/nomarr.db"` | **CRITICAL**: SQLite path - should be ArangoDB config |
| 555 | `docker exec -it nomarr ls -l /data/nomarr.db` | **CRITICAL**: SQLite file check - should be ArangoDB health check |

**Recommended Action:** Replace all SQLite database configuration with ArangoDB connection settings (ARANGO_HOST, arango_password in config, etc.).

---

### docs/user/deployment.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 187 | `database: path: "/data/nomarr.db"` | **CRITICAL**: SQLite config |
| 189 | `wal_mode: true` | **CRITICAL**: SQLite WAL mode - not applicable to ArangoDB |
| 249 | `database.wal_mode: Improves concurrent access` | **CRITICAL**: SQLite concept |
| 644 | `DB_PATH="/opt/nomarr/data/nomarr.db"` | **CRITICAL**: SQLite backup path |
| 652 | `cp "$DB_PATH"` backup command | **CRITICAL**: SQLite file backup - ArangoDB needs different backup strategy |
| 874 | `cp .../nomarr_YYYYMMDD.db` | **CRITICAL**: SQLite restore |
| 160 | Port 8888 | Verify consistent port usage |

**Recommended Action:** 
1. Replace SQLite config with ArangoDB connection settings
2. Update backup/restore procedures for ArangoDB (arangodump/arangorestore)
3. Remove WAL mode references
4. Add docker-compose service for ArangoDB container

---

### docs/user/api_reference.md

**Status:** `FIXED`

**Fixed (Commit 274df7f):**
- ✅ Updated config endpoint response to show `arango_password` instead of SQLite config

**Remaining Issues (Low Priority):**

| Line | Issue | Details |
|------|-------|---------|
| 12 | Base URL `http://localhost:8356/api` | Port 8356 is correct per config_svc.py |
| 3 | "Lidarr" in audience | Minor - could be generalized |
| 662-750 | Lidarr Integration section | Consider renaming to "Webhook Integration" |

**Notes:** Main config endpoint response is now accurate. Lidarr references are low priority.

---

### docs/dev/statebroker.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 27 | "SQLite WAL mode ensures safe concurrent access" | **CRITICAL**: SQLite concept - ArangoDB uses different concurrency |
| 414 | Port 8356 | Inconsistent port |

**Recommended Action:** Update IPC description to reflect ArangoDB's concurrency model instead of SQLite WAL.

---

### docs/dev/services.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 607-608 | `db_path: str` / `Database(db_path)` | **CRITICAL**: SQLite path-based construction - ArangoDB uses connection params |
| 938-939 | `sqlite3.Row` return type example | **CRITICAL**: SQLite type reference |

**Recommended Action:** Update Database construction examples to use ArangoDB connection pattern.

---

### docs/dev/mui-integration.md

**Status:** `OK`

**Notes:**
- Frontend MUI documentation
- No database or backend references
- Well-structured

---

### docs/dev/health.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 27-45 | SQL CREATE TABLE syntax | Should be ArangoDB collection schema (JSON) |
| 322 | "not enforced by SQLite" | SQLite reference |
| 363 | "SQLite row-level locking via WAL mode" | **CRITICAL**: SQLite concept |
| 465-466 | `sqlite3 /data/nomarr.db` CLI example | **CRITICAL**: Should be arangosh commands |
| 471 | `Database('/data/nomarr.db')` | **CRITICAL**: SQLite path construction |
| 498 | `sqlite3 ... UPDATE` command | **CRITICAL**: Should be AQL/arangosh |
| 505-510 | `sqlite3` commands | **CRITICAL**: Should be arangosh |
| 547 | `sqlite3 /data/nomarr.db ".timeout 1000"` | **CRITICAL**: SQLite debugging - needs ArangoDB equivalent |

**Recommended Action:** Complete rewrite of debugging section with ArangoDB/arangosh commands. Update schema to show ArangoDB document structure.

---

### docs/dev/calibration.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 29-47 | SQL CREATE TABLE with INTEGER PRIMARY KEY AUTOINCREMENT | **CRITICAL**: SQLite syntax - should be ArangoDB collection/document |
| 46 | "SQLite boolean" note | SQLite reference |
| 292 | "is 0 (false) or 1 (true) in SQLite" | SQLite-specific behavior |
| 431 | `sqlite3 config/db/essentia.sqlite` | **CRITICAL**: SQLite CLI command |

**Recommended Action:** Update schema to ArangoDB document format. Update CLI examples to use arangosh.

---

### docs/dev/architecture.md

**Status:** `FIXED`

**Fixed (Commit 274df7f):**
- ✅ Updated Database construction to show ArangoDB connection pattern (hosts keyword)
- ✅ Updated persistence examples to show `db.queue` access pattern

**Notes:** Architecture document now correctly shows ArangoDB patterns.

---

### docs/dev/workers.md

**Status:** `NEEDS_UPDATE`

**Issues Found:**

| Line | Issue | Details |
|------|-------|---------|
| 52 | "Each worker must create its own SQLite connection" | **CRITICAL**: SQLite connection advice |
| 273 | Port 8356 | Verify port consistency |
| 341 | "Multiprocessing safety (SQLite WAL mode)" | **CRITICAL**: SQLite concept |

**Recommended Action:** Update database connection guidance for ArangoDB (python-arango handles connection pooling differently).

---

### docs/upstream/modelsinfo.md

**Status:** `OK`

**Notes:**
- Upstream reference documentation (marked as non-canonical)
- No Nomarr-specific database references
- Appropriate disclaimers present

---

### docs/dev/TEST_COVERAGE_ANALYSIS.md

**Status:** `FILE_NOT_FOUND`

**Notes:** This file does not exist in the docs/dev/ directory.

---

### docs/dev/WORKER_SYSTEM_REFERENCE.md

**Status:** `FILE_NOT_FOUND`

**Notes:** This file does not exist in the docs/dev/ directory.

---

## Summary of Critical Issues

### 1. SQLite Database Configuration (CRITICAL)

**Affected Files:**
- docs/user/getting_started.md (lines 114, 294, 555)
- docs/user/deployment.md (lines 187, 189, 249, 644, 652, 874)
- docs/dev/services.md (lines 607-608)
- docs/dev/architecture.md (lines 261, 381)

**Current Pattern:**
```yaml
database:
  path: "/data/nomarr.db"
  wal_mode: true
```

**Should Be:**
```yaml
# ArangoDB connection is configured via environment variables:
# - ARANGO_HOST: http://nomarr-arangodb:8529
# - ARANGO_ROOT_PASSWORD: (for initial setup)
# - arango_password in config.yaml for runtime

# In config.yaml:
arango_password: "your-secure-password"
```

### 2. SQLite CLI Commands (CRITICAL)

**Affected Files:**
- docs/dev/health.md (lines 465-547)
- docs/dev/calibration.md (line 431)

**Current Pattern:**
```bash
sqlite3 /data/nomarr.db "SELECT * FROM health;"
```

**Should Be:**
```bash
# Using arangosh:
docker exec -it nomarr-arangodb arangosh --server.password <password> --javascript.execute-string 'db.health.toArray()'

# Or using Python:
docker exec -it nomarr python -c "
from nomarr.persistence.db import Database
db = Database()
for doc in db.health.get_all_workers():
    print(doc)
"
```

### 3. SQLite WAL Mode References (CRITICAL)

**Affected Files:**
- docs/user/deployment.md (lines 189, 249)
- docs/dev/statebroker.md (line 27)
- docs/dev/workers.md (line 341)
- docs/dev/health.md (line 363)
- docs/dev/queues.md (line 899)

**Action:** Remove all WAL mode references. ArangoDB uses a different transaction and concurrency model.

### 4. Inconsistent Port Numbers (MODERATE)

**Found Ports:**
- `8356` - api_reference.md (Base URL), statebroker.md, workers.md, some other examples
- `8888` - getting_started.md, deployment.md, navidrome.md, health.md, queues.md

**Code Reference:** `INTERNAL_PORT = 8356` in config_svc.py

**Action:** Determine canonical port and standardize across all documentation.

### 5. Lidarr-Specific References (MINOR)

**Affected Files:**
- docs/index.md (line 59)
- docs/user/api_reference.md (lines 3, 662-750)
- docs/dev/queues.md (line 340)

**Action:** Consider generalizing to "webhook integration" or "media manager integration" to be more inclusive of other tools.

### 6. SQL Schema Examples (MODERATE)

**Affected Files:**
- docs/dev/queues.md (CREATE INDEX examples)
- docs/dev/health.md (CREATE TABLE example)
- docs/dev/calibration.md (CREATE TABLE example)

**Action:** Either:
1. Replace with ArangoDB collection/index definitions, or
2. Add clear notes that these are conceptual illustrations (like queues.md line 7)

---

## Recommended Priority Order

1. **HIGH PRIORITY** - Update database configuration examples in user docs (getting_started.md, deployment.md)
2. **HIGH PRIORITY** - Update debugging commands in health.md (SQLite CLI → arangosh/Python)
3. **HIGH PRIORITY** - Standardize port numbers across all docs
4. **MEDIUM PRIORITY** - Update services.md and architecture.md Database construction patterns
5. **MEDIUM PRIORITY** - Update calibration.md schema and CLI examples
6. **MEDIUM PRIORITY** - Add ArangoDB container to docker-compose examples
7. **LOW PRIORITY** - Generalize Lidarr references
8. **LOW PRIORITY** - Update SQL schema examples to ArangoDB format or add disclaimers

---

## Files Requiring No Changes

- docs/index.md
- docs/dev/naming.md
- docs/dev/qc.md
- docs/dev/versioning.md
- docs/dev/mui-integration.md
- docs/upstream/modelsinfo.md

---

## Missing Files

The following requested files do not exist:
- docs/dev/TEST_COVERAGE_ANALYSIS.md
- docs/dev/WORKER_SYSTEM_REFERENCE.md

These may need to be created or were previously removed/renamed.
