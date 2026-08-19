---
name: tag-dataclass-migration
description: The Tag/Tags value-object landscape in Nomarr — four duplicate dataclass definitions, the 16 importers of nomarr.helpers.dto.tags_dto, field/API differences that block consolidation, and migration verification steps. Use when migrating the Tag value object, consolidating tag dataclasses, touching tags_dto.py, helpers/dataclasses/tags_dataclass.py, song_class.Tag, or any tags_dto importer.
---

# Tag Value-Object Migration

## Mental Model

Nomarr has **four** Tag/Tags dataclass definitions for the same concept ("a music tag with a name and one-or-more values"). Only one is actually used: `nomarr.helpers.dto.tags_dto` (16 importers). The other three are dead or scaffolding. The migration consolidates onto the validated `(name, values)` shape — but the validated shape rejects empty collections that the in-use v1 API produces freely, and v1 has factory/conversion methods (`from_dict`, `from_db_rows`, `to_dict`, `to_db_rows`) that the validated shape lacks. A migration is not a rename: empty-tag flows and method calls must be re-plumbed first.

## Coverage

**Documented:** All four Tag/Tags definitions + their consumers, exact v1→v2 API differences, per-file edit requirements, verification commands, adjacent non-dataclass Tag representations.
**Not yet documented:** None known.
**Last extended:** 2026-08-19

## Key Findings

### 1. The four Tag/Tags definitions

| # | Location | Shape | Consumers |
|---|----------|-------|-----------|
| 1 (IN USE) | `nomarr/helpers/dto/tags_dto.py` | `Tag(key: str, value: tuple[TagValue,...])`, `Tags(items)` — frozen, **no validation**, empty allowed | 16 (see below) |
| 2 (DEAD) | `nomarr/helpers/dataclasses/tags_dataclass.py` | `Tag(name: str, values: tuple[TagValue,...])`, `Tags(items)` — frozen+slots, **validated**, non-empty required | **ZERO** (only its own `__init__.py` re-export) |
| 3 (V2 SCAFFOLDING) | `v2/nomarr/helpers/dataclasses/tags_dataclass.py` | identical to #2 | only other unused `v2/nomarr/...` dataclasses (TYPE_CHECKING) |
| 4 (DEAD) | `nomarr/components/library/songs/song_class.py:21-26` | `Tag(name: str, value: str)` — **scalar** value | **ZERO** (`grep song_class` = 0 matches; `Song` allowlisted in deadcode_allowlist.py:1009) |

- `TagValue = str | int | float | bool` — identical in all files; `tag_write_comp.py` and `tag_parsing_comp.py` import only `TagValue` and are **unaffected** by the migration.
- The skill `library-files-data-flow` claims song_class is used by playlist import / embedding research — **stale**; verified zero importers.

### 2. Importers of `nomarr.helpers.dto.tags_dto` (16)

Production (12): `helpers/dto/__init__.py:96` (re-export — no external consumers of the re-export), `helpers/dto/processing_dto.py:17,173` (type-only), `workflows/processing/process_file_wf.py:36,85,138,192,267`, `components/processing/file_write_comp.py:20,73,91,112-113,126,152-153`, `workflows/processing/write_file_tags_wf.py:37,58-87`, `workflows/calibration/write_calibrated_tags_wf.py:67,95` (type-only), `components/tagging/tag_query_comp.py:9,153-190`, `components/tagging/tagging_aggregation_comp.py:15,338-345`, `components/tagging/tagging_reader_comp.py:11,22-30,51-92`, `components/tagging/tagging_writer_comp.py:25,245-280`, `components/tagging/tag_write_comp.py:13` (TagValue only), `components/tagging/tag_parsing_comp.py:14` (TagValue only).

Indirect consumer: `workflows/library/file_tags_io_wf.py:42` calls `tags.to_dict()` on `read_tags_from_file()` result (no import).

Tests (4): `tests/unit/components/processing/test_file_write_comp.py:18,127,146,162,190`, `tests/unit/workflows/calibration/test_apply_calibration_wf.py:11,43`, `tests/unit/workflows/calibration/test_write_calibrated_tags_wf.py:13,20-22`, `tests/unit/workflows/processing/test_write_file_tags_wf.py:7,16-18,65`.

### 3. API differences that block consolidation (v1 tags_dto → v2 tags_dataclass)

| Aspect | v1 (tags_dto) | v2 (tags_dataclass) | Breaks |
|--------|---------------|---------------------|--------|
| Tag field names | `key`, `value` | `name`, `values` | all `.key`/`.value` readers + constructors |
| Empty `Tags(items=())` | allowed | **ValueError** | write_file_tags_wf `_filter_tags_for_mode` "none" mode (line 80), tagging_aggregation_comp `aggregate_mood_tags` (line 343), test_apply_calibration_wf:43, test_write_file_tags_wf:65 |
| Empty dict → `from_dict({})` | allowed | **ValueError** (via empty items) | process_file_wf:85,138,192 |
| `Tag(key=..., value=None)` | allowed (no validation) | **TypeError** | test_write_file_tags_wf.py:18 |
| `from_dict` | yes | **NO** | tagging_aggregation_comp:345 |
| `from_db_rows` | yes | **NO** | tag_query_comp:166,189 |
| `to_dict` | yes (always-tuple) | **NO** | tagging_writer_comp:251,275; file_tags_io_wf:42 |
| `to_db_rows`, `has_key`, `has_value` | yes | NO | — (no current callers) |
| `get_values` miss | returns `()` | **raises KeyError** | — (no current callers, but semantic trap) |
| `has_name` | NO | yes | — |
| Sort | plain by key | casefold-then-name, merges dups, dedupes values | deterministic output changes |

### 4. Pre-existing / concurrent changes

Working tree was dirty at research start (`song_tags_comp.py` + its test); a concurrent session committed those as `ffb77d1c "Fix song tag row contract"` (matches log L105 KeyError 'type' fix) during this research. Branch `feat/develop-branch-migration`. **The repo is live — re-verify git status before editing.**

## Critical Invariants

1. `Tags.from_dict({})` / `Tags(items=())` appear in **happy paths**, not error paths (process_file_wf returns empty Tags for not-found/crash/skipped files; write_file_tags_wf "none" mode is the clear-namespace API contract). Any v2-style migration must keep an empty-tags representation (`None` or an explicitly-allowed empty container) or change these call sites to `None`.
2. `to_dict()` output is consumed by mutagen writers as `Mapping[str, object]` — tuple values are the contract (v2 would need an equivalent adapter).
3. Sibling DTO cross-import within `helpers/dto/` is the documented, allowed pattern (`.opencode/skills/nomarr-layers/references/helpers.md:48` uses tags_dto as its example) — moving the canonical class changes that doc.
4. ADR-041 (Domain Dataclasses as the Persistence-Component Contract) and ADR-032 mandate domain dataclasses over TypedDicts at the facade boundary; the persistence-domain-model skill documents three separate tag representations (tags_dataclass domain, tags_dto DTO, repo_dto TagRow) as a known proliferation.

## Sources

- `nomarr/helpers/dto/tags_dto.py` (full read)
- `nomarr/helpers/dataclasses/tags_dataclass.py` + `__init__.py` (full read)
- `v2/nomarr/helpers/dataclasses/tags_dataclass.py`, `song_dataclass.py` (full read)
- `nomarr/components/library/songs/song_class.py` (full read)
- All 16 importer files (read or symbol-grepped)
- ADR-041, ADR-032 (via persistence-domain-model skill), deadcode_allowlist.py
- Log L108 (this research), L105 (tag row contract), L99 (hydration facade)
