"""Test G — frozen semantic-head ruler labels (Plan A Phase 3, P3-S1..P3-S5).

Proves that the HEAD ruler label is the song's ACTUAL FROZEN ACTIVATION-DERIVED semantic
tuple (never the head suite's names/IDs), that identical head suites with different frozen
activations resolve different labels, that missing head evidence excludes only the HEAD ruler
(artist/genre stay evaluable), that the head-suite identity is persisted SEPARATELY from the
semantic label, and that ``"unknown"`` is never fabricated.  A physically present non-finite
stored activation fails closed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    _geometry_ruler_metrics,
)
from scripts.embedding_research.common.head_ruler_labels import (
    HeadSongLabel,
    resolve_head_ruler_labels,
)
from scripts.embedding_research.common.threshold_analysis import AllThresholdAnalysis
from scripts.embedding_research.db import (
    ensure_schema,
    read_head_label_provenance,
    write_head_label_provenance_in_transaction,
)
from scripts.embedding_research.db.geometry import GeometryIdentity, IntegrityRefused
from scripts.embedding_research.streams.records import HeadSuiteCurrentError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_RUN = "run-head-labels"
_EVAL = "evaluation-head-labels"


def _identity(song_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        stream_ref=f"stream-{song_id}",
        stream_digest=f"stream-digest-{song_id}",
        mask_ref=f"mask-{song_id}",
        mask_digest=f"mask-digest-{song_id}",
    )


class _Store:
    def __init__(self, masks: dict[str, np.ndarray]) -> None:
        self._masks = masks
        self.loads: list[str] = []

    def load_committed_observation(self, song_id: str, _backbone: str) -> SimpleNamespace:
        self.loads.append(song_id)
        return SimpleNamespace(identity=_identity(song_id), mask=self._masks[song_id])


def _selection(_song_id: str, ref: str, *, fingerprint: str = "suite-shared") -> SimpleNamespace:
    return SimpleNamespace(
        record=SimpleNamespace(artifact_ref=ref, head_ids="gender,timbre", dim_by_head="gender:2,timbre:2"),
        marker=SimpleNamespace(head_set_fingerprint=fingerprint),
    )


def _write_npz(root: Path, ref: str, rows_by_head: dict[str, list[list[float]]]) -> None:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **{head: np.asarray(rows, dtype=np.float32) for head, rows in rows_by_head.items()})


def _patch_suite(monkeypatch, selections: dict[str, SimpleNamespace]) -> None:
    def _resolve(_root, song_id, _backbone):  # type: ignore[no-untyped-def]
        if song_id not in selections:
            raise HeadSuiteCurrentError(f"no current head-suite marker for {song_id!r}")
        return selections[song_id]

    monkeypatch.setattr(
        "scripts.embedding_research.common.head_ruler_labels.resolve_current_head_suite",
        _resolve,
    )


def test_frozen_activations_not_suite_names_drive_the_head_label(tmp_path, monkeypatch) -> None:
    root = tmp_path
    _write_npz(
        root,
        "act-a.npz",
        {"gender": [[0.9, 0.1]] * 3, "timbre": [[0.9, 0.9]] * 3},
    )
    _write_npz(
        root,
        "act-b.npz",
        {"gender": [[0.1, 0.9]] * 3, "timbre": [[0.1, 0.1]] * 3},
    )
    _patch_suite(
        monkeypatch,
        {"song-a": _selection("song-a", "act-a.npz"), "song-b": _selection("song-b", "act-b.npz")},
    )
    store = _Store(
        {
            "song-a": np.asarray([1, 1, 0], dtype=np.uint8),
            "song-b": np.asarray([1, 1, 0], dtype=np.uint8),
        }
    )
    head_store = SimpleNamespace(output_root=root)

    label_a = resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="song-a", backbone="effnet")
    label_b = resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="song-b", backbone="effnet")

    assert label_a is not None and label_b is not None
    # Identical suite names/IDs AND identical fingerprint...
    assert label_a.head_set_fingerprint == label_b.head_set_fingerprint == "suite-shared"
    assert label_a.head_ids == label_b.head_ids == "gender,timbre"
    # ...but DIFFERENT frozen activations resolve DIFFERENT semantic ruler labels.
    assert label_a.full_tuple != label_b.full_tuple
    assert label_a.full_tuple == (("gender", 0), ("timbre", 1))
    assert label_a.labels == ("female", "dark")
    assert label_b.full_tuple == (("gender", 1), ("timbre", 0))
    assert label_b.labels == ("male", "bright")
    assert label_a.searchable_rows == 2
    assert "unknown" not in label_a.labels + label_b.labels


def test_missing_evidence_yields_no_label_and_non_finite_fails_closed(tmp_path, monkeypatch) -> None:
    root = tmp_path
    _write_npz(
        root,
        "act-nan.npz",
        {"gender": [[0.5, 0.5], [float("nan"), 0.5], [0.5, 0.5]], "timbre": [[0.5, 0.5]] * 3},
    )
    _write_npz(root, "act-dim3.npz", {"gender": [[0.1, 0.2, 0.3]] * 3, "timbre": [[0.5, 0.5]] * 3})
    _patch_suite(
        monkeypatch,
        {
            "nan-song": _selection("nan-song", "act-nan.npz"),
            "dim3-song": _selection("dim3-song", "act-dim3.npz"),
            # A suite IS present for zero-mask; the committed mask has no searchable rows.
            "zero-mask": _selection("zero-mask", "act-dim3.npz"),
        },
    )
    store = _Store(
        {
            "nan-song": np.asarray([1, 1, 0], dtype=np.uint8),
            "dim3-song": np.asarray([1, 1, 0], dtype=np.uint8),
            "zero-mask": np.zeros(3, dtype=np.uint8),
            "no-marker": np.asarray([1, 1, 0], dtype=np.uint8),
        }
    )
    head_store = SimpleNamespace(output_root=root)

    # Absent marker, absent searchable mass, and a non-binary head dimension are all missing
    # evidence -> NO label (a per-song HEAD ruler exclusion, never "unknown").
    assert (
        resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="no-marker", backbone="effnet")
        is None
    )
    assert (
        resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="zero-mask", backbone="effnet")
        is None
    )
    assert (
        resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="dim3-song", backbone="effnet")
        is None
    )
    # A physically PRESENT stored non-finite activation is corruption and fails closed.
    with pytest.raises(IntegrityRefused):
        resolve_head_ruler_labels(head_store=head_store, stream_store=store, song_id="nan-song", backbone="effnet")


def _song_request(song_id: str, head_label: object | None) -> GeometrySongRequest:
    return GeometrySongRequest(
        song_id=song_id,
        backbone="effnet",
        geometry_identity=GeometryIdentity(song_id, "effnet", "commit-a", "geometry-v1", "profile-a"),
        observation_evidence={"observation_group_sha256": f"observation-{song_id}"},
        artist="artist-a",
        genre="genre-a",
        head_label=head_label,
        head_suite_identity="suite-shared" if head_label is not None else None,
    )


def _song_analysis(request: GeometrySongRequest) -> GeometrySongAnalysis:
    thresholds = AllThresholdAnalysis(
        experiment="temporal_global",
        geometry_id=f"geometry-{request.song_id}",
        observation_group_sha256=f"observation-{request.song_id}",
        profile_digest="profile-a",
        mask_digest="mask-a",
        results=(),
        geometry_semantics_version="geometry-v1",
        evaluation_id=_EVAL,
        execution_id="execution-a",
    )
    scores = GeometryScoreBundle(
        scores={f"representation-{request.song_id}": 0.5},
        baseline_score=0.1,
        evaluation_comparable=True,
    )
    return GeometrySongAnalysis(request, thresholds, GeometryRepresentationRoster(()), scores)


def test_missing_head_evidence_excludes_only_the_head_ruler() -> None:
    request_a = _song_request("song-a", (("gender", 0), ("timbre", 1)))
    request_b = _song_request("song-b", (("gender", 1), ("timbre", 0)))
    request_c = _song_request("song-c", None)
    analyses = (_song_analysis(request_a), _song_analysis(request_b), _song_analysis(request_c))

    artist_metrics, genre_metrics, head_metrics, per_song, _deltas = _geometry_ruler_metrics(analyses)

    # song-c has NO head evidence but keeps its artist/genre labels: those rulers stay
    # defined/eligible for it and never lose the member.
    assert artist_metrics["n_songs"] == 3.0
    assert artist_metrics["missing_count"] == 0.0
    assert genre_metrics["n_songs"] == 3.0
    assert genre_metrics["missing_count"] == 0.0
    # Only song-c is excluded from the HEAD ruler; no "unknown" bucket is fabricated.
    assert head_metrics["n_songs"] == 2.0
    assert head_metrics["missing_count"] == 1.0
    assert per_song["song-c"]["eligible_artist"] == 1.0
    assert per_song["song-c"]["eligible_genre"] == 1.0
    assert per_song["song-c"]["eligible_head"] == 0.0


def test_suite_identity_is_persisted_separately_from_the_ruler_label() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    label = HeadSongLabel(
        song_id="song-a",
        backbone="effnet",
        full_tuple=(("gender", 0), ("timbre", 1)),
        labels=("female", "dark"),
        pooled=(0.2, 0.9),
        searchable_rows=2,
        head_set_fingerprint="suite-shared",
        head_ids="gender,timbre",
        dim_by_head="gender:2,timbre:2",
        stream_ref="stream-a",
        stream_digest="stream-digest-a",
        mask_ref="mask-a",
        mask_digest="mask-digest-a",
        present=True,
    )
    write_head_label_provenance_in_transaction(
        con,
        run_id=_RUN,
        evaluation_id=_EVAL,
        rows=(label, SimpleNamespace(song_id="song-c", backbone="effnet", present=False)),
    )
    rows = read_head_label_provenance(con, run_id=_RUN)
    con.close()

    by_song = {row["song_id"]: row for row in rows}
    present = by_song["song-a"]
    # The activation-derived ruler label and the head-suite identity are SEPARATE fields...
    assert present["semantic_label"] == (("gender", 0), ("timbre", 1))
    assert present["labels"] == ("female", "dark")
    assert present["pooled"] == (0.2, 0.9)
    assert present["head_set_fingerprint"] == "suite-shared"
    assert present["head_ids"] == "gender,timbre"
    # ...and the suite fingerprint is NEVER used as the ruler label.
    assert present["semantic_label"] != present["head_set_fingerprint"]
    # A missing-head song persists present=False and is excluded, never labelled "unknown".
    missing = by_song["song-c"]
    assert missing["present"] is False
    assert missing["semantic_label"] is None
    assert missing["labels"] == ()
    assert "unknown" not in repr(rows)
