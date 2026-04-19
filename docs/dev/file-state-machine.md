# File State Machine

Nomarr tracks per-file processing status through a boolean state graph stored in the `file_states` ArangoDB collection. Each file can simultaneously hold one vertex per axis — every axis is an independent boolean.

## Canonical definitions

All state vertex identifiers and axis pairs are defined in one place:

```
nomarr/helpers/constants/file_states.py
```

Import from there everywhere. Never hard-code `"file_states/tagged"` strings in other modules.

## Axes and vertex pairs

Each axis has exactly two poles: a **positive** vertex and a **negative** vertex. A file holds one pole per axis at any given time.

| Axis | Positive vertex | Negative vertex |
|------|----------------|----------------|
| `tagged` | `file_states/tagged` | `file_states/not_tagged` |
| `too_short` | `file_states/too_short` | `file_states/not_too_short` |
| `calibrated` | `file_states/calibrated` | `file_states/not_calibrated` |
| `tags_written` | `file_states/tags_written` | `file_states/tags_not_written` |
| `tags_current` | `file_states/tags_current` | `file_states/tags_stale` |
| `scanned` | `file_states/scanned` | `file_states/not_scanned` |
| `vectors_extracted` | `file_states/vectors_extracted` | `file_states/not_vectors_extracted` |
| `errored` | `file_states/errored` | `file_states/not_errored` |

These are exposed as `AXIS_PAIRS: dict[StateAxis, tuple[str, str]]` — a dict from axis name to `(positive_vertex, negative_vertex)`.

## Valid transitions

A transition is valid **if and only if** `from_state` and `to_state` are the two poles of the same axis. Cross-axis transitions (e.g., moving from `tagged` to `scanned`) are invalid.

```
tagged      ↔  not_tagged
too_short   ↔  not_too_short
calibrated  ↔  not_calibrated
tags_written ↔  tags_not_written
tags_current ↔  tags_stale
scanned     ↔  not_scanned
vectors_extracted ↔  not_vectors_extracted
errored     ↔  not_errored
```

Each arrow represents the only allowed directions for that axis. Positive→negative and negative→positive are both permitted; anything else raises `ValueError`.

## Enforcing transitions: `transition_file_state()`

```
nomarr/components/library/library_file_state_comp.py
```

`transition_file_state(db, file_ids, from_state, to_state)` is the single entry point for moving files between state vertices. It:

1. Looks up `(from_state, to_state)` in a pre-built set derived from `AXIS_PAIRS`.
2. Raises `ValueError` with a descriptive message if the pair is not a valid axis transition.
3. Delegates to `db.file_states.transition()` on success.

All callers that mutate file state should go through this function rather than calling persistence directly.

## Adding a new axis

1. Add `STATE_FOO = "file_states/foo"` and `STATE_NOT_FOO = "file_states/not_foo"` constants to `file_states.py`.
2. Add both to `ALL_STATE_VERTICES`.
3. Add `"foo": (STATE_FOO, STATE_NOT_FOO)` to `AXIS_PAIRS`.
4. Extend `StateAxis` with the new literal.
5. Write a migration that inserts the two new vertices into the `file_states` collection and connects existing files to one pole (typically the negative).
6. Export both constants in `__all__`.
