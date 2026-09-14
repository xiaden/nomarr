# Song State Machine

Nomarr tracks processing state per semantic song locator. The current application contract uses `SongIdentity` (also named `SongLocator`) and the `song_states` / `song_state_assignments` tables; generated song and library IDs remain persistence-private. State transitions are owned by the library state component and the `db.app` semantic intents.

## Current contract

State vertex identifiers and axis pairs are defined in:

```
nomarr/helpers/constants/file_states.py
```

These constants are bare state values; they are not collection-qualified names. Use `SongIdentity` values with `nomarr.components.library.library_song_state_comp` and `db.app.song_state_memberships` / `db.app.transition_song_states`. Do not construct or pass generated file/song IDs through application callers. The component validates that both vertices belong to one axis before delegating the semantic persistence intent.

Each axis has a positive and negative pole. A song holds one pole per axis:

| Axis | Positive value | Negative value |
| --- | --- | --- |
| `processed` | `processed` | `not_processed` |
| `calibrated` | `calibrated` | `not_calibrated` |
| `written` | `written` | `not_written` |
| `tags_current` | `tags_current` | `tags_not_fresh` |
| `hydrated` | `hydrated` | `not_hydrated` |
| `scanned` | `scanned` | `not_scanned` |
| `vectors_extracted` | `vectors_extracted` | `not_vectors_extracted` |
| `errored` | `errored` | `not_errored` |

A transition is valid only between the two poles of the same axis. Positive-to-negative and negative-to-positive transitions are both allowed; cross-axis transitions are rejected.

## Historical/non-operative material

Earlier versions of this page described a `file_states` API addressed by `file_ids`, including `transition_file_state()` and `db.file_states.transition()`. That model is historical and non-operative: it must not be used for new code or treated as the current persistence contract. The current owner is `nomarr/components/library/library_song_state_comp.py`, with semantic `SongIdentity` inputs and `db.app` song-state intents as described above.

## Adding a new axis

1. Add positive and negative constants to `file_states.py`.
2. Add both vertices to `ALL_STATE_VERTICES` and the pair to `AXIS_PAIRS`.
3. Extend the state-axis type.
4. Add the corresponding schema/migration data and initialize existing songs to the appropriate pole.
5. Export the constants in `__all__` where that module requires it.
