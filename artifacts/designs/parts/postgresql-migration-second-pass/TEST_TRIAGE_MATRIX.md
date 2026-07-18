# Test Triage — Light: Traceability Matrix

**Part:** B — Test Triage — Light
**Design doc:** `artifacts/designs/pending/DD-postgresql-migration-second-pass.md`
**Plan:** `TASK-postgresql-migration-second-pass-B-test-triage-light`

## Classification Summary

**Result:** 15 BEHAVIOR, 0 ARANGO. No tests to delete.

All xfailed tests exercise legitimate business logic that must be preserved. Each requires a rewrite against production PostgreSQL APIs (Part G) rather than deletion.

---

## Traceability Matrix

| # | Test File | Test Name / Method | Classification | Rationale | Reviewer | Review Status |
|---|-----------|--------------------|----------------|-----------|----------|---------------|
| 1 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_no_models_dir_produces_empty_cache` | BEHAVIOR | Tests legitimate cache initialization with empty models dir. Mock data is correct; source had broken `async __init__` (fixed in Part A). Tests need factory pattern update (`ONNXModelCache.create()`). | | PENDING |
| 2 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_with_db_calls_discover_head_models_not_no_db` | BEHAVIOR | Tests that DB path uses `discover_head_models` (not `_no_db` variant). Needs factory pattern update. | | PENDING |
| 3 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_heads_grouped_by_meta_backbone` | BEHAVIOR | Tests legitimate head model grouping by backbone. Needs factory pattern update. | | PENDING |
| 4 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_without_db_calls_discover_head_models_no_db` | BEHAVIOR | Tests NO-DB path calls `discover_head_models_no_db`. Needs factory pattern update. | | PENDING |
| 5 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_heads_from_same_backbone_grouped_together` | BEHAVIOR | Tests same-backbone heads are grouped correctly. Needs factory pattern update. | | PENDING |
| 6 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheModelCount::test_model_count_sums_backbones_and_heads` | BEHAVIOR | Tests legitimate model counting logic (sum of backbones + heads). Mock data is correct; source had broken `async __init__` (fixed in Part A). Tests need factory pattern update. | | PENDING |
| 7 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheModelCount::test_model_count_is_zero_for_empty_cache` | BEHAVIOR | Tests legitimate empty-cache counting returns zero. Needs factory pattern update. | | PENDING |
| 8 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_interleave_clusters_exhausted_returns_partial` (line ~196) | BEHAVIOR | Tests legitimate interleave logic when clusters exhaust before target_size. Assertion format mismatch (`{"a1", "b1"}` vs actual dict return). Business logic is valid. | | PENDING |
| 9 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_familiar_multiple_clusters_proportional_mix` (line ~288) | BEHAVIOR | Tests legitimate proportional cluster mixing. Uses string IDs (`f"f{i}"`) that may not match production int ID expectations. Business logic is valid. | | PENDING |
| 10 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_hidden_gems_empty_cold_collection_returns_empty` (line ~369) | BEHAVIOR | Tests legitimate edge case (empty cold collection → empty result). Mock patch target may need update for production API. Business logic is valid. | | PENDING |
| 11 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_hidden_gems_no_known_artists_skips_artist_filter` (line ~386) | BEHAVIOR | Tests legitimate artist-filter fallback behavior. Mock patch targets (`get_distinct_tag_values_for_files`) need update for production tag query API. Business logic is valid. | | PENDING |
| 12 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_hidden_gems_known_artists_excludes_artist_tracks` (line ~412) | BEHAVIOR | Tests legitimate artist exclusion logic. Mock data and patch targets need update for production API. Business logic is valid. | | PENDING |
| 13 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | `test_hidden_gems_both_played_and_artist_exclusion` (line ~449) | BEHAVIOR | Tests legitimate combined played+artist exclusion. Mock data and patch targets need update for production API. Business logic is valid. | | PENDING |
| 14 | `tests/unit/components/tagging/test_tag_stats_comp.py` | `test_returns_year_rows_sorted_descending_and_excludes_zero_counts` (line ~265) | BEHAVIOR | Tests legitimate year distribution sorting and zero-count exclusion. Mock data uses ArangoDB string IDs (`"tags/2019"`) but production `get_year_distribution` expects `isinstance(tag_id, int)`. Business logic is valid; mock data needs PostgreSQL int IDs. | | PENDING |
| 15 | `tests/unit/components/tagging/test_tag_stats_comp.py` | `test_returns_rows_sorted_by_count_desc_then_genre_and_respects_limit` (line ~312) | BEHAVIOR | Tests legitimate genre distribution sorting, grouping, and limit enforcement. Mock data uses ArangoDB graph edges (`_to`/`_from`) but production `_song_count_rows_for_tag_ids` expects `edge.get("tag_id")`. Business logic is valid; mock data needs PostgreSQL junction patterns. | | PENDING |

---

## Notes

- **Class-level xfails:** `test_ml_cache.py` uses class-level `@pytest.mark.xfail` decorators. Each test method is listed individually in this matrix because each tests distinct behavior.
- **Reviewer column:** Populated during buddy review.
- **Review Status:** `PENDING` → `APPROVED` / `REJECTED` after buddy review.
- **Next step:** All 15 tests are marked `@pytest.mark.skip(reason="Rewrite pending Part G")` per Part B scope. Actual rewrites happen in Part G (Test Edge-Case Extraction).

---

## Part G Execution Summary

**Plan:** `TASK-postgresql-migration-second-pass-G-test-edge-case-extraction`
**Execution date:** 2026-07-17
**Status:** ✅ COMPLETE

### Tests Rewritten and Verified

All 15 BEHAVIOR tests were rewritten and verified passing:

| # | Test File | Tests Rewritten | Phase | Status |
|---|-----------|-----------------|-------|--------|
| 1–7 | `tests/unit/components/ml/onnx/test_ml_cache.py` | 7 tests (2 classes: TestONNXModelCacheInit × 5, TestONNXModelCacheModelCount × 2) | Phase 2 | ✅ PASS |
| 8–13 | `tests/unit/components/navidrome/test_playlist_builder_comp.py` | 6 tests (interleave, familiar, hidden_gems × 4) | Phase 3 | ✅ PASS |
| 14–15 | `tests/unit/components/tagging/test_tag_stats_comp.py` | 2 tests (year distribution, genre distribution) | Phase 4 | ✅ PASS |

**Verification results (P5-S1):**
- 3 target files: 65 passed, 2 failed (pre-existing, outside Part G scope), 0 skipped, 0 xfailed
- All 15 Part G target tests: ✅ PASS
- Full test suite (P5-S2): 1829 passed, 26 failed (all pre-existing), 15 skipped, 0 xfailed
- Zero new regressions introduced

### Rewrite Changes Summary

| File | Key Changes |
|------|-------------|
| `test_ml_cache.py` | `ONNXModelCache(...)` → `ONNXModelCache.create(...)` (factory pattern from Part A). Removed 2 class-level `@pytest.mark.skip` decorators. |
| `test_playlist_builder_comp.py` | Mock data: string IDs → appropriate types (string file_ids for `_interleave_per_cluster`, integer played_file_ids for `build_familiar_playlist`). Sync lambdas → `AsyncMock` for async functions. Int assertions → string assertions for `file_ids: list[str]`. Removed 6 function-level `@pytest.mark.skip` decorators. |
| `test_tag_stats_comp.py` | ArangoDB string tag IDs (`"tags/2019"`) → integer tag IDs. ArangoDB graph edges (`_to`/`_from`) → PostgreSQL junction format (`tag_id` field). Mock target: `file_tag_repo.get_file_tag_edges_for_tags` → `list_file_tag_edges` (intent facade). Removed 2 function-level `@pytest.mark.skip` decorators. |

---

## Buddy Review Status

**Status:** ⏳ PENDING — requires human reviewer

Buddy review has not yet been performed. A human developer must review all 15 test rewrites.

### Reviewer Instructions

The reviewer should check each rewritten test for:

1. **Test uses production API correctly:** Verify that mock patch targets match the actual production call sites (e.g., `ONNXModelCache.create()` not `ONNXModelCache()`, `list_file_tag_edges` not `file_tag_repo.get_file_tag_edges_for_tags`, `AsyncMock` for async functions).

2. **Test data is realistic:** Verify that mock data shapes match what production code actually receives (e.g., integer tag IDs not ArangoDB string paths, `tag_id` field not `_to`/`_from` graph edges, string file_ids where production expects strings).

3. **Assertions verify behavior not implementation:** Verify that assertions test the observable behavior (return values, side effects) rather than internal implementation details (specific mock call counts, private method invocations).

### Review Checklist

For each test in the traceability matrix above (rows 1–15):
- [ ] Mock patch targets match production call sites
- [ ] Mock data shapes match production DTOs
- [ ] Async functions use `AsyncMock` (not sync lambdas)
- [ ] Assertions test behavior, not implementation
- [ ] No ArangoDB field names (`_id`, `_key`, `_to`, `_from`) in mock data
- [ ] Test passes in isolation (`pytest -k <test_name>`)

**Reviewer:** _______________ (pending)
**Review date:** _______________ (pending)
**Review status:** PENDING

---

## 20% Audit Sampling

**Status:** ⏳ PENDING — requires senior developer

### Sampling Protocol

Per the design document, 20% of rewritten tests (2 out of 15, rounded up from 3 → 2 per plan) must be randomly selected for deep review by a senior developer.

**Selection method:** Random selection from the 15 tests in the traceability matrix.

**Selected tests:** _______________ (pending — to be selected by senior developer)

**Deep review scope:**
- Full trace from test mock → production call site → return value → assertion
- Verify no mock/production API mismatch
- Verify test data covers edge cases mentioned in test name
- Verify assertion correctness against production return types

**Auditor:** _______________ (pending)
**Audit date:** _______________ (pending)
**Audit status:** PENDING

---

## Notes for Human Reviewer

### Key Discoveries from Execution

1. **Mock level matters:** Production code calls `db.library.list_file_tag_edges()` (intent facade), but some pre-existing tests mock `db.library.file_tag_repo.get_file_tag_edges_for_tags` (repo level). With `AsyncMock()`, the mock doesn't auto-delegate, causing empty results. The 2 Part G tag_stats tests mock `list_file_tag_edges` directly — the correct level.

2. **String vs int file_ids:** `_interleave_per_cluster` only keeps string file_ids (has `isinstance(fid, str)` check). `build_familiar_playlist` does `int(fid)` on played_file_ids. Different production functions expect different ID types — tests must match.

3. **AsyncMock required:** `get_distinct_tag_values_for_files` and `get_tag_values_grouped_by_file` are async functions. All hidden_gems tests needed `AsyncMock` instead of sync lambdas.

4. **Pre-existing failures outside Part G scope:** 2 tests in `test_tag_stats_comp.py` (TestGetTagValueCounts, TestGetAllTagStatsBatched) and 8 tests in other files mock at the wrong level. These are documented for future fix but are NOT Part G scope.
