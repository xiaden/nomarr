# Task: Replace spotipy with librespot OAuth + direct Web API

## Problem Statement

Spotify has stopped accepting new developer app registrations, making the current Spotify playlist import feature dead for all new users. The existing implementation uses `spotipy` with Client Credentials flow, which requires a Spotify Developer App (`client_id` + `client_secret`).

The solution: use `librespot` for OAuth authentication (browser-based user login, no dev app needed), then call the Spotify Web API directly with `requests` (already used by the Deezer fetcher). Keep the existing dev-credentials path as fallback for users who already have them.

Affected files:

- `nomarr/components/playlist_import/spotify_fetcher_comp.py` — rewrite to use requests + bearer token
- `nomarr/workflows/playlist_import/convert_playlist_wf.py` — update `_fetch_spotify` to support dual auth paths
- `nomarr/services/domain/playlist_import_svc.py` — add librespot session management, update config
- `nomarr/interfaces/api/web/playlist_import_if.py` — add OAuth flow endpoints
- `nomarr/interfaces/api/types/playlist_import_types.py` — new request/response types for OAuth
- `nomarr/interfaces/api/web/dependencies.py` — update service wiring
- `nomarr/services/infrastructure/config_svc.py` — keep existing config keys, no new ones needed
- `frontend/src/shared/api/playlistImport.ts` — add OAuth API calls
- `frontend/src/features/playlist-import/PlaylistImportPage.tsx` — add "Connect with Spotify" flow
- `frontend/src/features/config/components/ConfigField.tsx` — update descriptions
- `pyproject.toml` / `requirements.txt` — add `librespot`, remove `spotipy`

## Phases

### Phase 1: Add librespot dependency and validate it works

- [ ] Add `librespot` to `pyproject.toml` and `requirements.txt`, remove `spotipy`
- [ ] Create a throwaway script to verify librespot OAuth flow works (browser opens, token obtained, playlist fetched via requests)
- [ ] Verify librespot credential persistence (`credentials.json`) works across restarts
- [ ] Delete throwaway script after validation

### Phase 2: Rewrite spotify_fetcher_comp to use requests instead of spotipy

- [ ] Rewrite `create_spotify_client` to accept a bearer token string and return a thin wrapper or just the token
- [ ] Rewrite `fetch_spotify_playlist` to call `api.spotify.com/v1/playlists/{id}` with `requests` + bearer token
- [ ] Rewrite `_fetch_all_tracks` to handle pagination via `requests` (follow `next` URLs)
- [ ] Keep `_extract_track` unchanged (same JSON shape from Web API)
- [ ] Keep exception classes `SpotifyFetchError`, `SpotifyCredentialsError`
- [ ] Run `lint_project_backend` on `nomarr/components/playlist_import`

### Phase 3: Add librespot session management to the service layer

- [ ] Create `nomarr/components/playlist_import/spotify_auth_comp.py` with librespot OAuth session creation and token acquisition
- [ ] Add `get_spotify_token()` function that returns a bearer token from either librespot session or client credentials
- [ ] Handle credential storage path (configurable, defaults to nomarr data dir)
- [ ] Add `is_spotify_user_authenticated()` check (credentials.json exists and session is valid)
- [ ] Run `lint_project_backend` on `nomarr/components/playlist_import`

### Phase 4: Update workflow and service to support dual auth paths

- [ ] Update `PlaylistImportConfig` to add `spotify_credentials_path: str | None` field
- [ ] Update `PlaylistImportService` to expose `has_spotify_credentials()` that returns True if EITHER dev creds or librespot session exists
- [ ] Add `start_spotify_oauth()` method to service that initiates librespot OAuth and returns the auth URL
- [ ] Add `check_spotify_oauth_complete()` method to service that checks if OAuth completed successfully
- [ ] Update `_fetch_spotify` in workflow to accept a bearer token instead of client_id/secret
- [ ] Update `convert_playlist_workflow` signature: replace `spotify_client_id`/`spotify_client_secret` with `spotify_token: str | None`
- [ ] Update `PlaylistImportService.convert_playlist` to resolve the token from whichever auth source is available
- [ ] Run `lint_project_backend` on `nomarr/workflows/playlist_import` and `nomarr/services/domain`

### Phase 5: Add API endpoints for OAuth flow

- [ ] Add `SpotifyOAuthStartResponse` and `SpotifyOAuthStatusResponse` types to `playlist_import_types.py`
- [ ] Add `POST /playlist-import/spotify-oauth/start` endpoint that initiates OAuth and returns auth URL
- [ ] Add `GET /playlist-import/spotify-oauth/status` endpoint that checks if OAuth completed
- [ ] Update `GET /playlist-import/spotify-status` to reflect both auth methods (dev creds OR user OAuth)
- [ ] Update `SpotifyCredentialsStatusResponse` to include `auth_method: Literal["none", "dev_credentials", "user_oauth"]`
- [ ] Run `lint_project_backend` on `nomarr/interfaces`

### Phase 6: Update frontend for dual auth flow

- [ ] Update `playlistImport.ts` API module: add `startSpotifyOAuth()` and `getSpotifyOAuthStatus()` functions, update `SpotifyStatusResponse` type
- [ ] Update `PlaylistImportPage.tsx`: replace static warning with "Connect with Spotify" button when no auth is configured
- [ ] Add OAuth flow UI: button triggers OAuth start, opens auth URL in new tab, polls status until complete
- [ ] Update `ConfigField.tsx` descriptions for `spotify_client_id`/`spotify_client_secret` to note they're optional if user OAuth is used
- [ ] Build frontend with `npm run build` in `frontend/` and verify no TypeScript errors

### Phase 7: Validation and cleanup

- [ ] Run `lint_project_backend` on full workspace
- [ ] Run `lint_project_frontend`
- [ ] Verify existing unit tests pass (especially playlist import tests)
- [ ] Update `readme.md` playlist import section to mention both auth methods
- [ ] Verify `dockerfile` / `dockerfile.base` don't need changes (librespot is pure Python)

## Completion Criteria

- Spotify playlist import works via user OAuth (no dev app required)
- Existing dev credential path still works for users who have them
- Frontend shows "Connect with Spotify" when neither auth method is configured
- Frontend shows configured status when either auth method is available
- All linting passes (backend + frontend)
- No `spotipy` dependency remains
- `librespot` is the only new dependency

## References

- librespot-python: <https://github.com/kokarare1212/librespot-python>
- Current fetcher: `nomarr/components/playlist_import/spotify_fetcher_comp.py`
- Deezer fetcher (pattern to follow for requests-based approach): `nomarr/components/playlist_import/deezer_fetcher_comp.py`
