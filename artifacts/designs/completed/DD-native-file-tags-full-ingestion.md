# Native File Tags — Full Ingestion into Database — Design Document

**Status:** Draft  
**Author:** copilot  
**Created:** 2026-05-16  

**Related Documents:**

- []() —
- []() —
- []() —
- []() —
- []() —
- []() —
- []() —
- []() —
- []() —
- []() —

---

## Scope

nomarr/components/library/metadata_extraction_comp.py, nomarr/components/tagging/tag_normalization_comp.py, nomarr/workflows/library/sync_file_to_library_wf.py, nomarr/components/library/file_sync_comp.py

---

## Problem Statement

Tag normalization today applies a curated allowlist — `CANONICAL_TAGS` in `tag_normalization_comp.py` — and every tag key outside that set is silently discarded before the data reaches the database. A user who has tagged their files with `REPLAYGAIN_TRACK_GAIN`, `MUSICBRAINZ_ARTIST_ID`, `COMMENT`, `INITIALKEY`, `CATALOGNUMBER`, or any other non-canonical metadata will find those tags completely absent from the Nomarr database, preventing search, display, curation, and future writeback of anything the user had already invested in labelling.

A secondary problem exists in the current scan path: `nom:*` tags found on audio files are read back and re-persisted to the DB during scan. This is a circular write — files are projections of the DB; reading the projection back into the source of truth produces stale, potentially incorrect data. Nearly all existing library files have `nom:*` float decision tags written on them (from the era before `ml_output_streams`); without intervention, every re-scan would resurrect these already-eradicated tags in the DB.

The desired outcome: every text-representable tag present on a song file at scan time should appear as a tag vertex+edge in the database, **except** `nom:*` tags. Tags are stored under their normalized raw key name — no additional namespace prefix. `nom:*` ML tags remain the only namespaced keys, are written exclusively by the ML inference pipeline, and are **never read back from audio files during scan**.

---

## Architecture

## Tag Namespace Strategy

Three coexisting key classes in the DB after this change:

| Key class | Example key | Written by | Scan-ingest? | Write-back to file? | Curation? |
| ----------- | ------------- | ------------ | -------------- | --------------------- | ----------- |
| bare canonical | `title`, `artist`, `bpm` | scan | yes | never (DB is truth) | yes |
| bare raw | `replaygain-track-gain`, `comment` | scan | yes | never | yes |
| `nom:*` | `nom:mood-strict` | ML inference only | **never** | yes (deferred, gated) | yes |

Raw tags use the same bare-key format as canonical tags. They are distinguished only by not being in `CANONICAL_TAGS`. No prefix is applied. When `CANONICAL_TAGS` is later widened to include a key that also exists as a raw tag, the next re-scan naturally converges: the canonical write overwrites the raw value under the same key — no orphan, no collision.

`nom:*` tags on audio files are the file-projection output of the ML pipeline. The scan path must treat them as opaque write-protected projections and must never read them back into the DB. This is a one-way invariant: ML writes `nom:*` → DB → file; scan never reverses it.

---

## Extraction Pipeline Change

### Current flow

```
audio file
  └─ normalize_*(tags)          ← keeps only CANONICAL_TAGS + nom:*
       └─ all_tags: {title, artist, …, nom:mood-strict}
            └─ _apply_common_tag_fields
                 ├─ canonical fields → metadata scalars (artist, title …)
                 └─ nom:* → nom_tags dict

_sync_tags_and_entities:
  1. save_file_tags(all_tags)       ← canonical tags
  2. save_file_tags(prefixed_nom_tags)  ← nom:* read back from file ← PROBLEM
```

### Proposed flow

```
audio file
  ├─ normalize_*(tags)          ← unchanged; produces canonical + nom:* (nom:* retained
  │                                only for metadata partitioning; NOT saved to DB)
  └─ extract_raw_*(tags)        ← NEW; remaining text tags → bare normalized key
       └─ both non-nom dicts merged → all_tags

_apply_common_tag_fields (unchanged contract):
  ├─ canonical fields → metadata scalars (artist, title …)
  ├─ nom:* → nom_tags dict  (populated but never saved during scan)
  └─ everything else stays in all_tags (canonical + raw)
```

`sync_file_to_library_wf._sync_tags_and_entities` call count reduced to **one**:

1. `parsed_all_tags` — canonical + raw tags together
2. ~~`prefixed_nom_tags`~~ — **REMOVED**: `nom:*` on files are projections, not DB inputs

Raw tags ride inside `all_tags`. The `nom_tags` dict in metadata continues to be populated by `_apply_common_tag_fields` (unchanged) but the save call is deleted from the sync workflow.

---

## Key Normalization Rules for Raw Tags

Raw tag keys must be normalized to a stable, format-agnostic form:

1. **Strip format wrappers** — remove `TXXX:` (ID3), `----:com.apple.iTunes:` (MP4 freeform), no wrapper for Vorbis
2. **Lowercase** the entire remaining key
3. **Replace `_` and space** with `-`
4. **Skip** if the resulting key is in `CANONICAL_TAGS` — the canonical copy from `normalize_*` takes precedence; storing it twice is unnecessary
5. **Skip** if the resulting key starts with `nom:` — ML-owned namespace; `nom:*` values on files are stale projections. Reading them back during scan would corrupt the DB with old/float data. The scan path never writes `nom:*` to the DB under any circumstance.
6. **Skip** binary/non-text frames: `APIC`, `GEOB`, `USLT`, `SYLT`, `METADATA_BLOCK_PICTURE`, `COVERART`, `COVERARTMIME`, `covr`, `PRIV`

Collision example: `TXXX:BPM` normalizes to `bpm`; because `bpm` is in `CANONICAL_TAGS`, step 4 skips it. The canonical copy from `normalize_id3_tags` is used. If `CANONICAL_TAGS` later gains `comment`, any existing bare `comment` raw tag is simply overwritten on next re-scan — no migration needed.

---

## New Extraction Functions

Add to `tag_normalization_comp.py`:

```python
def extract_raw_mp4_tags(tags: Any) -> dict[str, str]: ...
def extract_raw_id3_tags(tags: Any) -> dict[str, str]: ...
def extract_raw_vorbis_tags(tags: Any) -> dict[str, str]: ...
```

Each function iterates ALL keys in the mutagen tag object, applies the normalization rules above, and emits `{normalized_key: json_string_value}` for every key that passes the skip rules. These are *additive* alongside the existing `normalize_*` functions, which are left entirely unchanged. The output of `extract_raw_*` is merged into the same `all_tags` dict that `normalize_*` already populates — later keys win on collision, but there should be no collision since skip rule 4 prevents duplicating canonical keys.

---

## `metadata_extraction_comp.py` Changes

`_apply_common_tag_fields` is **not modified**. Its contract (canonical scalars + nom_tags partition) remains identical.

Each format extractor (`_extract_mp4_metadata`, `_extract_flac_metadata`, `_extract_mp3_metadata`) calls the corresponding new `extract_raw_*` function and merges results into `metadata["all_tags"]` *before* calling `_apply_common_tag_fields`. Because skip rule 4 prevents canonical key duplication, `normalize_*` output and `extract_raw_*` output can be safely `dict.update`'d together.

No new keys are added to the `extract_metadata` default dict. Callers that only use canonical fields are unaffected — raw keys simply appear as additional entries in `all_tags` that those callers already ignore.

---

## `sync_file_to_library_wf.py` Changes

**Delete the `prefixed_nom_tags` save block** from `_sync_tags_and_entities`:

```python
# DELETE these lines:
nom_tags = metadata.get("nom_tags", {})
parsed_nom_tags = parse_tag_values(nom_tags) if nom_tags else {}
prefixed_nom_tags = {
    (f"nom:{name}" if not name.startswith("nom:") else name): values
    for name, values in parsed_nom_tags.items()
}
save_file_tags(db, file_id, prefixed_nom_tags)
```

The `nom_tags` key continues to be populated by `_apply_common_tag_fields` for other potential callers of `extract_metadata`; only the scan workflow's *save* call is removed. After this change, `_sync_tags_and_entities` makes exactly one `save_file_tags` call: `save_file_tags(db, file_id, parsed_all_tags)`. Raw tags ride inside `all_tags` at no extra cost.

`save_file_tags` delegates to `set_song_tags_batch`, which is idempotent and handles arbitrary `(name, value)` pairs.

---

## Write-back Behaviour

`file_write_comp.get_nomarr_tags` calls `get_song_tags(db, file_id, nomarr_only=True)` — returns only `nom:*` tags. Raw file-sourced tags (bare keys) are already excluded by this filter. `TagWriter` is namespace-scoped to `nom:`, so it never touches the non-namespaced portions of the audio file. Original raw tags on the file are therefore preserved unchanged through any Nomarr writeback cycle.

Future writeback of raw/canonical tags (e.g., user-edited title written back to file) is out of scope for this design but would require the writeback path to call `get_song_tags(nomarr_only=False)` and an extended `TagWriter` mode.

---

## ADR Compliance

| ADR | Requirement | Satisfied by |
| ----- | ------------- | -------------- |
| ADR-009 | `nom:` namespace reserved for ML | Raw tags have no `nom:` prefix; ML namespace untouched. ADR-009 write guards exist to prevent user error from clobbering ML outputs — file-sourced raw tags are scan-written, not user-written, so no guard extension is needed. |
| ADR-013 | Tag CRUD owned by tagging vertical slice | `save_file_tags` → `set_song_tags_batch` unchanged |
| ADR-008 | DB-first, deferred file writeback | Raw tags never enter `get_nomarr_tags` writeback path |
| ADR-003 | Boolean state graph invariants | No new state edges; `tags_written` state unaffected |
| ADR-014 | Tag curation via edge re-link | Raw tags are plain `(name, value)` vertices; edge re-link curation applies equally |

---

## Interaction with DD-remove-per-head-float-decision-tags

DD-remove-per-head-float-decision-tags executes **before** this DD. Its migration (V032) purges all `nom:*` float decision tags from the DB and resets `tags_written` state, forcing a tag-writeback cycle that will clear float tags from audio files.

However, V032 only affects the DB and a subsequent writeback pass. It cannot atomically remove `nom:*` tags from every audio file before the next scan runs. The window between V032 completing and a full library writeback finishing means audio files may still carry `nom:*` float tags on disk when this DD's scan path executes.

**Without this DD's nom: suppression**, those stale float tags would be re-ingested into the DB during the next scan, immediately undoing V032's cleanup. The suppression of `nom:*` in `extract_raw_*` (rule 5) and the deletion of the `prefixed_nom_tags` save in `_sync_tags_and_entities` closes this window entirely: re-scanning a file that still has `nom:*` float tags on disk produces zero `nom:*` writes to the DB.

This DD is therefore a **hard prerequisite complement** to DD-remove-per-head-float-decision-tags: V032 clears the DB; this DD prevents repopulation from disk.

---

## Migration

No schema migration required. The tag graph schema (`(name, value)` vertices + `song_has_tags` edges) already supports arbitrary name-value pairs. Existing files will gain raw tags on next re-scan. No forced re-scan is triggered; libraries on their natural scan cycle will gradually pick up the new tags.

---

## Design Goals

1. Every text-representable tag present on a song file at scan time is stored in the database, except `nom:*` tags.
2. Raw file-sourced tags and ML-generated tags are distinguishable — `nom:*` keys are ML-owned; everything else is scan-sourced. No new prefix required.
3. Raw file tags are never written back to audio files by this design (writeback is namespace-scoped to `nom:`).
4. The `nom:` namespace remains exclusively for ML-generated tags. The scan path never reads `nom:*` tags off files or writes them to the DB.
5. Implementation stays within the existing extraction pipeline — no new workers or scan phases.
6. Zero schema migration required.
7. Existing callers of `extract_metadata` that only consume canonical fields (`artist`, `title`, etc.) are not broken.
8. Web UI tag reads return a manageable set by default (canonical + `nom:*`); full raw tag access is opt-in at the query layer.
9. Stale `nom:*` float tags physically present on audio files are silently ignored during scan, preventing DD-remove-per-head-float-decision-tags from being undone by the next re-scan.

---

## Constraints

- `nom:` prefix is exclusively reserved for ML-generated tags (ADR-009). Raw file tags **must not** use the `nom:` prefix under any circumstances.
- The scan path (`sync_file_to_library_wf`) **must never write `nom:*` tags to the DB**, regardless of what is physically present on the audio file. `nom:*` DB values are owned exclusively by the ML inference pipeline's deferred-write path.
- Tag ownership stays in the tagging vertical slice; no new persistence calls may be added outside of `save_file_tags` → `set_song_tags_batch` (ADR-013).
- The boolean file-state graph (`tags_written/tags_not_written`, `tags_stale/tags_current`) must not be affected. Raw tags do not influence the `tags_written` state (ADR-003).
- The existing `normalize_*` functions in `tag_normalization_comp.py` must not be modified — their contract (canonical-only output) must be preserved. New `extract_raw_*` functions are additive.
- Web UI tag queries (`get_file_tags_with_path`, `get_song_tags`) must not return the full raw tag set by default. A `canonical_only` (or equivalent) filter mode must be available so API responses don't bloat with 50–100+ raw keys per file.

---

## Resolved Design Decisions

1. **No prefix for raw tags.** Raw tags are stored under their normalized bare key (e.g., `comment`, `replaygain-track-gain`). When `CANONICAL_TAGS` is later widened, re-scan overwrites the raw value under the same key — no orphan, no migration.

2. **No write guard for raw tags.** ADR-009 guards protect `nom:*` ML outputs from user mutation. File-sourced tags are scan-written, not user-written, and do not need the same protection.

3. **Query-layer filter needed, no per-file cap.** Web UI tag reads should default to canonical + `nom:*` only. Full raw tag access is exposed as an opt-in query parameter. No per-file raw-tag count cap is required. File writeback already reads only `nom:*` via `nomarr_only=True`; raw tags on disk are preserved unchanged by the namespace-scoped `TagWriter`.

4. **Explicit test required for Vorbis double-capture.** `extract_raw_vorbis_tags` must skip any key that normalizes to `nom:*` (i.e., the `NOM_*` Vorbis format). A dedicated unit test must verify this.

5. **No new `is_file_sourced` flag.** The frontend derives tag source from the key: `nom:*` → ML, known canonical keys → standard metadata, everything else → raw file tag. This is derivable at display time; no new DB or DTO field is warranted.

6. **Organic re-scan is acceptable.** No backfill job needed.

7. **Scan path drops the `prefixed_nom_tags` save entirely.** `nom:*` tags on audio files are projections of the DB, not inputs to it. The current scan-path save of `prefixed_nom_tags` is a design error: it creates a circular write (ML → DB → file → scan → DB) that can resurrect eradicated or stale data. Removing it is correct even independent of float-tag eradication, and is doubly necessary as a complement to DD-remove-per-head-float-decision-tags.

---
