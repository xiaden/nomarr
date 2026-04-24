# Schema Constructor Migration Map

This map records the final replacement path from legacy persistence AQL modules to the constructor-backed `Database` surface.

## Simple Collections (Plans B + F)

 | Legacy module | Constructor replacement | Notes |
 | --------------- | ------------------------- | ------- |
 | `meta_aql.py` | `db.meta.get(...)`, `db.meta._key.get(...)`, `db.meta._key.upsert([...], match_field="_key")` | Meta reads/writes are now standard collection + field verbs. |
 | `migrations_aql.py` | `db.migrations.insert([...])`, `db.migrations._key.get(...)`, `db.migrations.get.many.by_filter({...}, limit=...)` | Applied migration tracking is constructor-backed. |
 | `health_aql.py` | `db.health.insert([...])`, `db.health.get.many.by_filter({...}, limit=...)`, `db.health.delete([...])` | No custom operations remain. |
 | `sessions_aql.py` | `db.sessions._key.get(...)`, `db.sessions._key.upsert([...], match_field="_key")`, `db.sessions.delete([...])` | Session persistence uses normal collection verbs. |
 | `locks_aql.py` | `db.locks.insert([...])`, `db.locks.get.many.by_filter({...}, limit=...)`, `db.locks.delete([...])` | Locks stay standard CRUD; no lock-only verb exists. |
 | `vram_promises_aql.py` | `db.vram_promises.insert([...])`, `db.vram_promises.get.many.by_filter({...}, limit=...)`, `db.vram_promises.delete([...])` | Promise rows map directly to constructor verbs. |
 | `worker_claims_aql.py` | `db.worker_claims.insert([...])`, `db.worker_claims.file_id.get(...)`, `db.worker_claims.worker_id.get.many(...)`, `db.worker_claims.delete([...])` | Claim orchestration now composes field + collection verbs in component code. |
 | `worker_restart_policy_aql.py` | `db.worker_restart_policy._key.get(...)`, `db.worker_restart_policy._key.upsert([...], match_field="_key")` | Restart policy persistence is constructor-backed. |
 | `ml_capacity_aql.py` | `db.ml_capacity._key.get(...)`, `db.ml_capacity._key.upsert([...], match_field="_key")` | Capacity snapshots no longer need raw AQL helpers. |
 | `library_pipeline_states_aql.py` | `db.library_pipeline_states._key.get(...)`, `db.library_pipeline_states._key.upsert([...], match_field="_key")` | Pipeline state rows use standard key-based verbs. |

## Library Files + Library Graph (Plan D + F)

 | Legacy module | Constructor replacement | Notes |
 | --------------- | ------------------------- | ------- |
 | `library_files_aql/crud.py` | `db.library_files.path.get(...)`, `db.library_files.insert([...])`, `db.library_files._id.update(...)`, `db.library_files.path.upsert([...], match_field="path")` | Core file create/update/upsert logic is field-verb driven. |
 | `library_files_aql/reconciliation.py` | `db.library_files.get.many(...)`, `db.worker_claims.insert([...])`, `db.worker_claims.file_id.get(...)`, `db.worker_claims.delete([...])`, `db.file_states.transition([...], ...)` | Reconciliation composes library, claim, and state verbs instead of custom query helpers. |
 | `library_files_aql/stats.py` | `db.library_files.artist.aggregate(...)`, `db.library_files.album.aggregate(...)`, `db.library_files.get.many.by_filter({...}, limit=...)` | Stats and search moved to constructor aggregation/filter verbs. |
 | `libraries_aql.py` | `db.libraries.insert([...])`, `db.libraries.get(...)`, `db.libraries._key.get(...)`, `db.libraries.traversal(..., "library_contains_file")`, `db.libraries.cascade([...])` | Library graph access is now traversal/cascade-based. |
 | `file_states_aql.py` | `db.file_states.traversal(..., "file_has_state")`, `db.file_states.transition([...], from_state, to_state)` | State-graph queries now use traversal + transition. |
 | `library_contains_file` helper queries | `db.library_contains_file._to.upsert([...], match_field=["_from", "_to"])`, `db.library_contains_file._to.get.many(...)`, `db.library_contains_file._to.delete(...)` | Edge maintenance is constructor-native. |
 | `file_has_state` helper queries | `db.file_has_state.insert([...])`, `db.file_has_state._from.delete(...)`, `db.file_has_state._to.get.many(...)` | Edge creation and cleanup use normal edge verbs. |

## Tags (Plan C + F)

 | Legacy module | Constructor replacement | Notes |
 | --------------- | ------------------------- | ------- |
 | `tags_aql` package | `db.tags.value.upsert([...], match_field=["rel", "value"])`, `db.tags.get.many.by_filter({...}, limit=...)`, `db.tags.rel.get.many(...)`, `db.tags.rel.collect(...)`, `db.tags.traversal(..., "song_has_tags")`, `db.tags.cascade([...])` | Tag creation, lookup, traversal, and orphan cleanup all use constructor verbs. |
 | `song_has_tags` helper queries formerly embedded in tag AQL | `db.song_has_tags._from.get.many(...)`, `db.song_has_tags._to.get.many(...)`, `db.song_has_tags.count_by_filter({...})`, `db.song_has_tags.insert([...])`, `db.song_has_tags.delete([...])` | Edge-side tag reads/writes are composed directly in components. |

## Analytics (Plan E + F)

 | Legacy module | Constructor replacement | Notes |
 | --------------- | ------------------------- | ------- |
 | `calibration_state_aql.py` | `db.calibration_state._key.upsert([...], match_field="_key")`, `db.calibration_state._id.collect(...)`, `db.calibration_state.get.many(...)`, `db.model_has_calibration._key.get(...)`, `db.calibration_state.delete([...])`, `db.calibration_state.truncate()` | Calibration state persistence is now split across constructor verbs plus the calibration edge collection. |
 | `calibration_history_aql.py` | `db.calibration_history.insert([...])`, `db.calibration_history.calibration_key.get.many(...)`, `db.calibration_history.delete([...])`, `db.calibration_history.truncate()` | History retention and pruning now use constructor field verbs. |
 | analytics tag-join AQL in mood/calibration components | `db.tags.rel.get.many(...)`, `db.tags.rel.collect(...)`, `db.song_has_tags._to.get.many(...)`, `db.libraries.traversal(..., "library_contains_file")`, `db.ml_models.get(...)` | Cross-collection analytics now compose paginated constructor reads in Python. |

## ML + Vector Collections (Plan E + F)

 | Legacy module | Constructor replacement | Notes |
 | --------------- | ------------------------- | ------- |
 | `ml_models_aql.py` | `db.ml_models._id.collect(...)`, `db.ml_models.get.many(...)`, `db.ml_models.path.get(...)`, `db.ml_models.path.upsert([...], match_field="path")`, `db.ml_models.traversal(..., "model_has_output")`, `db.ml_models.delete([...])` | Model registry reads and writes are constructor-backed. |
 | `ml_model_outputs_aql.py` | `db.ml_model_outputs._key.get(...)`, `db.ml_model_outputs.insert([...])`, `db.ml_model_outputs._key.update(...)`, `db.ml_model_outputs.delete([...])` | Output rows no longer need raw UPSERT helpers. |
 | `segment_scores_stats_aql.py` | `db.segment_scores_stats._key.upsert([...], match_field="_key")`, `db.segment_scores_stats.head_name.get.many(...)`, `db.segment_scores_stats.cascade([...])`, `db.segment_scores_stats.truncate()` | Segment-score storage and cleanup use standard constructor verbs. |
 | `tag_model_output_aql.py` | `db.tag_model_output._from.get.many(...)`, `db.tag_model_output._key.update(...)`, `db.tag_model_output.insert([...])`, `db.tag_model_output._from.delete(...)`, `db.tag_model_output._to.delete(...)` | Tag/output edge maintenance is constructor-native. |
 | `navidrome_tracks_aql.py` | `db.navidrome_tracks._key.upsert([...], match_field="_key")`, `db.navidrome_tracks._key.collect(...)`, `db.navidrome_tracks.traversal(..., "has_nd_id")`, `db.navidrome_tracks.cascade([...])` | Navidrome track graph persistence uses key, traversal, and cascade verbs. |
 | `navidrome_playcounts_aql.py` | `db.navidrome_playcounts.get(...)`, `db.navidrome_playcounts._key.upsert([...], match_field="_key")`, `db.navidrome_playcounts.userid.get.many(...)`, `db.navidrome_playcounts.userid.delete(...)` | Playcount buckets migrated to field + collection verbs. |
 | `vectors_track_aql/` | `db.register_vectors_track_backbone(...)`, `db.get_vectors_track_cold(...)`, `db.get_vectors_track_maintenance(...).ensure_cold_collection()`, `db.get_vectors_track_maintenance(...).get_stats()`, `hot._id.collect(...)`, `cold._key.upsert([...], match_field="_key")`, `hot.truncate()` | Hot/cold vector workflows now use the constructor-backed dynamic namespaces plus maintenance helper namespace. |

## Cleanup Outcome (Plan F)

- `nomarr/persistence/database/` is now an empty namespace stub.
- All live callers go through `nomarr.persistence.db.Database` and constructor-backed namespaces.
- Raw AQL remains valid only in migrations and the constructor/persistence internals that intentionally own query assembly.
