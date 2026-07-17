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
| 1 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_init_default_device` | BEHAVIOR | Tests legitimate cache initialization. Mock data is correct; source had broken `async __init__` (fixed in Part A). Tests need factory pattern update (`ONNXModelCache.create()`). | | PENDING |
| 2 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_init_with_db` | BEHAVIOR | Tests legitimate cache init with database. Needs factory pattern update. | | PENDING |
| 3 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_init_model_discovery` | BEHAVIOR | Tests legitimate model discovery (backbones + heads). Needs factory pattern update. | | PENDING |
| 4 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_init_no_db` | BEHAVIOR | Tests legitimate NO-DB code path. Needs factory pattern update. | | PENDING |
| 5 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheInit::test_init_model_discovery_no_db` | BEHAVIOR | Tests legitimate NO-DB model discovery. Needs factory pattern update. | | PENDING |
| 6 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheModelCount::test_model_count_from_backbones_and_heads` | BEHAVIOR | Tests legitimate model counting logic (sum of backbones + heads). Mock data is correct; source had broken `async __init__` (fixed in Part A). Tests need factory pattern update. | | PENDING |
| 7 | `tests/unit/components/ml/onnx/test_ml_cache.py` | `TestONNXModelCacheModelCount::test_model_count_empty_cache` | BEHAVIOR | Tests legitimate empty-cache counting. Needs factory pattern update. | | PENDING |
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
