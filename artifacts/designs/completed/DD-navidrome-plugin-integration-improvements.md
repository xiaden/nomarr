# Navidrome Plugin Integration Improvements — Design Document

**Status:** Accepted  
**Author:** rnd-dd-author  
**Created:** 2026-04-05  
**Updated:** 2026-04-05 (PatternEnforcer scope expansion — config namespace drift)

---

## Scope

Navidrome plugin integration layer — Python service (`navidrome_svc.py`), Go plugin (`main.go`), shared `backbone_id`/`library_key` contracts, observability and guard rails across the playlist generation and similar-tracks pipelines.

Also in scope following PatternEnforcer discovery: config namespace alignment, cross-layer DTO for generate-playlists response, domain exception for misconfiguration, test coverage for new/changed behaviour, and a stale design doc referencing obsolete config names.

---

## Problem Statement

Four diagnosed bugs cause silent failures in the Navidrome integration layer, and broader observability gaps make these failures invisible to operators.

**BUG 1 (HIGH):** `library_key` defaults to `""` in `navidrome_svc.generate_playlists()` (L486). When unconfigured, `compute_taste_profile` queries a vector collection named with an empty library key — which does not exist — returning `None`. The workflow then logs "No taste profile for user X" at INFO and returns `[]`. Every playlist generation silently produces nothing with no actionable signal.

**BUG 2 (HIGH — root cause of silent empty output):** `navidrome_svc.generate_playlists()` reads an entire obsolete `playlist_*` config family. `DynamicConfig` (and the web UI) uses `pp_*` keys. Because the keys never match, `ConfigService.get()` always returns the hardcoded fallback defaults — every user-configured value is silently ignored.

Full mapping of stale → live keys:

 | Service reads (stale) | `DynamicConfig` / schema key (live) | Default in schema |
 | --- | --- | --- |
 | `vector_backbone_id` | `pp_backbone_id` | `"effnet-discogs"` |
 | `playlist_enabled_types` (list) | `pp_type_familiar`, `pp_type_discovery`, `pp_type_hidden_gems`, `pp_type_genre`, `pp_type_universal` (individual booleans) | all `True` |
 | `playlist_half_life_days` | `pp_half_life_days` | `30.0` |
 | `playlist_top_n` | `pp_top_n` | `200` |
 | `playlist_max_songs` | `pp_max_songs` | `50` |
 | `playlist_min_play_count` | `pp_min_play_count` | `3` (service default is `1` — mismatch) |
 | `playlist_min_songs` | `pp_min_songs` | `10` (service default is `5` — mismatch) |
 | `playlist_max_genre_playlists` | *(no `pp_*` equivalent exists in schema)* | — |

The `backbone_id` default mismatch (original BUG 2) is a subset of this broader drift — fixing the namespace alignment resolves it for playlist generation. BUG 2 is the **primary root cause** of "no output" observed by operators.

**BUG 3 (LOW):** The Go plugin's playlist push loop (L501) calls `createPlaylist` even when `TrackNdIDs` is empty. If all file IDs fail Navidrome resolution, empty playlists are created/overwritten in Navidrome, wiping previously populated playlists.

**Observability gaps:** ANN results with no ND mappings log at DEBUG only. Missing taste profiles log at INFO. All-playlists-below-`min_songs` filtering is silent. These paths represent misconfiguration or data-absence scenarios that operators cannot detect without enabling DEBUG logging.

---

## Architecture

## Bug Fixes

### BUG 1: `library_key` Absence Handling

**Decision: Fail fast at request time with a clear error.**

In `navidrome_svc.generate_playlists()`, after resolving `library_key` from config:

- If `library_key` is empty string or `None`, raise `MisconfiguredError` immediately — do NOT pass it downstream to `compute_taste_profile`.
- Log at ERROR with structured context: `library_key=<empty>, user_id=X, backbone_id=Y`.
- The HTTP endpoint catches `MisconfiguredError` and returns `422 Unprocessable Entity` with a body indicating `library_key` is not configured.

**Rationale:** Startup-time validation was considered but rejected because `library_key` can legitimately be absent before the first library scan completes. Request-time validation with a clear error is the right balance — it does not block startup but makes the misconfiguration immediately actionable when playlist generation is attempted.

**Files changed:** `nomarr/services/domain/navidrome_svc.py` (add guard before workflow delegation), `nomarr/helpers/exceptions.py` (add `MisconfiguredError` — see Domain Exception section below).

---

### BUG 2: Config Namespace Alignment

**Decision: Align all `playlist_*` reads in `navidrome_svc.py` to the canonical `pp_*` keys from `DynamicConfig`.**

`navidrome_svc.generate_playlists()` must be updated to read the following keys:

 | Old read (remove) | New read | Notes |
 | --- | --- | --- |
 | `ConfigService.get("vector_backbone_id", "effnet-discogs")` | `ConfigService.get("pp_backbone_id", "effnet-discogs")` | Default aligns with schema |
 | `ConfigService.get("playlist_enabled_types", [...])` | Derive list from `pp_type_familiar`, `pp_type_discovery`, `pp_type_hidden_gems`, `pp_type_genre`, `pp_type_universal` | Read each bool; include type name in list if `True` |
 | `ConfigService.get("playlist_half_life_days", 30.0)` | `ConfigService.get("pp_half_life_days", 30.0)` | Same default |
 | `ConfigService.get("playlist_top_n", 200)` | `ConfigService.get("pp_top_n", 200)` | Same default |
 | `ConfigService.get("playlist_max_songs", 50)` | `ConfigService.get("pp_max_songs", 50)` | Same default |
 | `ConfigService.get("playlist_min_play_count", 1)` | `ConfigService.get("pp_min_play_count", 3)` | Default corrected to match schema (`1` → `3`) |
 | `ConfigService.get("playlist_min_songs", 5)` | `ConfigService.get("pp_min_songs", 10)` | Default corrected to match schema (`5` → `10`) |
 | `ConfigService.get("playlist_max_genre_playlists", 5)` | *(no `pp_*` key in schema — see note)* | Add `pp_max_genre_playlists: int` to `DynamicConfig`, or drop the config override and hardcode `5` |

**`pp_max_genre_playlists` decision needed (Open Question 4):** This config key has no `pp_*` equivalent in `DynamicConfig`. Two options: (a) add `pp_max_genre_playlists: int = 5` to the `DynamicConfig` dataclass and schema metadata, or (b) treat it as a fixed internal limit and remove the config read. Option (a) exposes it through the web UI consistently with other `pp_*` settings — preferred.

**Enabled types mapping:** `DynamicConfig` stores each type as an individual boolean (`pp_type_familiar`, etc.). The workflow expects a list of type name strings. The service must build this list at call time:

```python
type_flag_keys = ["familiar", "discovery", "hidden_gems", "genre", "universal"]
resolved_enabled_types = (
    enabled_types
    if enabled_types is not None
    else [t for t in type_flag_keys if self._config_service.get(f"pp_type_{t}", True)]
)
```

**`backbone_id` contract (formerly BUG 2):** With `pp_backbone_id` now the canonical read, the Python service will use the correct user-configured value. The Go plugin still does not need to send `backbone_id` for playlist generation — Python owns the config. However, adding optional `backbone_id` to `generatePlaylistsRequest` in Go remains worthwhile so operators can override per-request if needed.

**Files changed:**

- `nomarr/services/domain/navidrome_svc.py` — replace all `playlist_*` / `vector_backbone_id` reads with `pp_*` equivalents; rebuild `enabled_types` from individual flags
- `nomarr/helpers/config_schema.py` — add `pp_max_genre_playlists: int = 5` to `DynamicConfig` and its metadata dict (if option (a) chosen for Open Question 4)
- `navidrome-plugin/src/main.go` — add optional `backbone_id` to `generatePlaylistsRequest` struct (omitempty)
- `nomarr/interfaces/` — the generate-playlists endpoint handler to accept optional `backbone_id` in request body and pass it through

---

### BUG 3: Empty Playlist Guard in Go

**Decision: Skip `createPlaylist` when `TrackNdIDs` is empty.**

In the Go plugin's playlist push loop, add a guard:

```go
if len(pl.TrackNdIDs) == 0 {
    pdk.Log(pdk.LogWarn, "nomarr: skipping empty playlist ...")
    continue
}
```

This prevents creating/overwriting playlists with zero tracks. Log at WARN so operators see that playlist generation returned empty results.

**Files changed:** `navidrome-plugin/src/main.go` (add guard before `createPlaylist` call at ~L501).

---

## `backbone_id` Contract Summary

 | Endpoint | Go sends `backbone_id`? | Python source of truth | Default |
 | --- | --- | --- | --- |
 | `similar-tracks` | Yes (required) | Request body | `"effnet"` (Go default) |
 | `generate-playlists` | Optional | `ConfigService("pp_backbone_id")`, overridden by request if present | `"effnet-discogs"` (schema default) |

---

## Cross-Layer DTO: `NavidromeGeneratePlaylistsResult`

Add to `nomarr/helpers/dto/navidrome_dto.py`:

```python
from typing import Literal

@dataclass
class NavidromeGeneratePlaylistsResult:
    """Result of a generate-playlists request returned by the service layer."""
    status: Literal["ok", "no_data", "misconfigured"]
    message: str  # Human-readable; always populated, empty string for "ok"
    playlists: list  # List of playlist dicts; may be empty for "no_data"
```

`NavidromeGeneratePlaylistsResult` is the return type of `navidrome_svc.generate_playlists()`. The interface layer converts it to the HTTP response shape described in the API Response Contract section. Using a typed dataclass avoids raw dict returns and makes the `status` contract explicit across the service → interface boundary.

Export from `nomarr/helpers/dto/__init__.py`.

**Files changed:** `nomarr/helpers/dto/navidrome_dto.py`, `nomarr/helpers/dto/__init__.py`.

---

## Domain Exception: `MisconfiguredError`

`nomarr/helpers/exceptions.py` does not have a suitable precondition/config error exception. Existing exceptions (`PlaylistQueryError`, `LibraryNotFoundError`, `SubsonicApiError`) are all narrower in scope.

Add:

```python
class MisconfiguredError(ValueError):
    """Raised when a required configuration value is absent or invalid.

    Intended for request-time precondition checks in services. Interfaces
    should catch this and return 422 Unprocessable Entity.
    """
```

The service raises `MisconfiguredError("library_key not configured")` when `library_key` is empty. The interface catches it and returns `422`. This keeps HTTP concerns out of the service layer.

**Files changed:** `nomarr/helpers/exceptions.py`.

---

## Observability Improvements

### Log Level Promotions

 | Location | Current | Proposed | Condition |
 | --- | --- | --- | --- |
 | `generate_playlists_wf.py` L91 | INFO "No taste profile" | **WARN** | Always — this means the user has no usable play data or vectors are missing |
 | `find_similar_tracks_wf.py` L122 | DEBUG "N ANN results had no ND mapping" | **WARN** when unmapped > 50% of results | High unmapped ratio signals sync gap |
 | `generate_playlists_wf.py` L140 | (silent) all playlists filtered by `min_songs` | **WARN** "All N playlists filtered out (below min_songs=M)" | When output is empty but builders produced playlists |
 | `navidrome_svc.py` playlist push path | (downstream in Go) | **WARN** in Python when returning zero playlists to Go | Always when result list is empty |

### Structured Log Context

All WARN/ERROR logs in the playlist generation and similar-tracks paths should include:

- `user_id`
- `backbone_id`
- `library_key` (where applicable)
- Operation name (e.g., `"generate_playlists"`, `"find_similar_tracks"`)

Use `logger.warning("...", extra={...})` or f-string with consistent key=value format matching existing codebase style.

---

## Guard Rails

### Request-Time Precondition Checks

Add to `navidrome_svc.generate_playlists()` before calling the workflow:

1. **`library_key` is not empty** — raise `MisconfiguredError("library_key not configured")`.
2. **Vector collection exists** for the resolved `pp_backbone_id` + `library_key` — call `db.get_vectors_track_cold(backbone_id, library_key)` and check it has documents. If empty/missing, raise `MisconfiguredError("vectors not computed for backbone_id=X, library_key=Y")`.

The interface catches `MisconfiguredError` and returns `422` with a `status: "misconfigured"` body (see API Response Contract).

**Why request-time, not startup:** Both `library_key` and vector collections are populated asynchronously by the scan/ML pipeline. They may not exist at startup but will exist by the time a user has play history. Startup validation would cause false alarms.

### Go Plugin Guard Rails

1. Empty `TrackNdIDs` guard (BUG 3 fix above).
2. Log response status breakdown: after processing all playlists for a user, log summary (N created, M updated, K skipped-empty).

---

## Empty Result Signaling — API Response Contract

### Decision: Add a `status` field to the generate-playlists response

Current response shape: `{"playlists": [...]}`.

Proposed:

```json
{
  "status": "ok" | "no_data" | "misconfigured",
  "message": "Human-readable explanation (only when status != ok)",
  "playlists": [...]
}
```

- `"ok"` — playlists generated (may still be empty if user taste is very narrow).
- `"no_data"` — no play history or taste profile for this user. Not an error — normal for new users.
- `"misconfigured"` — `library_key` empty, vectors missing, or backbone mismatch. Operator action needed.

HTTP status codes:

- `200` for `"ok"` and `"no_data"`.
- `422` for `"misconfigured"`.

The service returns `NavidromeGeneratePlaylistsResult`; the interface serialises it to this shape.

The Go plugin must be updated to parse the `status` field:

- On `200` with `"no_data"` status: log at INFO, skip playlist push.
- On `422` (catches `MisconfiguredError`): log at ERROR with the `message` field, skip playlist push.
- On `200` with `"ok"`: proceed as today.

**Files changed:** Python endpoint handler (serialise `NavidromeGeneratePlaylistsResult`), `navidrome-plugin/src/main.go` (add `Status` and `Message` fields to the response struct and branch on `Status`).

---

## Test Coverage

### New test files

 | File | What to test |
 | --- | --- |
 | `tests/unit/workflows/navidrome/test_generate_playlists_wf.py` | WARN log when taste profile is absent; WARN log when all playlists filtered by `min_songs`; empty `playlists` return when all filtered |
 | `tests/unit/services/domain/test_navidrome_svc.py` | `MisconfiguredError` raised when `library_key` empty; `MisconfiguredError` raised when vector collection empty; config keys read as `pp_*` (not `playlist_*`); `enabled_types` derived correctly from individual `pp_type_*` booleans |

### Files to update

 | File | What to change |
 | --- | --- |
 | `tests/unit/workflows/navidrome/test_find_similar_tracks_wf.py` | Update log-level assertion: DEBUG → WARN for high-unmapped-ratio path (once log promotion is implemented) |

---

## Stale Artifact

`artifacts/designs/completed/DD-per-user-playlists.md` documents the old `playlist_*` config names. It should be annotated with a deprecation notice referencing this document, or updated to reflect the `pp_*` namespace. Since it is in `completed/`, a deprecation note at the top is sufficient; a full rewrite is not required.

---

## Design Goals

1. **Fix silent failures** — all bugs produce actionable errors instead of empty results.
2. **Config namespace alignment** — web UI settings are actually used; no more hardcoded default shadow.
3. **Single source of truth** — `backbone_id` contract is unambiguous across Go plugin and Python service.
4. **Operator visibility** — misconfiguration and data-absence scenarios are distinguishable in logs and API responses.
5. **Minimal scope** — no changes to reconcile, background tasks, sync workflows, or frontend.

---

## Constraints

- Go plugin is compiled as a WASM Extism plugin — changes must remain compatible with the Extism PDK and Navidrome's plugin interface.
- Python default changes must not break existing installations where `pp_backbone_id` is already explicitly configured.
- The `find_similar_tracks` endpoint already works correctly for its contract (Go sends `backbone_id`); changes should not regress it.
- No new Python dependencies. No new Go dependencies.
- Response shape changes must be backward-compatible — `status` and `message` fields are additive; `playlists` array remains at the top level.
- `DynamicConfig` changes require a forward-only migration that seeds any new keys with their schema defaults for existing installations.

---

## Open Questions

1. **Default backbone value alignment:** Should both Go and Python default to `"effnet"` (matching current Go instant-mix behaviour), or should the project standardise on `"effnet-discogs"` (matching the `DynamicConfig` schema default)? The design resolves this in favour of `"effnet-discogs"` (schema default) now that `pp_backbone_id` is the read key. Confirm.

2. **Vector collection existence check cost:** Should the guard rail that checks vector collection document count run on every playlist generation request, or should it be cached/rate-limited? For small deployments this is negligible, but worth confirming.

3. **Go plugin config for `backbone_id`:** Should the Go plugin read `backbone_id` from its config and send it for playlist generation (making the contract fully explicit), or is the "Python owns the default" approach sufficient? The design recommends adding it as optional in the Go request struct.

4. **`pp_max_genre_playlists` key:** Add to `DynamicConfig` (exposes through web UI, consistent with other `pp_*` settings) or drop the config hook and hardcode `5`? Recommended: add to schema.

5. **`DD-per-user-playlists.md` stale artifact handling:** Annotate with a deprecation header only, or fully update? Recommended: deprecation header only.
