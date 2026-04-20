# Analytics

Pure computation for collection statistics, mood analysis, and tag analytics.

## Responsibilities

- Compute tag frequency distributions and co-occurrence matrices
- Analyze mood coverage, tier balance, and dominant vibes
- Generate collection overview stats (year/genre distributions, file counts)
- Compute per-artist tag profiles

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `analytics_comp` | Tag frequency counting, correlation matrices, co-occurrence analysis, artist tag profiles, dominant vibe computation |
 | `collection_overview_comp` | Library-level stats — total files, year distribution, genre distribution (queries DB directly) |
 | `mood_analysis_comp` | Mood coverage rates, tier balance, top mood pairs, dominant vibes per library (queries DB directly) |

## Patterns

- **Pure computation vs. DB reads:** `analytics_comp` functions are pure — they accept pre-fetched data and return computed results. `collection_overview_comp` and `mood_analysis_comp` accept a `Database` handle and query ArangoDB directly.
- **Optional library filtering:** DB-querying modules accept `library_id` to scope stats to a single library or compute across all.
- **Namespace-aware:** Tag functions work with namespaced key:value format (e.g., `mood-strict:happy`).

## Dependencies

- **Upstream:** Called by analytics services/workflows for dashboard data
- **Downstream:** `collection_overview_comp` and `mood_analysis_comp` call persistence directly (ArangoDB queries)
- **External:** Standard library only (no third-party deps)
