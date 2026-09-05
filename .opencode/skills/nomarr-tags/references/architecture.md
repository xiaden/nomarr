# Tag System Architecture

## Database Schema

### `tags` (table)

| Field | Type | Notes |
| ------- | ------ | ------- |
| `id` | int | Auto-increment integer PK |
| `namespace` | `str` | Tag namespace (`nom`) |
| `name` | `str` | Key: `nom:happy_effnet_mood_happy-msd-musicnn-1` |
| `value` | `str` | Stored as string; lists are JSON-encoded |

Uniqueness is over the full `(namespace, name, value)` tuple. Relationship metadata lives on the `song_tags` edge, not the `tags` row.

### `song_tags` (join table)

Join `songs.id → tags.id` carrying edge metadata: `confidence` (`float`, default 1.0), `source` (`str`), `created_at` (epoch ms), unique over `(song_id, tag_id)` (`nomarr/persistence/models/song_tag.py`).

### `tag_model_output` (join table — provenance)

| Field | Type | Notes |
| ------- | ------ | ------- |
| `score` | `float` | Activation score from ML inference |
| `created_at` | `int` | Epoch ms |
| `updated_at` | `int` | Epoch ms |

### `ml_model_outputs` (table)

| Field | Type |
| ------- | ------ |
| `output_index` | `int` |
| `label` | `str \| None` |
| `fully_labeled` | `bool` |

### `segment_scores_stats` (table — calibration source)

| Field | Type |
| ------- | ------ |
| `head_name` | `str` |
| `tagger_version` | `str` |
| `num_segments` | `int` |
| `pooling_strategy` | `str` |
| `label_stats` | `list[{label, mean, std, min, max}]` |
| `processed_at` | `int` |

### In-memory domain: `Tags` from `nomarr/helpers/dataclasses/tags_dataclass.py` — `Tag(name: str, values: tuple[TagValue, ...])` frozen+slots, `Tags` canonicalizes (merge dup names, dedupe values, sort). Legacy `.key`/`.value`/`from_dict`/`to_db_rows` factories on `nomarr/helpers/dto/tags_dto.py` are gone — that module is a compat re-export shim. Row↔domain conversion is `nomarr/persistence/mappers/tag_mapper.py`.

---

## `nom:` Namespace Convention

- `nom` = default namespace for all Nomarr-generated tags (set in `TagWriter(namespace="nom")` and `ProcessorConfig.namespace`)
- `_ns_key(key, "nom")` applies prefix exactly once — already-prefixed keys pass through unchanged
- In DB: `namespace` + `name` columns hold the split namespace (`nom`) and the key; the full wire key is `nom:{name}` (`name` does NOT include the `nom:` prefix — see `nomarr/persistence/models/tag.py` and `tag_mapper.py`)
- During read: `get_song_tags(nomarr_only=True)` filters `tag_name.startswith("nom:")`
- Vorbis format: `nom:mood-strict` stored as `NOM_MOOD_STRICT`, normalized back on read by `tag_normalization_comp.py`
- Non-`nom:` tags (`genre`, `artist`, `album`, `title`, `year`, `bpm`) are canonical metadata read from audio files

---

## Complete ML → DB Data Flow

```
AudioFile
  └─ load_audio_mono()                [ml_audio_comp.py]      MonoLoader via essentia
  └─ preprocess → mel patches         [ml_preprocess_comp.py]
  └─ ONNXBackboneModel.run()          → embeddings[n_patches × embed_dim]
  └─ ONNXHeadModel.run(embeddings)    → segment_scores[n_patches × n_classes]
  └─ pool_scores(trimmed_mean, 10%)   → pooled_vec[n_classes]
  └─ run_head_decision(HeadSpec)      [ml_heads_comp.py]
        regression   → decide_regression()         raw float per label
        multiclass   → decide_binary_multiclass()  gated, tiered per label
        multilabel   → decide_multilabel()         gated, tiered per label
  └─ decision.as_tags(key_builder)    → {model_key: float_score}
        model_key = normalize_label(label)_{backbone}_{model_stem}
  └─ tags_accum.update(head_tags)     raw numeric scores accumulated
  └─ collect_mood_outputs()           [tagging_aggregation_comp.py]
        add_regression_mood_tiers()   regression heads → HeadOutput
        aggregate_mood_tiers()
          _compute_suppressed_keys()  intra-head + cross-head suppression
          _build_tier_term_sets()     strict / regular / loose sets
          _make_inclusive_mood_tags() → {nom:mood-strict: [...], ...}
  └─ tags_accum.update(mood_tags)
  └─ DeferredFileWrites(db_tags, ml_edges)
       async via _execute_deferred_writes():
         1. parse_tag_values(db_tags)               string → typed, always lists
         2. prefix all keys: "name" → "nom:name"
          3. save_file_tags(db, file_id, nom_tags)
              set_song_tags_batch()  [tag_write_comp.py]
                delete old song_tags rows for (song, name)
                upsert tag row: db.tags.upsert(name=name, value=value)
                upsert song_tags row: (song → tag)
         4. resolve_tag_ids() + write_tag_model_output_edges_batch()
         5. set_chromaprint()
         6. upsert_segment_stats_batch()
         7. transition_file_state → STATE_TAGGED
```

**Tag key format (built by `HeadInfo.build_versioned_tag_key()`):**
`{normalize_tag_label(label)}_{backbone}_{model_stem}`
Example: `"Happy"` from `mood_happy-msd-musicnn-1` with effnet backbone → `happy_effnet_mood_happy-msd-musicnn-1` → stored as `nom:happy_effnet_mood_happy-msd-musicnn-1`

---

## Tag CRUD Operations

### Write (ML pipeline)

`set_song_tags_batch(db, file_id, tags)` — full-replace semantics per tag name:

1. Delete existing `song_tags` rows for `(song, name)`
2. Upsert tag row `{name, value}`
3. Upsert `song_tags` row

### Calibration update (mood only)

`save_mood_tags` / `save_mood_tags_batch` — writes all three `nom:mood-*` keys; absent tiers cleared with empty value lists (edges deleted).

### Orphan cleanup

`cleanup_orphaned_tags_wf.py` — deletes tag rows with no `song_tags` joins AND no `tag_model_output` outbound rows. Called after curation relink and via `GET /library/cleanup-tag`.

Note: Tags with `tag_model_output` provenance rows but no `song_tags` links survive cleanup ("ghost" tags after curation).

### File removal

`tagging_remove_comp.remove_tags_from_file(path, "nom")` — strips all `nom:*` frames per format.

---

## Curation Operations

All curation operations are DB-only. Affected files are set to `tags_not_written` state for deferred audio writeback.

| Operation | Mechanism |
| ----------- | ----------- |
| **Rename** | Upsert new tag row, `relink_tag_edges` moves `song_tags` rows, orphan cleanup |
| **Merge** | `relink_tag_edges` from all sources to canonical target, orphan cleanup |
| **Split** | Subset of songs relinked to new tag value |
| **Commit writeback** | `write_file_tags_wf` writes pending DB tags to audio files |

---

## API Surface

### Tag read/write

- `GET /tag/show?path=` — read `nom:*` tags from audio file
- `DELETE /tag/remove?path=` — remove all `nom:*` tags from audio file
- `GET /library/file/{id}/tag?nomarr_only=` — DB tags for a file

### Tag queries

- `GET /library/file/tag/unique-keys` — all distinct tag keys
- `GET /library/file/tag/values?tag_key=` — distinct values for a key
- `GET /library/file/tag/mood-values?mood_tier=` — unique mood terms per tier
- `POST /library/file/by-tag` — search files by tag value/distance

### Curation

- `POST /tag-curation/rename` — rename tag value
- `POST /tag-curation/merge` — merge sources into canonical
- `POST /tag-curation/split` — split songs to new tag value
- `POST /tag-curation/commit` — write pending DB tags to audio files
- `GET /tag-curation/pending-count` — count files with uncommitted changes
- `PATCH /tag-curation/file/{id}/tag` — replace tags for a file+name

### Maintenance

- `POST /library/cleanup-tag` — orphan cleanup (dry_run option)
