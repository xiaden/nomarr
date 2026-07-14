# PostgreSQL + pgvector Migration — Cross-Plan Audit

**Audited:** 2026-07-13  
**Plans audited:** A (Infra), B (Primitives), C (Core Repos), D (ML Repos), E (Facades), F (Cleanup), G (Testing)  
**Sources:** DD (748 lines), README (parts), CONTRACTS.md (427 lines), 7 plan files

---

## CRITICAL (Must Fix Before Execution)

### 1. Embedding Model Schema Mismatch
**Plans affected:** A, D  
**Issue:** Plan A's Embedding model has `model_id`, `vector_type` (not in DD). Missing `embed_dim`, `model_suite_hash`, `num_segments`, `segmentation_hash` (in DD and DTO). DTO and model don't agree — `insert_embedding()` returns `EmbeddingRecord` but can't populate its fields.  
**Fix:** Align Plan A's Embedding model with DD schema and CONTRACTS.md DTO.

### 2. Plan F Would Delete SQLAlchemy Base
**Plans affected:** F  
**Issue:** Plan F Step P2-S2 says "Delete ArangoDB Pydantic models: remove nomarr/persistence/models/base.py (contains ArangoDocument, ArangoEdge)." But Plan A already replaced base.py with SQLAlchemy 2.x declarative Base. Delete = catastrophic.  
**Fix:** Update Plan F Step P2-S2 to skip base.py.

### 3. Plan F Would Delete SQLAlchemy Tag Model
**Plans affected:** F  
**Issue:** Same stale-description bug. Plan A already created SQLAlchemy Tag in tag.py. Plan F Step P2-S2 would delete it.  
**Fix:** Update Plan F Step P2-S2 to skip tag.py.

### 4. FileStateRepository Missing from Plan C
**Plans affected:** C, E  
**Issue:** Plan E references `get_file_state`, `assign_state`, `bootstrap_states`, etc. — FileStateRepository methods. CONTRACTS.md marks them as "Plan C,E" but Plan C never creates FileStateRepository. Plan E is BLOCKED.  
**Fix:** Add FileStateRepository creation to Plan C.

### 5. EmbeddingStreamRepository Missing from Plan D
**Plans affected:** D, E  
**Issue:** Plan E references `upsert_stream`, `get_stream`, `list_by_backbone`, `delete_for_file` — EmbeddingStreamRepository methods. CONTRACTS.md marks them as "Plan D,E" but Plan D never creates EmbeddingStreamRepository. Plan E is BLOCKED.  
**Fix:** Add EmbeddingStreamRepository creation to Plan D.

### 6. pg_trgm Extension Not Created
**Plans affected:** A  
**Issue:** DD §10 requires `CREATE EXTENSION pg_trgm`. Plan A's migration creates `CREATE EXTENSION vector` but not `pg_trgm`. Plan G tests will fail.  
**Fix:** Add `CREATE EXTENSION IF NOT EXISTS pg_trgm` to Plan A's Alembic migration step.

### 7. Docker Conflict Between Plans A and F
**Plans affected:** A, F  
**Issue:** Plan A Step P1-S1 replaces ArangoDB with PostgreSQL. Plan F Step P2-S6 tries to delete a non-existent ArangoDB service. No-op at best.  
**Fix:** Remove Plan F Step P2-S6 (already done by Plan A).

### 8. insert_embedding() Can't Populate Returned DTO
**Plans affected:** D  
**Issue:** `insert_embedding(file_id, backbone_id, model_id, embedding_vector, genres=None) -> EmbeddingRecord`. But `EmbeddingRecord` has `embed_dim`, `model_suite_hash`, `num_segments`, `segmentation_hash` — not accepted as parameters.  
**Fix:** Compute `embed_dim = len(embedding_vector)`, set remaining fields to None/deferred, OR add parameters.

### 9. Plan E Creates Repo-Layer Methods
**Plans affected:** C, D, E  
**Issue:** ~15 methods in CONTRACTS.md are marked "Plan E" but are repo-layer logic: `truncate_files`, `truncate_folders`, `delete_all_embeddings`, `update_model`, `delete_outputs_for_file`, `truncate_states`, etc. These should be in Plans C/D.  
**Fix:** Move these methods to Plans C/D where the repositories are created.

### 10. Plan E Calls Methods That Don't Exist
**Plans affected:** C, E  
**Issue:** `search_files_by_tag_contains`, `list_all_tag_names`, `count_tags_filtered`, `list_tags_with_song_count`, `get_genre_tags_for_files`, `search_files_by_tag_pattern` — referenced by Plan E, marked "Plan E" in CONTRACTS.md, but never created in any plan.  
**Fix:** Add these methods to Plan C's TagRepository creation steps.

---

## HIGH (Should Fix)

### 11. maintenance_work_mem Not Set Before HNSW Build
**Plans affected:** A  
**Issue:** DD §7 requires `maintenance_work_mem = 2GB` for HNSW builds. Plan A's migration creates the index but doesn't set this parameter. Builds will use 64MB default (hours instead of minutes).  
**Fix:** Add `SET maintenance_work_mem = '2GB'` before HNSW index creation in Plan A's migration step.

### 12. FK Index CI Check Missing
**Plans affected:** A, G  
**Issue:** DD §6/§7: "CI check: every FK column must have a supporting index." No plan implements this verification.  
**Fix:** Add CI check (pytest test or pre-commit hook) to Plan G.

### 13. Legacy ArangoDB Test Files Not Deleted
**Plans affected:** G  
**Issue:** Plan F Step P2-S7 says "test files are Part G scope." Plan G creates new tests but doesn't delete old ArangoDB test files. Dead code in test suite.  
**Fix:** Add Plan G step to delete legacy `tests/**/test_*_aql.py` files.

### 14. DTO Location Inconsistent
**Plans affected:** C, D  
**Issue:** Plan C creates DTOs in `nomarr/persistence/database/repo_dto.py`. Plan D creates DTOs in `nomarr/helpers/dto/`. No canonical location.  
**Fix:** Standardize on `nomarr/helpers/dto/` (helpers layer is for DTOs per architecture conventions).

### 15. Exception Module Name Ambiguous
**Plans affected:** A, B  
**Issue:** CONTRACTS.md says `nomarr.persistence.errors`. Plan A says `nomarr/persistence/exceptions.py`. Plan B imports from `nomarr.persistence.exceptions`.  
**Fix:** Verify actual module name in codebase, standardize references.

### 16. Plan D Forward Reference
**Plans affected:** D  
**Issue:** Step 1 imports DTOs from Step 5. DTO file doesn't exist yet at Step 1.  
**Fix:** Reorder: DTO creation (current Step 5) → before skeleton (current Step 1).

### 17. Plan F Components Scope Contradiction
**Plans affected:** F  
**Issue:** "Out of scope: Components layer (65+ files)." But Step P1-S7 says "Audit and update components layer." Contradiction.  
**Fix:** Remove "Out of scope" statement. Components ARE in scope.

### 18. Plan E Steps Truncated
**Plans affected:** E  
**Issue:** Steps 2-5, 7-8, 10-11 are truncated in the plan file. Can't fully verify method mappings.  
**Fix:** Expand truncated steps with full method names.

---

## LOW / Optional

- **DD §4 recursive CTEs** — deferred to V2 per Plan F. No action needed.
- **tag_interactions/tag_calibrations tables** — in DD appendix but not in schema section. Verify and add to Plan A if needed.
- **Recursive CTE tests** — not needed for V1.
- **unaccent extension** — not required by DD. Skip.
- **Facade integration tests** — repos are tested in Plan G; facades are thin pass-throughs.

---

## DD Section Coverage Summary

| DD Section | Coverage | Gaps |
|---|---|---|
| §1 Scope/Problem/Goals/Constraints | ✅ | None |
| §2 Architecture & Decisions | ⚠️ | maintenance_work_mem, pg_trgm not implemented |
| §3 Schema & Relationships | ⚠️ | Embedding model mismatch, tag_interactions/tag_calibrations missing |
| §4 Vector Design | ⚠️ | Recursive CTEs deferred to V2 |
| §5 Persistence & Repository Architecture | ✅ | All layers covered |
| §6 Migration & Implementation Strategy | ⚠️ | FK index CI check missing |
| §7 Risks & Mitigations | ⚠️ | FK CASCADE deadlock check, pg_trgm short-string risk not addressed |
| §8 Testing & Acceptance Criteria | ⚠️ | Legacy test cleanup missing |
| §9 Resolved Decisions | ✅ | All applied |
| §10 Appendix | ⚠️ | pg_trgm extension, tag_interactions/tag_calibrations |

---

**Audit by:** Exec-Planner (ses_0a1475d8dffe0NS4wjDcN6hy8P)  
**Total issues:** 10 CRITICAL + 10 HIGH + 5 LOW = 25
