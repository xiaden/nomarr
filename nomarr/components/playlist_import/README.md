# Playlist Import

Fetch playlists from streaming platforms, normalize metadata, and match tracks against the local library.

## Responsibilities

- Parse Spotify and Deezer playlist URLs (including short links and URI formats)
- Fetch playlist metadata and tracks from platform APIs
- Normalize artist names, track titles, and album names for cross-platform matching
- Match imported tracks to local library files using ISRC, exact, and fuzzy strategies

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `url_parser_comp` | Extract platform and playlist ID from Spotify/Deezer URLs — handles web URLs, Spotify URIs, and Deezer short links |
 | `spotify_fetcher_comp` | Fetch Spotify playlists via `spotipy` (Client Credentials flow), handles pagination for 100+ track playlists |
 | `deezer_fetcher_comp` | Fetch Deezer playlists via public API (no auth required), resolves `link.deezer.com` short links |
 | `metadata_normalizer_comp` | Text normalization for matching — Unicode NFKC, strip featuring/remaster suffixes, remove punctuation, artist-specific "The" handling |
 | `track_matcher_comp` | Multi-strategy matching: ISRC exact → title+artist exact → fuzzy (token_sort_ratio). Returns confidence levels and ambiguity flags |

## Patterns

- **Tiered matching:** `track_matcher_comp` tries strategies in confidence order — ISRC (highest), then normalized exact, then fuzzy. Ambiguous fuzzy matches are flagged for user review.
- **Platform abstraction:** Both fetchers return the same `(PlaylistMetadata, list[PlaylistTrackInput])` tuple, so the pipeline is platform-agnostic after URL parsing.
- **Pure normalization:** `metadata_normalizer_comp` is stateless with no DB or network access — pure string transformation.

## Dependencies

- **Upstream:** Called by playlist import workflows
- **Downstream:** `track_matcher_comp` calls persistence directly (ArangoDB library file queries for matching candidates)
- **External:** `spotipy` (Spotify API), `requests` (Deezer API), `thefuzz` (fuzzy string matching)
