# Navidrome

Navidrome/Subsonic integration — API communication, play data crawling, playlist generation, and taste profiling.

## Responsibilities

- Communicate with Navidrome via the Subsonic REST API
- Crawl play history (play counts, last-played timestamps) for all songs
- Build personalized playlists using ANN vector search with taste centroids
- Compute recency-weighted taste profiles from user play data
- Generate M3U playlist files with relative paths
- Execute tag-based playlist queries and resolve versioned tag keys
- Provide predefined playlist templates (mood, style, quality, mixed)

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `subsonic_client_comp` | `SubsonicClient` — synchronous HTTP client with token auth, covers ping, album listing, playlist CRUD, scan triggering |
 | `subsonic_crawl_comp` | Walk all Navidrome albums via paginated API, collect song IDs, paths, and play data |
 | `taste_profile_comp` | Compute recency-weighted taste centroid from top-N played tracks using embedding vectors |
 | `playlist_builder_comp` | Build personalized playlists — Familiar, Discovery, Hidden Gems, Universal, and per-genre via ANN search |
 | `tag_query_comp` | Tag-based playlist queries — find files by tag conditions, resolve short names to versioned keys, fetch preview tracks |
 | `m3u_comp` | Build and save M3U files with relative paths and sanitized filenames |
 | `templates_comp` | Predefined `.nsp` playlist templates (mood, style, quality, mixed categories) |

## Patterns

- **Subsonic token auth:** `SubsonicClient` generates per-request `md5(password + salt)` tokens — no session state.
- **ANN-based playlists:** Playlist builders use the taste centroid for approximate nearest neighbor search, then apply exclusion filters (played/unplayed, known artists).
- **Versioned tag keys:** `tag_query_comp` maps user-friendly short names to versioned storage keys, supporting future multi-version calibrations.

## Dependencies

- **Upstream:** Called by Navidrome services and playlist workflows
- **Downstream:** `collection_overview_comp`, `mood_analysis_comp`, `taste_profile_comp`, `playlist_builder_comp`, `tag_query_comp` call persistence directly (ArangoDB)
- **External:** `requests` (Subsonic API), `spotipy` (indirect via playlist import), `numpy` (centroid math)
