"""Signature guard for ``MlInferenceRepo.replace_song_inference_results``.

P1-S2 of ``TASK-ml-write-boundary-leaks-storage-representation-A-typed-inference-
write-boundary``. The typed Phase-2 repository signature IS in force and is pinned
here without a database: ``TestTypedAggregateSignature`` is the permanent unit-level
guard holding the repository to the typed contract — a semantic ``SongIdentity``
*song* (never an integer key) plus keyword-only typed
``Sequence[BackboneVectorWrite]`` / ``Sequence[OutputStreamWrite]`` command
sequences, with identity resolution internal to the repository.

The behavioral backbone-scope and atomic-rollback coverage of the legacy (removed)
``TestMlInferenceRepo`` class is superseded by
``tests/characterization/test_ml_write_typed_aggregate.py`` on real PostgreSQL and
by the unit scope/rollback tests in ``test_ml_inference_repo_scope.py``. No DB is
required for the signature pin.
"""

from __future__ import annotations

import pytest

from nomarr.persistence.database.ml_inference_repo import MlInferenceRepo

# ---------------------------------------------------------------------------
# P1-S2 permanent typed repository aggregate signature
# (TASK-ml-write-boundary-leaks-storage-representation-A). Phase 2 landed: the
# repository accepts a semantic SongIdentity (never an integer song key) and
# keyword-only typed Sequence[BackboneVectorWrite]/Sequence[OutputStreamWrite]
# command sequences (resolving the song FK internally). No DB is required to pin
# the signature — TestTypedAggregateSignature is the permanent no-DB signature
# guard.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTypedAggregateSignature:
    def test_repository_accepts_song_identity_not_integer_key(self) -> None:
        import inspect

        sig = inspect.signature(MlInferenceRepo.replace_song_inference_results)
        params = list(sig.parameters)
        assert "song" in params, f"expected a semantic `song` param, got {params}"
        assert "song_id" not in params, "repository must not accept an integer song key"

    def test_repository_vectors_are_keyword_only_typed_sequence(self) -> None:
        import inspect

        sig = inspect.signature(MlInferenceRepo.replace_song_inference_results)
        vectors = sig.parameters["vectors"]
        assert vectors.kind is inspect.Parameter.KEYWORD_ONLY
        # The annotation references the typed write command (Phase-2 signature in force).
        annotation = vectors.annotation
        text = getattr(annotation, "__name__", str(annotation))
        assert "BackboneVectorWrite" in text, f"vectors must be typed commands, got {text!r}"
        assert "dict" not in text.lower(), "vectors must not be raw row dictionaries"

    def test_repository_output_streams_are_typed_sequence(self) -> None:
        import inspect

        sig = inspect.signature(MlInferenceRepo.replace_song_inference_results)
        streams = sig.parameters["output_streams"]
        assert streams.kind is inspect.Parameter.KEYWORD_ONLY
        text = getattr(streams.annotation, "__name__", str(streams.annotation))
        assert "OutputStreamWrite" in text, f"output_streams must be typed commands, got {text!r}"
