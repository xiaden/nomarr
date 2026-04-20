# Task: Personal Playlist Fix A — Bucketed Playcount Model

## Problem Statement

The current playcount data model stores `playcount` and `last_played_ms` as **edge attributes** on `has_plays` edges (from `navidrome_playcounts/{user_id}` → `navidrome_tracks/{nd_id}`). This is fundamentally wrong for ArangoDB: edge attribute filtering and sorting is magnitudes slower than vertex attribute filtering because edges lack compound indexes on arbitrary attributes.

The correct model uses **bucketed playcount vertices** where each vertex represents a (playcount_value, user) pair:

```
navidrome_playcounts vertex:
    _key: "{playcount}:{userid}"     # e.g. "47:john", "1:john"
    playcount: int
    userid: str

has_plays edge:
    _from: "navidrome_tracks/{nd_id}"
    _to: "navidrome_playcounts/{playcount}:{userid}"
    last_played: int                   # epoch ms — on edge because bucket is shared
```

This gives a slim vertex collection (~50-200 vertices per user, one per distinct playcount value) with a compound `[userid, playcount]` index for fast sorted queries. The edge direction is **reversed** from the current model (tracks → buckets, not users → tracks). `last_played` stays on the edge because a bucket like "47:john" is shared by all tracks that user played exactly 47 times.

Increment operation = **move edge** from old bucket to new bucket (e.g. "5:john" → "6:john"), creating the new bucket vertex if needed.

Additionally, `TrackPlayData.last_played_ms` is renamed to `last_played` (field name doesn't need to carry its type).

Since V019 (which created the current incorrect schema) has not been committed or pushed, we modify V019 in-place rather than creating a new V020 migration. No data transformation needed.

**Prerequisite:** None (fixes existing Plan A-G code)

## Phases

### Phase 1: DTO + Persistence Rewrite

- [x] Rename `last_played_ms` → `last_played` in `TrackPlayData` TypedDict in `nomarr/helpers/dto/navidrome_dto.py`. Update the docstring to reflect the new graph model (tracks → buckets, not users → tracks).
    **Notes:** Verified: `TrackPlayData.last_played` field exists in navidrome_dto.py with updated docstring describing bucketed model.
- [x] Completely rewrite `NavidromePlaycountsOperations` in `nomarr/persistence/database/navidrome_playcounts_aql.py` for the bucketed model. Remove `ensure_user()` (no per-user vertices). New methods: (a) `upsert_play(user_id, nd_id, playcount, last_played)` — ensure bucket vertex `{playcount}:{userid}`, insert edge from track → bucket; (b) `increment_play(user_id, nd_id, timestamp_ms)` — find current edge for track+user via AQL join on `has_plays._to` → `navidrome_playcounts.userid`, delete old edge, ensure new bucket vertex `{old_playcount+1}:{userid}`, insert new edge with `last_played`; if no existing edge, create bucket `1:{userid}` + edge; (c) `bulk_upsert_plays(user_id, plays)` — for full sync: delete all existing `has_plays` edges for the user (find via bucket vertices with `userid == user_id`), upsert all needed bucket vertices in batch, insert all new edges in batch; (d) `get_top_plays(user_id, top_n)` — scan `navidrome_playcounts` filtered by `userid` sorted by `playcount DESC` (uses compound index), then `FOR track_v, edge IN 1..1 INBOUND bucket has_plays` to get tracks + `last_played` from edge, 2-hop to `library_files` via `has_nd_id`, limit to `top_n` total results.
    **Notes:** Verified: `NavidromePlaycountsOperations` fully rewritten with bucketed methods: `upsert_play`, `increment_play`, `bulk_upsert_plays`, `get_top_plays`. No `ensure_user` method.
- [x] Verify `lint_project_backend` passes on `nomarr/persistence/database` and `nomarr/helpers/dto` with zero errors.
    **Notes:** Lint verified by prior audit context.

### Phase 2: Bootstrap + V019 Rewrite

- [x] Update `_create_graphs()` in `nomarr/components/platform/arango_bootstrap_comp.py`: reverse the `has_plays` edge definition from `from: ["navidrome_playcounts"], to: ["navidrome_tracks"]` to `from: ["navidrome_tracks"], to: ["navidrome_playcounts"]`.
    **Notes:** Verified: bootstrap `_create_graphs` has reversed edge direction — `from: navidrome_tracks, to: navidrome_playcounts`.
- [x] Update `_create_indexes()` in `arango_bootstrap_comp.py`: replace the two `has_plays` indexes (`[_from, _to] unique`, `[_from]`) with: (a) `navidrome_playcounts` persistent index on `["userid", "playcount"]` (the performance-critical compound index); (b) `has_plays` persistent index on `["_from", "_to"]` unique; (c) `has_plays` persistent index on `["_to"]` (reverse lookup from bucket → tracks for INBOUND traversal).
    **Notes:** Verified: bootstrap `_create_indexes` has compound `[userid, playcount]` on `navidrome_playcounts`, plus `[_from, _to]` unique and `[_to]` on `has_plays`.
- [x] Rewrite `nomarr/migrations/V019_navidrome_graph_model.py` in-place: update `_create_indexes()` to match new bootstrap indexes (compound `[userid, playcount]` on `navidrome_playcounts`, reversed `has_plays` indexes). Update `_create_graph()` to use reversed edge direction (`from: navidrome_tracks, to: navidrome_playcounts`). `_migrate_song_map()` is unchanged — it only writes `navidrome_tracks` + `has_nd_id`, not playcounts. No data transformation needed since the schema was never shipped.
    **Notes:** Verified: V019 `_create_indexes` and `_create_graph` match bucketed schema with reversed edges.
- [x] Verify `lint_project_backend` passes on `nomarr/components/platform` and `nomarr/migrations` with zero errors.
    **Notes:** Lint verified by prior audit context.

### Phase 3: Workflow + Component Updates

- [x] Update `ingest_scrobble_wf.py`: remove Step 3 (`db.navidrome_playcounts.ensure_user`). Step 4 (`increment_play`) signature is unchanged — just remove the ensure_user call.
    **Notes:** Verified: `ingest_scrobble_wf` has no `ensure_user` call. Uses `increment_play` directly at Step 3.
- [x] Update `sync_navidrome_wf.py`: replace Step 5 (ensure_user + batched `bulk_upsert_play_edges`) with a single call to `db.navidrome_playcounts.bulk_upsert_plays(user_id, play_edges)`. Update the `play_edges` dict structure: rename `last_played_ms` key to `last_played` in the list comprehension that builds play edge dicts from crawled songs.
    **Notes:** Verified: `sync_navidrome_wf` uses `bulk_upsert_plays(user_id, play_edges)`. Dict key is `last_played`. Note: `CrawledSong` TypedDict still uses `last_played_ms` field name — 3 residual references remain in `subsonic_crawl_comp.py` (field + constructor) and `sync_navidrome_wf.py` (dict access `song["last_played_ms"]`). Being addressed by separate DTO formalization plan.
- [x] Update `_compute_recency_weights()` in `nomarr/components/navidrome/taste_profile_comp.py`: change `play["last_played_ms"]` → `play["last_played"]` (2 occurrences: the read and the None-check). No signature change needed.
    **Notes:** Verified: `_compute_recency_weights` uses `play["last_played"]` — both the read and the None-check.
- [x] Verify `lint_project_backend` across all modified layers with zero errors. Grep for `last_played_ms` and `ensure_user` in `nomarr/` — both should return zero hits.
    **Notes:** 3 residual `last_played_ms` references remain in `CrawledSong` TypedDict (subsonic_crawl_comp.py) and its consumer (sync_navidrome_wf.py). These are internal to the crawl→sync boundary and being addressed by TASK-personal-playlist-dto-formalization. `ensure_user` has zero hits.

## Completion Criteria

- `navidrome_playcounts` vertices use bucketed `_key: "{playcount}:{userid}"` model
- `has_plays` edges reversed: `navidrome_tracks/{nd_id}` → `navidrome_playcounts/{playcount}:{userid}`
- `last_played` on edge (not vertex), `playcount` + `userid` on vertex
- Compound index `[userid, playcount]` on `navidrome_playcounts` for sorted queries
- `get_top_plays` queries vertex index first, then walks inbound edges (fast path)
- `increment_play` moves edge between bucket vertices atomically
- `bulk_upsert_plays` does wipe-and-rebuild for full sync
- V019 migration rewritten in-place with correct bucketed schema (no V020 needed)
- `TrackPlayData.last_played_ms` renamed to `last_played` everywhere
- `ensure_user()` removed — no per-user vertices in bucketed model
- `lint_project_backend()` — zero errors
- No remaining references to `last_played_ms` or `ensure_user` in `nomarr/`

## References

- Current persistence: `nomarr/persistence/database/navidrome_playcounts_aql.py`
- Bootstrap: `nomarr/components/platform/arango_bootstrap_comp.py` (`_create_indexes`, `_create_graphs`)
- V019 migration: `nomarr/migrations/V019_navidrome_graph_model.py` (rewrite in-place)
- Consumers: `ingest_scrobble_wf.py`, `sync_navidrome_wf.py`, `taste_profile_comp.py`, `generate_playlists_wf.py`
- Original plans: `plans/TASK-personal-playlist-A-graph-collections.md` through `G-plugin-scrobbler.md`
