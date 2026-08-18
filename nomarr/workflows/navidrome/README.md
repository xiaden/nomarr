# Navidrome Workflows

Workflows for Navidrome integration — smart/static playlist generation, config export, and vector-based track similarity.

## Responsibilities

- Parse and execute smart playlist queries with nested boolean logic
- Generate `.nsp` smart playlist structures for Navidrome
- Preview smart playlist results with sample tracks
- Generate static M3U playlists from file IDs
- Generate Navidrome TOML config for custom tag fields
- Preview tag statistics for config generation
- Find similar tracks via vector ANN search
- Generate personal playlists from user taste profiles

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `parse_smart_playlist_query_wf.py` | Pure parser — query string → `SmartPlaylistFilter` with nested `RuleGroup` tree |
 | `filter_engine_wf.py` | Execute `SmartPlaylistFilter` against DB using set operations (AND=intersection, OR=union) |
 | `generate_smart_playlist_wf.py` | Convert parsed filter to `.nsp` JSON structure with sort/limit validation |
 | `preview_smart_playlist_wf.py` | Execute filter and return total count + sample tracks |
 | `generate_static_playlist_wf.py` | Resolve file IDs to paths, generate M3U content, optional server-side save |
 | `generate_navidrome_config_wf.py` | Query tags collection, detect types, generate TOML with field aliases |
 | `preview_tag_stats_wf.py` | Batched tag statistics for all tags (type, multivalue, summary, short_name) |
 | `find_similar_tracks_wf.py` | Resolve seed descriptor → vector → ANN search → return similar-track descriptors |
 | `generate_playlists_wf.py` | Taste profile computation, dispatch to playlist type builders (familiar, discovery, hidden gems, genre) |

## Patterns

- **Pure parsing**: Query parser is a pure function with no DB access; execution is separate
- **Set-based filtering**: Filter engine uses Python set intersection/union for boolean logic
- **Builder dispatch**: Playlist generation dispatches to per-type builder components

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and pass it to components (`components/navidrome/*`, `components/ml/vectors/*`). Direct DB usage goes through the `Database` abstraction layer.

## Dependencies

- **Called by**: `services/domain/navidrome_svc.py`
- **Calls**: `components/navidrome/*` (playlist builders, taste profile, descriptor matching, tag query, M3U), `components/ml/vectors/*` (ANN search)
- **Receives**: `Database`, namespace, config parameters
