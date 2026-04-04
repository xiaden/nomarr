# Design: Per-User Playlist Configuration

**Status:** Draft
**Date:** 2026-03-22

---

## Problem

Personal playlist configuration currently lives in the wrong place. All playlist tuning
parameters (`enabled_types`, `max_songs`, `half_life_days`, `top_n`, `min_play_count`,
`min_songs`) are stored in Nomarr's `ConfigService` — a global singleton. The Navidrome
plugin has a single flat `pp_user_id` field, meaning only one Navidrome user gets playlists.

The Navidrome PDK fully supports per-user plugin configuration via JSON Schema arrays,
as demonstrated by the ListenBrainz plugin (`kgarner7/navidrome-listenbrainz-daily-playlist`).
Plugin config can have a `users` array where each entry contains per-user settings with
its own `username`, playlist preferences, and tuning knobs.

Additionally, the current plugin does **not** pass `?u=username` in Subsonic API calls,
so `createPlaylist` creates playlists in whatever default admin context the plugin runs
under — not under the target user's account.

## Goals

1. Move user-facing playlist config from Nomarr UI to Navidrome plugin config (per-user)
2. Support multiple Navidrome users, each with their own playlist preferences
3. Fix playlist ownership — playlists must be created under the correct Navidrome user
4. Keep Nomarr-side config as server defaults and technical tuning params
5. Maintain backward compatibility with the existing single-user API

## Non-Goals

- Changing the playlist generation algorithm itself
- Adding new playlist types
- Frontend playlist management UI
- Navidrome user discovery/auto-sync
- Per-user backbone selection (PDK config is static JSON Schema; dynamic dropdowns not possible)

---

## Config Ownership Split

Not all params belong on the plugin side. The split:

**Per-user in plugin (user-facing preferences):**

| Param | Description | Default |
| --- | --- | --- |
| `enabled_types` | Which playlist types to generate | all 5 types |
| `max_songs` | Maximum songs per playlist | 50 |
| `min_songs` | Minimum songs to keep a playlist | 5 |

**Server-side in Nomarr (technical tuning):**

| Param | Description | Default | Why server-side |
| --- | --- | --- | --- |
| `half_life_days` | Taste profile decay rate | 30.0 | Algorithm internals |
| `top_n` | Candidate pool size | 200 | Algorithm internals |
| `min_play_count` | Minimum plays to count a track | 1 | Algorithm internals |
| `backbone_id` | ML model for vector similarity | `effnet-discogs` | Depends on installed models |
| `library_key` | Which library to query | `""` | Server topology |

**Rationale:** Users care about what playlists they get and how many tracks.
They do not care about decay rates, candidate pool sizes, or which ML model is doing
the math. Technical params stay server-side where they can be tuned globally.

**Backbone selection note:** Ideally, per-user backbone selection (or even multi-backbone
generation) would let users pick "give me playlists from both effnet-discogs and
msd-musicnn." However, Navidrome's PDK config is static JSON Schema defined at build
time — the plugin cannot query Nomarr for installed backbones to populate a dynamic
dropdown. Free-text backbone ID entry is error-prone. Future work could explore a
runtime config negotiation mechanism, but for now backbone stays on Nomarr side.

---

## Architecture

### Current Flow

```text
Plugin (cron) → POST /api/v1/navidrome/generate-playlists {user_id}
                    ↓
              NavidromeService.generate_playlists(user_id)
                reads ALL tuning params from ConfigService (global)
                    ↓
              generate_playlists_wf (workflow)
                    ↓
              returns [NavidromePersonalPlaylistEntry] with file_ids
                    ↓
              Interface resolves file_ids → nd_ids
                    ↓
Plugin ← response with {playlist_type, playlist_name, track_nd_ids}
                    ↓
Plugin → host.SubsonicAPICall("createPlaylist?name=...&songId=...")
         (NO user context — wrong playlist owner)
```

### Proposed Flow

```text
Plugin reads per-user config from manifest users array
    ↓
For each user in config:
    ↓
Plugin → POST /api/v1/navidrome/generate-playlists {
           user_id, enabled_types, max_songs, min_songs
         }
                    ↓
              NavidromeService.generate_playlists(user_id, **overrides)
                uses provided params for user-facing prefs,
                reads technical params from ConfigService
                    ↓
              (same workflow, same response shape)
                    ↓
Plugin ← response with playlists
                    ↓
Plugin → subsonicCall("createPlaylist", username, &songIds)
         builds URI: /rest/createPlaylist?u=username&name=...&songId=...
         (playlist created under CORRECT user context)
```

---

## Component Changes

### A. Nomarr API (Backend)

**File: `nomarr/interfaces/api/v1/navidrome_v1_if.py`**

The request model already has `max_songs` and `enabled_types` as optional fields.
Add `min_songs`. Only user-facing params are accepted as overrides:

```python
class GeneratePlaylistsRequest(BaseModel):
    user_id: str
    enabled_types: list[str] | None = None
    max_songs: int | None = None
    min_songs: int | None = None
```

The endpoint passes these through to the service. The service uses provided values,
falling back to `ConfigService` for any that are `None`. Technical params
(`half_life_days`, `top_n`, `min_play_count`) are always read from `ConfigService`.

**File: `nomarr/services/domain/navidrome_svc.py`**

Update `generate_playlists()` signature to accept the three user-facing overrides:

```python
def generate_playlists(
    self,
    user_id: str,
    *,
    enabled_types: list[str] | None = None,
    max_songs: int | None = None,
    min_songs: int | None = None,
) -> list[NavidromePersonalPlaylistEntry]:
```

Each param: use provided value if not None, else read from `ConfigService`.
Technical params always come from `ConfigService`.

### B. Navidrome Plugin (Go/WASM)

**File: `navidrome-plugin/manifest.json`**

Replace flat `pp_user_id` with a `users` array. Each entry has user-facing prefs only:

```json
"users": {
  "type": "array",
  "title": "Personal Playlist Users",
  "items": {
    "type": "object",
    "properties": {
      "username": {
        "type": "string",
        "title": "Navidrome Username",
        "description": "The Navidrome user who will own these playlists"
      },
      "enabled_types": {
        "type": "array",
        "title": "Playlist Types",
        "items": {
          "type": "string",
          "enum": ["familiar", "discovery", "hidden_gems", "genre", "universal"]
        },
        "default": ["familiar", "discovery", "hidden_gems", "genre", "universal"]
      },
      "max_songs": {
        "type": "integer",
        "title": "Max Songs per Playlist",
        "default": 50
      },
      "min_songs": {
        "type": "integer",
        "title": "Min Songs to Keep Playlist",
        "default": 5
      }
    },
    "required": ["username"]
  }
}
```

Keep global `pp_enabled`, `pp_schedule_cron` at top level.
Remove `backbone_id` from plugin config (stays on Nomarr side).

**File: `navidrome-plugin/src/main.go`**

Major changes:
1. Add `subsonicCall()` helper that prepends `?u=username` to SubsonicAPICall URIs
   (follow pattern from LBZ plugin: `url := fmt.Sprintf("/rest/%s?u=%s", endpoint, user)`)
2. Add playlist find-and-replace: search for existing playlist by name, update or create
3. Refactor `generateAndPushPlaylists()` to:
   - Read `users` array from plugin config
   - Iterate over each user
   - Send per-user prefs (`enabled_types`, `max_songs`, `min_songs`) in API request body
   - Push playlists via Subsonic API with `?u=username` for correct ownership

### C. Frontend Cleanup

**Files in `frontend/src/features/config/components/`**

Remove or simplify personal playlist config section in Nomarr settings UI.
Per-user prefs (`enabled_types`, `max_songs`, `min_songs`) now live in plugin config.
Keep technical tuning params that stay server-side (`half_life_days`, `top_n`,
`min_play_count`) — label them as "Playlist Algorithm Tuning" or similar.
Remove `pp_enabled` (now per-user in plugin).
Keep `backbone_id` and `library_key` (still needed server-side).

---

## Research Findings

### Navidrome PDK Subsonic API

`host.SubsonicAPICall(uri string) (string, error)` takes a raw URI string.
The LBZ plugin wraps this in a helper that prepends `/rest/{endpoint}?u={user}`:

```go
func Call(endpoint, subsonicUser string, params *url.Values) (*responses.JsonWrapper, bool) {
    url := fmt.Sprintf("/rest/%s?u=%s", endpoint, subsonicUser)
    if params != nil {
        url += "&" + params.Encode()
    }
    subsonicResp, err := host.SubsonicAPICall(url)
    // ...
}
```

### Navidrome PDK Users API

`host.UsersGetUsers() ([]User, error)` returns all users the plugin has access to.
`User` struct: `{UserName, Name, IsAdmin}`.

The plugin must be granted `users` permission in manifest.json to enumerate users.
Users must be enabled for the plugin in Navidrome's plugin permissions UI.

### Navidrome PDK Config

`pdk.GetConfig(key string) (string, bool)` returns config values as strings.
For array/object config, the raw JSON string is returned and must be unmarshalled.

### Navidrome PDK Config Limitations

Plugin config is defined via static JSON Schema in `manifest.json`. There is no
mechanism for the plugin to:
- Query an external service for available options at config-render time
- Populate dropdowns dynamically based on runtime data
- Negotiate config schema with the backend

This means backbone selection cannot be a validated dropdown in plugin config.
A free-text string field would work but is error-prone. Decision: keep backbone
selection on Nomarr side.

### Existing Nomarr API

`POST /api/v1/navidrome/generate-playlists` currently accepts:

```json
{"user_id": "string", "max_songs": null, "enabled_types": null}
```

Note: `max_songs` and `enabled_types` already exist as optional overrides but are
**NOT WIRED THROUGH** — the endpoint ignores them and only passes `user_id` to the service.

### Config Keys in Nomarr ConfigService

| Key | Default | Type | Where after change |
| --- | --- | --- | --- |
| `vector_backbone_id` | `"effnet-discogs"` | str | Nomarr only |
| `library_key` | `""` | str | Nomarr only |
| `playlist_enabled_types` | all 5 types | list[str] | Nomarr default, plugin override |
| `playlist_half_life_days` | `30.0` | float | Nomarr only |
| `playlist_top_n` | `200` | int | Nomarr only |
| `playlist_max_songs` | `50` | int | Nomarr default, plugin override |
| `playlist_min_play_count` | `1` | int | Nomarr only |
| `playlist_min_songs` | `5` | int | Nomarr default, plugin override |

---

## Migration / Compatibility

- The API change is **additive** — one new optional field (`min_songs`), existing requests still work
- Plugin config change is **breaking** — old `pp_user_id` removed, users must reconfigure
  after plugin update (this is acceptable for alpha)
- Nomarr-side config keys are preserved as defaults; plugin overrides take precedence
- Frontend config section simplified: remove user-facing prefs, keep technical tuning

---

## Future Work

- **Multi-backbone playlists:** Per-user backbone selection, or generating playlists from
  multiple backbones for a single user (requires runtime config negotiation or a separate
  mechanism for the plugin to discover available backbones)
- **User discovery:** Plugin could use `host.UsersGetUsers()` to auto-detect users
  instead of requiring manual config entry

---

## Testing Strategy

- Backend: Unit test that service uses override params when provided, falls back to ConfigService when None
- Plugin: TinyGo unit tests following LBZ plugin pattern with mock Subsonic API
- E2E: Docker container test with Navidrome + plugin (manual for now)
