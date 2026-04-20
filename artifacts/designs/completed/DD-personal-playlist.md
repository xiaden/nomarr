# Design: Personal Playlist (Daily Mix)

**Status:** Draft v3  
**Date:** 2026-03-20  
**Author:** Design discussion between developer and Copilot

---

## Summary

Generate personalized playlists for each Navidrome user based on their listening habits and Nomarr's ML embeddings. Playlists are pushed directly to Navidrome on a configurable schedule — users open their music player and find fresh playlists waiting.

Each user gets their own taste profile and their own set of playlists. The Navidrome plugin handles per-user scrobble events, scheduling, and playlist push. Nomarr handles the ML: computing taste centroids, running ANN search, and assembling playlist candidates.

The data model is **graph-native**: Navidrome track IDs, their link to Nomarr files, and per-user play counts are all represented as vertices and edges in ArangoDB. No denormalization, no document-collection workarounds — the graph IS the data model.

---

## What Exists Today

 | Capability | Status | Where |
 | --- | --- | --- |
 | Per-track embeddings (effnet, musicnn) | **Done** | `vectors_track_hot__*` / `vectors_track_cold__*` collections |
 | ANN vector search on cold collections | **Done** | `VectorsTrackColdOperations.search_similar()` |
 | Navidrome ↔ Nomarr ID mapping | **Exists, being replaced** | `navidrome_song_map` → migrates to graph model |
 | Subsonic API client | **Done** | `SubsonicClient` in `components/navidrome/` |
 | Playlist push to Navidrome | **Done** | `push_playlist_wf.py` — creates/replaces playlist by name |
 | Similar tracks from seed vector | **Done** | `find_similar_tracks_wf.py` — ANN search + ID resolution |
 | Plugin config surface in Navidrome UI | **Done** | `manifest.json` JSON Schema → rendered as form fields |
 | Navidrome API credentials (live from ConfigService) | **Done** | `navidrome_api_url`, `navidrome_api_user`, `navidrome_api_password` |
 | Tag system (artists, genres, etc.) | **Done** | `tags` vertices + `song_has_tags` edges |

**What does NOT exist:**

- Graph-based Navidrome track + play count model (new collections)
- Scrobble ingestion endpoint (`/api/v1/navidrome/scrobble`)
- Plugin Scrobbler capability (forward scrobbles to Nomarr)
- Taste profile computation (multi-centroid from weighted embeddings)
- Playlist type taxonomy (Familiar, Discovery, Hidden Gems, Universal)
- Plugin-side scheduling for playlist generation

---

## Graph Architecture: Navidrome Play Data

### Why Graph Over Document

The old approach (a document collection with composite keys, denormalized artist fields, and file_id foreign keys) conflates identity mapping with play tracking and requires manual joins. ArangoDB is a graph database — model graph problems as graphs.

The graph model provides:

- **No denormalization** — relationships are edges, not duplicated fields
- **Clean separation** — track identity, file linkage, and play counts are distinct vertices
- **Per-user play counts** as first-class vertices, not embedded fields
- **Deferred resolution** — scrobbles create play data immediately; file linkage happens when library sync runs, independently
- **Natural traversals** — "top played tracks for user X" is a graph query, not a document join

### Collection Design

```
library_files --[has_nd_id]--> navidrome_tracks --[has_plays]--> navidrome_playcounts
  (existing)      (edge)          (vertex)          (edge)          (vertex)
```

#### `navidrome_tracks` — Vertex Collection

Represents a Navidrome media file. The structural join point between Nomarr files and play data.

```
{
  _key: "abc123",              // Navidrome mediafile ID
  created_at: 1710950400000    // Epoch millis when first seen
}
```

Minimal properties — the vertex exists to anchor edges. Track metadata (title, artist, genre) lives in Nomarr's existing tag system.

#### `has_nd_id` — Edge Collection

Links a Nomarr library file to its Navidrome track identity. **No properties on the edge** — ArangoDB best practice is to filter on vertices, not edges.

```
{
  _from: "library_files/xyz",
  _to: "navidrome_tracks/abc123"
}
```

This replaces the existing `navidrome_song_map` document collection. The edge IS the ID mapping. One library file → one navidrome track (1:1). A navidrome_track may temporarily have no inbound `has_nd_id` edge if it was created via scrobble before library sync ran.

#### `navidrome_playcounts` — Vertex Collection

Per-user play count data for a Navidrome track. One vertex per (track, user) pair.

```
{
  _key: "abc123:john",         // Composite: <nd_id>:<userid> for fast upsert
  userid: "john",              // Navidrome username
  playcount: 47,               // Cumulative play count
  last_played_ms: 1710950400000,  // Epoch millis of most recent play
  updated_at: 1710950400000    // Epoch millis when last modified
}

Indexes:
- persistent unique: _key (automatic)
- persistent: [userid, playcount DESC]       // Top played per user
- persistent: [userid, last_played_ms DESC]  // Most recent per user
```

`last_played_ms` is required for the recency weighting formula. Multiple vertices per navidrome_track (one per user) is expected and clean.

#### `has_plays` — Edge Collection

Links a Navidrome track to its play count vertices. **No properties on the edge.**

```
{
  _from: "navidrome_tracks/abc123",
  _to: "navidrome_playcounts/abc123:john"
}
```

### Query Patterns

**Top plays for user X** (the primary taste profile query):

```aql
FOR pc IN navidrome_playcounts
    FILTER pc.userid == @user
    SORT pc.playcount DESC
    LIMIT @top_n
    // Walk inbound to get the nd_id, then inbound again to get the library file
    LET nd_track = FIRST(FOR v IN 1..1 INBOUND pc has_plays RETURN v)
    LET lib_file = FIRST(FOR v IN 1..1 INBOUND nd_track has_nd_id RETURN v)
    RETURN {
        nd_id: nd_track._key,
        file_id: lib_file._id,
        playcount: pc.playcount,
        last_played_ms: pc.last_played_ms
    }
```

Note: starts from the `navidrome_playcounts` index (fast userid + playcount lookup), then traverses inbound to resolve IDs. The "awkward" part is the 2-hop reverse traversal from playcount → track → file, but the index-first approach makes this efficient.

**Plays for a Navidrome track** (easy forward traversal):

```aql
FOR pc IN 1..1 OUTBOUND DOCUMENT("navidrome_tracks", @nd_id) has_plays
    RETURN { userid: pc.userid, playcount: pc.playcount }
```

**Resolve nd_id → file_id** (replaces song_map lookup):

```aql
FOR lib_file IN 1..1 INBOUND DOCUMENT("navidrome_tracks", @nd_id) has_nd_id
    RETURN lib_file._id
```

**Known artists for a user** (for Hidden Gems filtering):

```aql
FOR pc IN navidrome_playcounts
    FILTER pc.userid == @user AND pc.playcount > 0
    LET nd_track = FIRST(FOR v IN 1..1 INBOUND pc has_plays RETURN v)
    LET lib_file = FIRST(FOR v IN 1..1 INBOUND nd_track has_nd_id RETURN v)
    FILTER lib_file != null
    LET artists = (
        FOR tag IN 1..1 OUTBOUND lib_file song_has_tags
            FILTER tag.rel == "artist"
            RETURN tag.value
    )
    RETURN DISTINCT artists
```

No denormalized artist field — the tag system is the authority. This avoids stale artist data entirely.

### Orphan Management

Orphans arise from three scenarios:

 | Scenario | Orphaned Objects | Cleanup Strategy |
 | --- | --- | --- |
 | Library file deleted from Nomarr | Dangling `has_nd_id` edge (from=deleted) | Periodic sweep: find edges where `_from` doc doesn't exist |
 | Navidrome track removed | `navidrome_tracks` vertex + downstream `has_plays` edges + `navidrome_playcounts` vertices | On library sync: remove tracks not seen in Navidrome, cascade delete |
 | User removed from Navidrome | `navidrome_playcounts` vertices for that user | On user list refresh: delete playcounts for unknown userids |

Orphan cleanup runs as part of the library sync workflow (not a standalone cron). It's cheap — check for dangling edges and vertices after the main sync completes.

### Migration from `navidrome_song_map`

The existing `navidrome_song_map` document collection is replaced by `navidrome_tracks` + `has_nd_id`. Migration:

1. Create `navidrome_tracks` vertex collection
2. Create `has_nd_id` edge collection
3. For each document in `navidrome_song_map`: create a `navidrome_tracks` vertex (`_key = nd_id`), create a `has_nd_id` edge (`_from = file_id, _to = navidrome_tracks/<nd_id>`)
4. Create `navidrome_playcounts` vertex collection + `has_plays` edge collection (empty initially)
5. Drop `navidrome_song_map` after verification
6. Update `sync_song_map_wf.py` to work with the graph model (or replace entirely)

This is a forward-only migration. The graph model is strictly more capable.

---

## Two Data Paths

### Path 1: Initial Sync (Historical Catch-Up)

When a user first enables the plugin, we need their existing play history. The sync workflow:

1. Walks the Navidrome library: `getAlbumList2` (paginated) → `getAlbum(albumId)` per album
2. For each track: upsert `navidrome_tracks` vertex, create `has_nd_id` edge to library_file
3. Per enabled user: capture `playCount` and `played` (lastPlayed) from the Subsonic `Child` response
4. Upsert `navidrome_playcounts` vertex + `has_plays` edge for each (track, user) pair

The Subsonic API returns per-user play counts when authenticated as that user. The plugin calls `subsonicapi_call("getAlbum?id=...&u=username")` internally (zero network overhead).

**About the N+1 concern:** Walks `getAlbumList2` (500/page) → `getAlbum(albumId)` per album. For 23k songs ≈ ~500 albums ≈ ~502 calls. Album-level N+1, not song-level. Via plugin's `subsonicapi_call`, these are in-process function calls — effectively free. One-time operation. Acceptable.

### Path 2: Real-Time Scrobble (Ongoing)

The Navidrome plugin Scrobbler capability receives per-user scrobble events in real time:

```json
{
  "username": "john",
  "track": { "id": "abc123", "title": "...", "duration": 180.5 },
  "timestamp": 1703270400
}
```

The plugin POSTs to Nomarr's `/api/v1/navidrome/scrobble`. Nomarr processes:

1. Upsert `navidrome_tracks/abc123` vertex (idempotent)
2. Upsert `navidrome_playcounts/abc123:john` vertex: `playcount += 1, last_played_ms = timestamp`
3. Ensure `has_plays` edge exists from track → playcount vertex

Note: the `has_nd_id` edge (linking to a library_file) may not exist yet if library sync hasn't run. This is fine — the play data is captured immediately. The file linkage is resolved whenever sync creates the edge. **Deferred resolution** is a key advantage of the graph model.

After the initial sync, play counts stay fresh without ever re-walking the library.

### Scrobble Deduplication

Navidrome may send duplicate scrobbles on retry (`scrobbler(retry_later)` error). The upsert is idempotent for timestamp, but play_count increment is not. Guard with a short dedup window: same user + track within 30 seconds = skip increment.

---

## Navidrome Plugin Architecture

The plugin is a **thin relay and scheduler**, not a compute engine. Nomarr does all ML/vector work.

### Plugin Capabilities Used

 | Capability | Purpose |
 | --- | --- |
 | **Scrobbler** | Receive per-user scrobble events from Navidrome, forward to Nomarr |
 | **Users** | Enumerate which users the plugin is enabled for |
 | **SubsonicAPI** | Call Subsonic API internally for initial play history sync |
 | **Scheduler** | Schedule recurring playlist generation |
 | **HTTP** | POST scrobbles and trigger generation on Nomarr's API |
 | **KVStore** | Persist per-user sync state (has initial sync completed?) |

### Plugin Flow

```
Navidrome                              Nomarr
┌─────────────────────┐               ┌──────────────────────────┐
│  Nomarr Plugin      │               │                          │
│  ┌───────────────┐  │  HTTP POST    │  /api/v1/navidrome/      │
│  │ Scrobbler     │──┼──────────────▶│    scrobble              │
│  │ (real-time)   │  │               │  ├─ upsert track vertex  │
│  ├───────────────┤  │               │  └─ upsert playcount     │
│  │ Scheduler     │──┼── trigger ───▶│  /api/v1/navidrome/      │
│  │ (cron)        │  │               │    generate-playlists    │
│  ├───────────────┤  │               │  ├─ taste profiles       │
│  │ SubsonicAPI   │  │  ◀── push ───│  ├─ multi-centroid ANN   │
│  │ (internal)    │  │  playlists    │  ├─ type taxonomy        │
│  ├───────────────┤  │               │  └─ return playlist IDs  │
│  │ Users         │  │               │                          │
│  │ (per-user)    │  │               │                          │
│  ├───────────────┤  │               │                          │
│  │ KVStore       │  │               │                          │
│  │ (sync state)  │  │               │                          │
│  └───────────────┘  │               │                          │
└─────────────────────┘               └──────────────────────────┘
```

### Multi-User: Easier Than Expected

The plugin `users` permission + Scrobbler capability gives us per-user for free:

1. Admin installs the Nomarr plugin, configures which users it applies to (or "Allow all users")
2. Plugin calls `users_getusers()` → gets list of usernames
3. Each scrobble event includes `username` → Nomarr creates per-user playcounts in the graph
4. Playlist generation runs per-user: each user gets their own taste profile + playlists
5. Plugin creates playlists via `subsonicapi_call("createPlaylist?...&u=username")` — internal, no network

No per-user credential storage on Nomarr's side. The plugin handles auth implicitly.

From the Navidrome plugin docs:
> *"Scrobble events are only sent for users assigned to the plugin through Navidrome's configuration."*

### Scheduling: Plugin-Side Only

The plugin has a built-in `scheduler_schedulerecurring(cronExpr, payload, scheduleId)` host function. Nomarr has **no cron config and no scheduling responsibility**.

Plugin `nd_on_init` schedules:

- Recurring playlist generation (default: daily at 3 AM, configurable via plugin config)
- On trigger, the plugin calls `/api/v1/navidrome/generate-playlists` for each enabled user
- Nomarr returns playlist track IDs
- Plugin creates/replaces playlists via internal `subsonicapi_call`

Nomarr's API is stateless — it computes playlists on request.

---

## Taste Profile Computation

### Genre-Partitioned ANN Indexes (No K-Means)

ArangoDB already does similarity search via `APPROX_NEAR_COSINE` on cold vector collections. Instead of computing k-means centroids in Python and feeding them back to ArangoDB, we let ArangoDB handle both the partitioning and the search.

**How it works:** During cold promotion (hot → cold), each track's genre tags are known (from `song_has_tags`). The vector is added to the **global** index (already exists) and also to a **genre-specific** index for each genre tag the track carries. Any genre with 100+ analyzed tracks gets its own index.

This means ArangoDB IS the clustering engine. Genre indexes are the clusters. No k-means, no numpy, no centroid computation — just a single weighted centroid per query scope and ANN search on the appropriate index.

**Pipeline:**

1. Query top N tracks by play count for a user (graph traversal from `navidrome_playcounts`)
2. Resolve each track to its `library_files` document via graph traversal
3. Look up embeddings from `vectors_track_cold` by file_id
4. Compute recency-weighted scores → single weighted centroid (just a weighted average + L2 normalize)
5. **Global ANN search** → candidates for Discovery / Universal playlists
6. **Per-genre ANN search** → candidates for genre-specific playlists ("Your Jazz Mix", "Your Metal Mix")
7. Apply playlist type filters (see Playlist Type Taxonomy below)
8. Merge and assemble final playlists

Genre playlists are v1 — they're **easier** with this approach because the label IS the genre tag that defines the index. No cluster labeling needed.

### Genre Index Lifecycle

Genre indexes are built alongside the global index during cold promotion. In v1, they are **static after build** — if a user changes a genre tag, the index becomes stale until the next manual rebuild.

This is acceptable for v1. Genre changes are infrequent. But it creates a future concern:

**Future (post-v1):** Track genre tag changes should flag the affected genre indexes as needing refresh. This could be a simple dirty bit per genre index, checked on next playlist generation or periodic maintenance. Not v1 scope, but the migration design should not preclude it.

### Weighting Formula: Recency-Scaled Play Count

$$w_i = \log(1 + \text{playcount}_i) \cdot e^{-\lambda \cdot d_i}$$

Where:

- $\lambda = \ln(2) / \text{half\_life}$ (configurable, default 30 days)
- $d_i$ = days since last played
- Log-scaling prevents heavy-rotation tracks from dominating
- Adopted from AudioMuse's exponential decay approach, improved with log play count

### Unknown Recency Handling

 | Case | Cause | Handling |
 | --- | --- | --- |
 | `playcount == 0` | Never played | **Exclude entirely.** Not a taste signal. |
 | `playcount > 0`, no `last_played_ms` | Legacy Navidrome — plays before timestamps were tracked | **Assign synthetic recency of `half_life × 2` days ago.** Default 30-day half-life → 60 days → decay weight ≈ 0.25. |

Everything goes through the same exponential decay — the synthetic recency is just a different $d_i$ value.

### Backbone Agnosticism

Computation accepts a `backbone_id` parameter and works with whatever embeddings are in the cold collection. No hardcoded model names.

### Centroid Normalization

Cold collection indexes use cosine metric (stored as `vector_n`). The single weighted centroid must be L2-normalized **after** weighted averaging. The weighted average of unit vectors is not itself a unit vector.

---

## Playlist Type Taxonomy

Five playlist types for v1. Each type uses the same weighted centroid but queries different indexes with different filters.

 | Type | ANN Index | Filter Logic | What It Produces |
 | --- | --- | --- | --- |
 | **Familiar** | None (direct query) | Only tracks with `playcount >= threshold` | "Songs you love" — comfort music you know well |
 | **Discovery** | Global | Exclude tracks with `playcount > 0` (never heard) | "Songs you'll probably like but haven't heard" |
 | **Hidden Gems** | Global | Exclude ALL tracks from artists in user's play history | "New artists that match your taste" — maximum novelty |
 | **Genre** | Per-genre index | Same centroid, genre-constrained search space | "Your Jazz Mix", "Your Metal Mix" — per-genre taste |
 | **Universal** | Global | Diversified sampling across results | "Discovered for You" — cross-genre mix |

### Hidden Gems: Artist Exclusion via Tag Traversal

Hidden Gems requires knowing which **artists** the user has listened to. Instead of denormalizing artist data onto play counts (stale data risk), we traverse the tag system:

1. Get user's played tracks via graph traversal → resolve to library_files
2. For each library_file, traverse `song_has_tags` edges where `tag.rel == "artist"` → collect known artists
3. Filter ANN results: exclude tracks whose artist tags are in the known set

Filter: `distance(centroid, track) < threshold AND track.artist_tags NOT IN user_known_artists`

This guarantees every track in the playlist is from an unfamiliar artist. Maximum novelty while maintaining taste relevance. Tag system is always authoritative — no stale data.

### Genre Playlists: Index Per Genre

Each genre with 100+ analyzed tracks gets its own ANN index in the cold collection. The playlist generation queries each genre index the user has affinity for (determined by which genres appear in their played tracks). The centroid is the same — only the search space changes.

Genre labels are free: the index name IS the genre. "Your Jazz Mix" comes from the jazz index, not from post-hoc cluster labeling.

---

## Configuration

~10 keys total. Plugin owns scheduling. No per-type size overrides — global min/max.

```yaml
personal_playlists:
  enabled: true                    # Master switch
  overwrite_playlists: true        # Replace existing or create new dated ones
  backbone_id: "effnet-discogs"    # Which embeddings to use
  half_life_days: 30               # Recency decay parameter
  min_play_count: 3                # Minimum plays to influence taste profile
  max_songs: 50                    # Global max songs per playlist
  min_songs: 10                    # Global min songs per playlist

  types:
    familiar:
      enabled: true
    discovery:
      enabled: true
    hidden_gems:
      enabled: true
    genre:
      enabled: true
    universal:
      enabled: true
```

Config lives in Nomarr's settings page (ConfigService). The plugin handles connectivity (scrobbles, scheduling, playlist push) — not ML configuration.

No `schedule_cron` key on the backend. The plugin's own config form (via `manifest.json`) exposes cron scheduling to the Navidrome admin.

---

## Architecture

### New Backend Modules

```
persistence/database/
  navidrome_tracks_aql.py          # CRUD for navidrome_tracks vertices + has_nd_id edges
  navidrome_playcounts_aql.py      # CRUD for navidrome_playcounts vertices + has_plays edges

components/
  navidrome/
    taste_profile_comp.py          # Weighted centroid computation + recency weighting

workflows/
  navidrome/
    sync_navidrome_wf.py           # Library sync: tracks + edges + per-user play counts
    ingest_scrobble_wf.py          # Process a single scrobble event
    generate_playlists_wf.py       # Full pipeline: graph query → profile → ANN → filter → assemble

interfaces/api/v1/
    navidrome_if.py                # POST /api/v1/navidrome/scrobble
                                   # POST /api/v1/navidrome/generate-playlists
```

### Existing Modules (changed or referenced)

- `navidrome_song_map_aql.py` — **deprecated and removed** post-migration. Replaced by graph model.
- `sync_song_map_wf.py` — **replaced** by `sync_navidrome_wf.py` which works with the graph.
- `find_similar_tracks_wf.py` — stays as-is, used for Instant Mix (seed-based, no taste profile)
- `push_playlist_wf.py` — stays as-is. Plugin handles push, but this may be used as backend fallback.
- `SubsonicClient` — stays as-is for Nomarr-side Subsonic calls

### Data Flow

```
  Navidrome User Plays Song
           │
           ▼
  ┌─────────────────────┐
  │ Navidrome calls      │
  │ nd_scrobbler_        │
  │ scrobble()           │
  └────────┬────────────┘
           │ plugin HTTP POST
           ▼
  ┌──────────────────────────┐
  │ Nomarr                    │
  │ /api/v1/navidrome/scrobble│
  │ ├─ upsert navidrome_tracks│
  │ │  vertex (if new nd_id)  │
  │ ├─ upsert playcount vertex│
  │ │  (per user + track)     │
  │ ├─ ensure has_plays edge  │
  │ └─ done                   │
  │                           │
  │ Note: has_nd_id edge to   │
  │ library_file created by   │
  │ sync, not by scrobble     │
  └──────────────────────────┘

  ─── Later, on schedule: ───

  ┌─────────────────────┐
  │ Plugin scheduler     │
  │ fires cron           │
  └────────┬────────────┘
           │ HTTP POST per user
           ▼
  ┌──────────────────────────────┐
  │ Nomarr                        │
  │ /api/v1/navidrome/            │
  │   generate-playlists?user=john│
  │ ├─ query playcounts (graph)   │
  │ ├─ resolve to library_files   │
  │ ├─ fetch embeddings           │
  │ ├─ weighted centroid           │
  │ ├─ ANN search (global + genre)│
  │ ├─ apply type filters         │
  │ │  (familiar/discovery/       │
  │ │   hidden gems/universal)    │
  │ ├─ resolve back to nd_ids     │
  │ └─ return playlist nd_ids     │
  │    per type                   │
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌─────────────────────────┐
  │ Plugin creates           │
  │ playlists via            │
  │ subsonicapi_call()       │
  │ (internal, per user)     │
  └─────────────────────────┘
```

---

## DTOs

```python
class TrackPlayData(TypedDict):
    file_id: str              # Nomarr library_files document ID
    nd_id: str                # Navidrome track ID
    playcount: int
    last_played_ms: int       # Epoch millis (0 = unknown)

class TasteCluster(TypedDict):
    centroid: list[float]     # Normalized centroid vector
    track_count: int          # Tracks in this cluster
    label: str                # Human-readable label (genre or "Mix N")

class TasteProfile(TypedDict):
    nd_user: str
    clusters: list[TasteCluster]
    backbone_id: str
    track_count: int          # Total tracks that contributed
    generated_at_ms: int

class PlaylistResult(TypedDict):
    playlist_type: str        # "familiar", "discovery", "hidden_gems", "universal"
    playlist_name: str
    nd_ids: list[str]         # Navidrome track IDs, ordered
    track_count: int
```

No artist field on any DTO. Artist data is resolved via tag traversal when needed (Hidden Gems filter), never denormalized onto play data.

---

## Competitive Analysis: AudioMuse-AI "Sonic Fingerprint"

AudioMuse-AI (open source, NeptuneHub/AudioMuse-AI) implements an equivalent feature. Examined for inspiration and differentiation.

### Their Algorithm

1. **Get top played songs** — `getAlbumList2(type=frequent)` returns albums by frequency. Fetches tracks, `random.sample()` picks N. Album-level approximation, not track-level.
2. **Get recency** — `getSong(id=...)` per track (N+1 HTTP requests) for `lastPlayed`.
3. **Weight** — Exponential decay: $w = e^{-\lambda \cdot d}$, `half_life=30 days`. No `lastPlayed` = flat 0.25.
4. **Centroid** — Single weighted average.
5. **ANN search** — Voyager library.
6. **Scheduling** — DB-backed cron table, synchronous execution.

### Weaknesses We Exploit

 | Their Weakness | Our Advantage |
 | --- | --- |
 | Album-level play frequency + `random.sample()` | Exact per-track play counts from real-time scrobble + initial sync |
 | N+1 `getSong` calls for `lastPlayed` | `last_played_ms` updated on every scrobble — always fresh, zero extra API calls |
 | Single centroid — diverse taste collapses to mushy middle | Genre-partitioned ANN indexes — each genre gets its own search space |
 | Global play counts (no per-user) | Per-user `navidrome_playcounts` from day one |
 | Synchronous cron execution blocks other tasks | Plugin-side async scheduling |
 | One playlist type | Taxonomy: Familiar, Discovery, Hidden Gems, Genre, Universal |
 | External ANN library (Voyager) | ArangoDB-native ANN via `APPROX_NEAR_COSINE` — same DB, zero operational overhead |

### What We Adopt From Them

 | Their Pattern | Our Adaptation |
 | --- | --- |
 | **Exponential decay for recency** | Adopt as default weighting formula |
 | **Dated playlist naming** | Supported as `overwrite_playlists: false` mode |

### Differentiation Summary

```
AudioMuse:  album_frequency → random_sample → N+1_getSong → single_centroid → Voyager_ANN → 1 playlist
Nomarr:     per_user_scrobble → graph_play_data → weighted_centroid → genre_partitioned_ANN → 5 playlist types
```

---

## Difficulty Assessment

 | Component | Difficulty | Notes |
 | --- | --- | --- |
 | Graph collections + migration from song_map | **Easy-Medium** | New vertex/edge collections, migrate existing data, AQL operations |
 | Scrobble ingestion endpoint | **Easy** | Thin interface → upsert workflow on graph |
 | Plugin Scrobbler capability | **Medium** | WASM plugin development (Go/TinyGo), HTTP POST to Nomarr |
 | Plugin scheduler for generation | **Easy-Medium** | `scheduler_schedulerecurring` + HTTP trigger |
 | Initial play history sync workflow | **Easy-Medium** | Walk albums (existing pattern), capture per-user play counts, create graph edges |
 | Weighted centroid + genre-partitioned ANN | **Easy** | Single weighted average + L2 normalize, ArangoDB does the rest |
 | Playlist type filters (Familiar/Discovery/Hidden Gems) | **Easy-Medium** | AQL query variations per type, tag traversal for Hidden Gems |
 | Playlist generation endpoint | **Medium** | Orchestrate all the above into a single workflow |
 | Plugin playlist push via SubsonicAPI | **Easy** | `subsonicapi_call("createPlaylist?...")` per user |
 | Config UI for playlist settings | **Easy** | Known pattern, existing config page |
 | Orphan cleanup | **Easy** | Graph traversal sweep after sync |
 | Genre-partitioned ANN indexes | **Easy-Medium** | Build during cold promotion, filter by genre tag. 100+ track threshold. |

### Total Estimate

- **v1 (graph model, per-user scrobble, genre-partitioned ANN, all 5 playlist types):** ~4-5 sessions
- **v1.5 (genre index refresh on tag change, freshness window):** ~2 sessions
- **v2 (backbone blending, starred track boost, ListenBrainz/Last.fm):** ~3-4 sessions

---

## Open Questions

1. ~~**Per-user play counts via Subsonic API**~~ **Answered.** Plugin Scrobbler + SubsonicAPI with `u=username`.

2. **Embedding dimensionality** — What are the actual dims for effnet-discogs and musicnn? Affects ANN search performance.

3. ~~**Centroid normalization**~~ **Answered.** L2-normalize after weighted averaging.

4. **Minimum library size** — Below what analyzed-track count is personal playlist meaningless? Probably ~100 minimum.

5. **Starred tracks** — Should starred/favorited tracks carry extra weight? Could be a multiplier on weight.

6. ~~**Plugin scrobble interception**~~ **Answered.** Full Scrobbler capability.

7. ~~**numpy/scikit-learn**~~ **Answered.** No scikit-learn, no k-means. Genre-partitioned ANN indexes in ArangoDB handle clustering natively.

8. **Plugin language choice** — Go (recommended by Navidrome) is the supported path.

9. **Scrobble deduplication window** — 30 seconds same user+track = skip. Is this sufficient?

10. **Plugin config scope** — Currently global (not per-user). Per-user preferences may need Nomarr-side settings with per-user auth, or plugin KVStore keyed by username.

11. **Graph traversal performance** — The 2-hop reverse traversal (playcount → track → file) needs benchmarking at scale. Index-first approach (start from `navidrome_playcounts` collection) should be efficient, but worth validating with ~23k tracks × multiple users.

12. **Backfill for unlinked playcounts** — Scrobbles that arrive before library sync create `navidrome_tracks` vertices without `has_nd_id` edges. After sync creates the edges, should we retroactively link? The graph handles this naturally (the edge just appears), but the taste profile query already filters `lib_file != null`.

13. **Genre index minimum size** — 100 tracks is the proposed threshold for creating a genre-specific ANN index. Is this enough for meaningful ANN results? Too low creates noisy indexes; too high misses niche genres.

14. **Genre index rebuild trigger (post-v1)** — When a user edits genre tags, the affected genre indexes become stale. What's the right granularity for flagging? Per-index dirty bit? Per-track dirty list? Deferred, but architecture should not preclude it.

---

## Implementation Order

1. **Graph collections + migration** — Create `navidrome_tracks`, `has_nd_id`, `navidrome_playcounts`, `has_plays`. Migrate `navidrome_song_map` data. This unblocks everything.
2. **Scrobble ingestion endpoint** — `POST /api/v1/navidrome/scrobble` → graph upsert. Can test with curl.
3. **Initial play history sync workflow** — Walk albums, create graph edges, capture per-user play counts.
4. **Plugin Scrobbler capability** — Forward `nd_scrobbler_scrobble` → Nomarr.
5. **Taste profile computation** — Weighted centroid with recency weighting + genre-partitioned ANN search.
6. **Playlist generation workflow** — Taste profile → ANN search → type filters → assemble track lists.
7. **Generation endpoint** — `POST /api/v1/navidrome/generate-playlists` → returns playlist IDs per type.
8. **Plugin scheduler + playlist push** — `scheduler_schedulerecurring` + `subsonicapi_call("createPlaylist")`.
9. **Config UI** — Personal playlist settings in Nomarr web UI.
10. **Genre playlists with cluster labeling** — ~~v1.5~~ Built into v1 via genre-partitioned ANN indexes.
