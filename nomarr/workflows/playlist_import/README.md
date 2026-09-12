# Playlist Import Workflows

Workflow for converting streaming service playlists (Spotify, Deezer) to local M3U playlists by matching against the imported library.

## Responsibilities

- Parse streaming playlist URLs (Spotify and Deezer formats)
- Fetch playlist metadata and tracks from streaming APIs
- Match streaming tracks against local library files (exact + fuzzy)
- Generate M3U playlist content from matched tracks

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `convert_playlist_wf.py` | End-to-end conversion — parse URL → fetch tracks → match against library → generate M3U |

## Patterns

- **Platform detection**: URL parsing identifies Spotify vs Deezer and dispatches to appropriate fetcher
- **Fuzzy matching**: Library matching falls back to fuzzy artist+title comparison when exact match fails
- **Ambiguous exclusion**: Ambiguous matches (multiple candidates) are excluded from M3U output

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** The workflow receives `Database` but loads library tracks only through the public typed component boundary — `components/library/library_song_query_comp.py::get_tracks_for_matching` returns `TrackSong` carriers and `locators_for_carriers` projects them to opaque `SongIdentity` locators. There is no direct persistence seam and no path-to-id conversion. Streaming API access uses `components/playlist_import/*` for fetching and normalization.

## Dependencies

- **Called by**: `services/domain/playlist_import_svc.py`
- **Calls**: `components/playlist_import/*` (URL parsing, Spotify/Deezer fetching, track matching, metadata normalization); `components/library/library_song_query_comp.py` (typed `TrackSong` carriers + opaque locator projection)
- **Receives**: `Database`, playlist_url, Spotify credentials
