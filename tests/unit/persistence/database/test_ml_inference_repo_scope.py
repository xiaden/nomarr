"""Unit tests for the vector backbone scope invariant."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.ml_inference_repo import MlInferenceRepo

pytestmark = pytest.mark.unit


def _repo() -> tuple[MlInferenceRepo, MagicMock]:
    """Build an inference repository with a session that records SQL calls."""
    session = MagicMock()
    session.begin_nested.return_value.__enter__.return_value = session
    return MlInferenceRepo(session), session


@pytest.mark.parametrize("declared_backbone", ["effnet", None])
def test_vector_payload_uses_aggregate_backbone_scope(declared_backbone: str | None) -> None:
    """Matching and omitted declarations both persist the aggregate backbone."""
    repo, session = _repo()
    payload = {"model_id": "model-1", "embedding_vector": [0.1, 0.2]}
    if declared_backbone is not None:
        payload["backbone_id"] = declared_backbone

    repo.replace_song_inference_results(
        song_id=1,
        backbone="effnet",
        vectors=[payload],
        output_streams=[],
    )

    statement = session.execute.call_args_list[-1].args[0]
    assert statement.compile().params["backbone_id"] == "effnet"
    session.commit.assert_called_once_with()


def test_mismatched_vector_backbone_fails_before_replacement_mutation() -> None:
    """A contradictory declaration is rejected before deletes or inserts begin."""
    repo, session = _repo()

    with pytest.raises(ValueError, match=r"backbone_id.*aggregate backbone"):
        repo.replace_song_inference_results(
            song_id=1,
            backbone="effnet",
            vectors=[
                {
                    "model_id": "model-1",
                    "embedding_vector": [0.1, 0.2],
                    "backbone_id": "musicnn",
                }
            ],
            output_streams=[{"output_id": "stream-1", "values": [0.9]}],
        )

    session.begin_nested.assert_not_called()
    session.execute.assert_not_called()
    session.commit.assert_not_called()
