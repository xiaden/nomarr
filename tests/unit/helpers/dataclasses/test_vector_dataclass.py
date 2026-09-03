"""Unit tests for the caller-facing vector domain value objects.

``TASK-vector-read-contract-correction-A-typed-domain-callers`` Phase 1
(P1-S2): prove the frozen/slotted ``SongVector``, ``VectorMatch``, and
``EmbeddingCounts`` domain values carry only application vector-read semantics,
reuse the existing ``SongIdentity`` composition, preserve tuple vector values
and order, and expose no persistence row fields or factories.  See
``nomarr/helpers/dataclasses/vector_dataclass.py``.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import EmbeddingCounts, SongVector, VectorMatch

PERSISTENCE_FIELDS = (
    "id",
    "_id",
    "_key",
    "song_id",
    "backbone_id",
    "tier",
    "embed_dim",
    "created_at",
    "updated_at",
    "distance",
)
FACTORIES = ("from_db_doc", "from_row", "from_record", "to_dict")

_LIBRARY = LibraryIdentity(name="music")
_SONG = SongIdentity(library=_LIBRARY, normalized_path="/music/a.mp3")


def _song_vector(**kwargs: object) -> SongVector:
    base: dict[str, object] = {
        "song": _SONG,
        "backbone": "effnet",
        "vector": (0.1, 0.2, 0.3),
        "model_suite_hash": "suite",
        "num_segments": 3,
        "segmentation_hash": None,
        "genres": None,
    }
    base.update(kwargs)
    return SongVector(**base)  # type: ignore[arg-type]


def _match(**kwargs: object) -> VectorMatch:
    base: dict[str, object] = {"song": _SONG, "backbone": "effnet", "score": 0.85}
    base.update(kwargs)
    return VectorMatch(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestVectorDomainIsFrozenAndSlotted:
    def test_song_vector_is_frozen_and_slotted(self) -> None:
        vector = _song_vector()
        with pytest.raises(AttributeError):
            vector.backbone = "other"  # type: ignore[misc]
        assert not hasattr(vector, "__dict__")

    def test_vector_match_is_frozen_and_slotted(self) -> None:
        match = _match()
        with pytest.raises(AttributeError):
            match.score = 0.5  # type: ignore[misc]
        assert not hasattr(match, "__dict__")

    def test_embedding_counts_is_frozen_and_slotted(self) -> None:
        counts = EmbeddingCounts(hot_count=3, cold_count=5)
        with pytest.raises(AttributeError):
            counts.hot_count = 1  # type: ignore[misc]
        assert not hasattr(counts, "__dict__")

    def test_equality_by_value(self) -> None:
        assert _song_vector() == _song_vector()
        assert _match() == _match()
        assert _song_vector() != _song_vector(backbone="yamnet")
        assert _match() != _match(score=0.5)
        assert EmbeddingCounts(3, 5) == EmbeddingCounts(hot_count=3, cold_count=5)
        assert EmbeddingCounts(3, 5) != EmbeddingCounts(3, 6)


@pytest.mark.unit
class TestFieldTypes:
    def test_song_vector_field_types(self) -> None:
        vector = _song_vector(vector=(0.5, -0.5), model_suite_hash="h", num_segments=2, genres=("a", "b"))
        assert isinstance(vector.song, SongIdentity)
        assert isinstance(vector.backbone, str)
        assert isinstance(vector.vector, tuple)
        assert isinstance(vector.model_suite_hash, str)
        assert isinstance(vector.num_segments, int)
        assert vector.segmentation_hash is None or isinstance(vector.segmentation_hash, str)
        assert vector.genres is None or isinstance(vector.genres, tuple)

    def test_vector_match_field_types(self) -> None:
        match = _match(score=0.9, vector=(1.0, 2.0))
        assert isinstance(match.song, SongIdentity)
        assert isinstance(match.backbone, str)
        assert isinstance(match.score, float)
        assert match.vector is None or isinstance(match.vector, tuple)

    def test_embedding_counts_field_types(self) -> None:
        counts = EmbeddingCounts(hot_count=1, cold_count=2)
        assert isinstance(counts.hot_count, int)
        assert isinstance(counts.cold_count, int)


@pytest.mark.unit
class TestTupleVectorPreservation:
    def test_song_vector_preserves_values_and_order(self) -> None:
        stored = (0.1, -0.2, 0.3, 0.4)
        vector = _song_vector(vector=stored)
        assert vector.vector == stored
        assert vector.vector == (0.1, -0.2, 0.3, 0.4)
        assert list(vector.vector) == [0.1, -0.2, 0.3, 0.4]

    def test_vector_match_optional_vector_preserves_order(self) -> None:
        stored = (0.9, 0.8, 0.7)
        match = _match(vector=stored)
        assert match.vector == stored

    def test_song_vector_vector_is_immutable_tuple(self) -> None:
        # tuple fields are immutable by construction — the value object never
        # mutates or reorders the stored vector.
        vector = _song_vector()
        with pytest.raises(AttributeError):
            vector.vector = (1.0,)  # type: ignore[misc]
        assert vector.vector == (0.1, 0.2, 0.3)


@pytest.mark.unit
class TestOptionalMetadata:
    def test_none_versus_set_metadata_are_distinct(self) -> None:
        bare = _song_vector(model_suite_hash=None, num_segments=None, segmentation_hash=None, genres=None)
        set_vals = _song_vector(
            model_suite_hash="suite",
            num_segments=4,
            segmentation_hash="seg",
            genres=("rock", "pop"),
        )
        assert (bare.model_suite_hash, bare.num_segments, bare.segmentation_hash, bare.genres) == (
            None,
            None,
            None,
            None,
        )
        assert (set_vals.model_suite_hash, set_vals.num_segments, set_vals.segmentation_hash, set_vals.genres) == (
            "suite",
            4,
            "seg",
            ("rock", "pop"),
        )
        # None genres stays distinct from an explicitly-provided empty tuple.
        assert _song_vector(genres=None).genres is None
        assert _song_vector(genres=()).genres == ()

    def test_vector_match_vector_defaults_to_none(self) -> None:
        assert _match().vector is None
        assert _match(vector=None).vector is None
        assert _match(vector=(1.0,)).vector == (1.0,)


@pytest.mark.unit
class TestScoreSemantics:
    def test_score_accepts_in_range_values(self) -> None:
        for score in (-1.0, -0.5, 0.0, 0.85, 1.0):
            assert _match(score=score).score == score

    def test_score_is_float_and_semantic_range_is_minus_one_to_one(self) -> None:
        # Range enforcement is by contract (persistence applies the
        # clamp(1 - distance, -1, 1) formula); the value object stores a float.
        match = _match(score=1.0)
        assert isinstance(match.score, float)
        # The dataclass carries the value verbatim; it does not reject an
        # out-of-range score here (no invented range validation).
        assert _match(score=5.0).score == 5.0

    def test_embedding_counts_carry_counts(self) -> None:
        assert EmbeddingCounts(hot_count=7, cold_count=0).hot_count == 7
        assert EmbeddingCounts(hot_count=0, cold_count=3).cold_count == 3


@pytest.mark.unit
class TestIdentityComposition:
    def test_song_vector_song_is_a_song_identity(self) -> None:
        vector = _song_vector()
        assert isinstance(vector.song, SongIdentity)
        assert vector.song == _SONG
        assert vector.song.library.name == "music"
        assert vector.song.normalized_path == "/music/a.mp3"

    def test_vector_match_song_is_a_song_identity(self) -> None:
        match = _match()
        assert isinstance(match.song, SongIdentity)
        assert match.song == _SONG

    def test_rejects_non_song_identity_composition(self) -> None:
        with pytest.raises(TypeError):
            _song_vector(song=_LIBRARY)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _match(song=_LIBRARY)  # type: ignore[arg-type]

    def test_rejects_blank_backbone(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _song_vector(backbone=value)
            with pytest.raises(ValueError):
                _match(backbone=value)


@pytest.mark.unit
class TestNoPersistenceLeakage:
    def test_no_persistence_owned_fields(self) -> None:
        for value in (_song_vector(), _match(), EmbeddingCounts(1, 2)):
            for attr in PERSISTENCE_FIELDS:
                assert not hasattr(value, attr), f"vector domain value must not expose {attr!r}"

    def test_no_db_row_factories_or_projections(self) -> None:
        for cls in (SongVector, VectorMatch, EmbeddingCounts):
            for name in FACTORIES:
                assert not hasattr(cls, name), f"{cls.__name__} must not expose {name!r}"
