---
name: frontend-api-contract
description: Frontend-backend API contract alignment for Nomarr — wire format rules (file_id int, bool true/false), confirmed type mismatches (LibraryPipelineStatus.state, SongListResult.song_ids, LibraryFile.calibration), the api_coverage tooling and its path bugs, and which backend endpoints are genuinely unused. Use when touching frontend/src/shared/api/*, shared/types.ts, or the api_coverage scripts, or when fixing frontend type/test errors against the backend API.
---

# Frontend API Contract

## Mental Model

The frontend API layer lives in `frontend/src/shared/api/*.ts` (one module per backend domain: files, library, metadata, ml, vectors, navidrome, tagCuration, analytics, calibration, config, auth, apiKey, filesystem, playlistImport, tags, processing). All requests go through `client.ts` (`request/get/post/put/patch/del`), which injects the session token, normalizes errors to `ApiError`, and supports an opt-in `transformCase` (snake→camel). Most API modules use raw snake_case wire shapes and do NOT transform case; `library.ts` maps responses manually to camelCase `Library`.

Backend wire rules (from `nomarr/interfaces/api/id_codec.py` and `types/`):
- `file_id` on the wire is an **INTEGER** (`encode_id` is a pass-through ensuring int type). Non-numeric strings in `file_id` path/body positions 400 via `decode_path_id`.
- Booleans serialize as `true`/`false` (Pydantic coerces DB 0/1).
- `library_name` path params are the URL-encoded natural library name (`encodeURIComponent` on the client, `decode_library_name` on the server).
- `entity_id` metadata path params are natural tag values (str), URL-encoded.
- Backend endpoint paths are kebab-case full words (ADR-020).

## Coverage

**Documented:** wire format rules; confirmed type mismatches; api_coverage tooling bugs + how to run it corrected; genuinely-unused endpoints; test-fixture hazards.
**Not yet documented:** per-endpoint exhaustive request/response field audit (only the files/library/metadata/ml/tag-curation surfaces were audited Aug 2026); navidrome and analytics deep audits.
**Last extended:** 2026-08-31

## Key Findings

### API coverage tooling is broken (path off-by-one) — workaround
- `scripts/human-scripts/check_api_coverage.py:27` computes `project_root = Path(__file__).parent.parent` = `scripts/` → scans nonexistent `scripts/frontend/src` (0 refs) and writes `scripts/scripts/outputs/api_coverage.html`.
- `scripts/human-scripts/tools/api_coverage/discovery.py` has the same off-by-one for its own `project_root` (4 parents instead of 3) → `ts_file.relative_to(project_root)` raises and is swallowed → 0 refs.
- Corrected run: `.venv/bin/python - <<EOF` with `sys.path.insert(0, "scripts/human-scripts")`, explicit `project_root = Path("/workspace/nomarr")`. Result: 100 backend routes, ~91 used; 0 `.tsx` files contain raw `/api/` strings (all endpoints live in `.ts` modules).
- Scanner only matches `*.ts`, literal/template `/api/...` strings. Trailing `${params}` template suffixes (analytics.ts) and `/api/web/library${query}` (library.ts:69) are matcher false-negatives — account for them manually.

### Confirmed contract mismatches (frontend type vs backend response)
- **`LibraryPipelineStatus.state`** — `frontend/src/shared/api/library.ts:202-210` declares `state: string`; backend `PipelineStatusResponse` (nomarr/interfaces/api/types/library_types.py:458-490) has NO `state` — only `scan_state`, `ml_state`, `calibration_state`, `tag_write_state` (+ counts/auto_write/file_write_mode). `getPipelineStatus` has NO production consumer; only `library.test.ts:70-91` exercises it with a fixture containing `state: "write_ready"` (consistent with the wrong type). Either delete the function+test or fix type to the 4-axis shape.
- **`SongListResult.song_ids: string[]`** — `frontend/src/shared/types.ts:70`; backend `SongListResponse.song_ids: list[int]` (encoded) (metadata_types.py:43-54). `LibraryBrowser.tsx:140` feeds these into `getFilesByIds(string[])`; works only via Pydantic int→str coercion. Fix: `song_ids: number[]` and `getFilesByIds(fileIds: Array<string | number>)`.
- **`LibraryFile.calibration?: string`** — `frontend/src/shared/api/files.ts:24`; backend field is `calibration_version` (library_types.py `LibraryFileWithTagsResponse`). Never read anywhere in the frontend — stale, safe to delete or rename.
- Dashboard `WorkStatus.pipeline_libraries[].state` (processing.ts:25-30) is CORRECT — backend `LibraryPipelineInfoResponse` (info_types.py:190-206) does have `state`. Do not "fix" that one.

### Wire-format hazards in test fixtures (pass because client is mocked)
- `useLibrarySearch.test.ts:64-65` `tagged: 0` / `skip_auto_tag: 0` → TS2322 build errors; backend sends true/false. Use booleans.
- `files.test.ts:46` `["file-1","file-2"]` and `tagCuration.test.ts:43,48,92` `"file-123"`/`"file-1"` — non-numeric ids would 400 against a real backend (`decode_path_id`). Real ids are numeric or digit-strings.
- `tag_curation_if.py` PATCH `/file/{file_id}/tag` takes raw `file_id: str` (no decode) — inconsistent with songs_if `GET /file/{file_id}/tag` which decodes. Tag-curation response ids (`TagSongItemResponse.file_id`) are backend-produced strings.

### Genuinely unused backend endpoints (no frontend reference anywhere)
`POST /library/clear-data`, `POST /{library_name}/reconcile`, `POST /{library_name}/retry-errored`, `POST /{library_name}/validate-tag`, `POST /navidrome/playlist/static`, `POST /navidrome/sync-song`, `GET /metadata/album/{album_id}/artist`, `/api/v1/info`, `/api/v1/navidrome/*`, `GET /health`, `GET /health/gpu`, `GET /info`, `GET /{full_path:path}` catch-all. (retry-errored has a backend response model `RetryErroredResponse{retried}` and frontend `getErroredFiles` exists — but no retry client function.)

### Confirmed-matching contracts (do NOT change)
- `search()` query params q/artist/album/tag_key/tag_value/tagged_only/limit/offset ↔ songs_if.py:59 `SearchFilesQuery` (note backend default limit=100, frontend default 200 in useLibrarySearch).
- `getFilesByIds` body `{file_ids}` ↔ `FileIdsRequest{file_ids: list[str], max_length=500}`.
- `searchByTag` body ↔ `TagSearchRequest{tag_key, target_value: float|str, limit, offset}`.
- `getUniqueTagKeys`/`getTagValues`/`getMoodValues` query params ↔ songs_if.py:139-196 (nomarr_only/tag_key/mood_tier/limit).
- `updateWriteMode` uses `?file_write_mode=` query param ↔ library_scan_if.py:226-229 (Query param, not body).
- `getRecentActivity` `library_id` query param ↔ ml_if.py:203.
- `updateFileTags` body `{name, values}` ↔ `UpdateFileTagsRequest` (tag_curation_if.py:59-61).
- `listSongsForEntity` requires `name` query param (metadata_if.py:74).
- ml endpoints model_id/output_id are `str` path params on both sides.
- `scanQuick/scanFull/repairTags` POST `{}` to endpoints with no body param (FastAPI ignores) — harmless.

## Critical Invariants
- Never type `file_id` as a non-numeric string for songs_if endpoints — the backend decodes and 400s.
- Never use numeric literals (`0`/`1`) for boolean API fields in fixtures — backend serializes true/false.
- The coverage tooling's "0 references" output is ALWAYS the path bug, never reality — run with the corrected project_root.
- ADR-020: all REST URL segments kebab-case full words; `file_id` remains a path segment in `/api/web/library/file/{file_id}/tag` (not yet renamed to a full word).

## Sources
- `frontend/src/shared/api/files.ts`, `library.ts`, `metadata.ts`, `processing.ts`, `tagCuration.ts`, `client.ts`
- `frontend/src/shared/types.ts`
- `nomarr/interfaces/api/web/songs_if.py`, `library_if.py`, `library_scan_if.py`, `ml_if.py`, `metadata_if.py`, `tag_curation_if.py`, `info_if.py`
- `nomarr/interfaces/api/types/library_types.py`, `metadata_types.py`, `info_types.py`
- `nomarr/interfaces/api/id_codec.py`
- `scripts/human-scripts/check_api_coverage.py`, `scripts/human-scripts/tools/api_coverage/*`
- `artifacts/decisions/ADR-020-rest-api-naming-convention-kebab-case-full-words.md`
