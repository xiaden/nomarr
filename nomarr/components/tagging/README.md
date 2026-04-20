# Tagging Components

Tag reading, writing, normalization, aggregation, and mood tier computation for audio file metadata.

## Responsibilities

- Read and write namespaced tags (nom:*) across MP3/MP4/FLAC formats
- Normalize tags from format-specific representations to canonical names
- Parse tag values (JSON arrays, semicolons, numeric types)
- Aggregate head outputs into mood tier collections (strict/regular/loose)
- Reconstruct head outputs from stored statistics for re-aggregation
- Safe file writes with copy-modify-verify-replace pattern
- Remove namespaced tags from files

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `tagging_reader_comp` | Read namespaced tags from audio files, infer write mode from existing tags |
 | `tagging_writer_comp` | Format-aware `TagWriter` with direct and safe (atomic) write modes |
 | `safe_write_comp` | Copy-modify-verify-replace write pattern with audio property validation |
 | `tagging_remove_comp` | Remove all namespaced tags from a file (MP3 TXXX, MP4 freeform, Vorbis) |
 | `tag_normalization_comp` | Normalize format-specific tags (ID3, MP4, Vorbis) to canonical names |
 | `tag_parsing_comp` | Parse tag value strings into typed lists (JSON, semicolons, floats, ints) |
 | `tagging_aggregation_comp` | Aggregate HeadOutputs into mood-strict/regular/loose with conflict suppression |
 | `tagging_reconstruction_comp` | Reconstruct HeadOutputs from DB statistics for re-aggregation after calibration |
 | `mood_labels_comp` | Normalize model labels (non_*→ not_*) |

## Patterns

- **Safe writes:** `safe_write_comp` copies the file, writes to the copy, probes audio properties (duration, sample rate, channels) to verify integrity, then atomically replaces. Hardlink strategy avoids folder mtime changes where supported.
- **Inclusive tiers:** Mood tiers are inclusive: strict ⊂ regular ⊂ loose. A label in strict also appears in regular and loose.
- **Conflict suppression:** Semantic opponent labels (e.g., happy vs sad) are suppressed when both sides have tiers, preventing contradictory tags.
- **Format abstraction:** Each writer (MP3/MP4/Vorbis) handles format-specific tag storage — ID3 TXXX frames, iTunes freeform atoms, Vorbis comments with uppercase key convention.

## Dependencies

- **Upstream:** Called by `workflows/` (tag write workflow, reconciliation) and `ml/inference/` (mood aggregation)
- **Downstream:** Calls `persistence/` directly, `helpers/` for LibraryPath and Tags DTOs
- **External:** `mutagen` (tag read/write)
