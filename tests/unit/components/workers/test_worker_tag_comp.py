from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.workers.worker_tag_comp import discover_and_claim_file_for_tags
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity


def _identity() -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid="691ebf37-b1e4-5244-a9c0-4758c39eaab6"),
        normalized_path="song-123.mp3",
    )


@pytest.mark.unit
def test_discover_and_claims_next_file() -> None:
    db = MagicMock()
    with (
        patch(
            "nomarr.components.workers.worker_tag_comp.discover_next_file_needing_tags",
            return_value=SimpleNamespace(identity=_identity()),
        ) as discover,
        patch(
            "nomarr.components.workers.worker_tag_comp.claim_file",
            return_value=True,
        ) as claim,
    ):
        result = discover_and_claim_file_for_tags(db, "tag_extractor-1")

    assert result == _identity()
    discover.assert_called_once_with(db, exclude_claimed=True)
    claim.assert_called_once_with(db, _identity(), "tag_extractor-1")


@pytest.mark.unit
def test_returns_none_when_claim_is_lost() -> None:
    db = MagicMock()
    with (
        patch(
            "nomarr.components.workers.worker_tag_comp.discover_next_file_needing_tags",
            return_value=SimpleNamespace(identity=_identity()),
        ),
        patch(
            "nomarr.components.workers.worker_tag_comp.claim_file",
            return_value=False,
        ),
    ):
        result = discover_and_claim_file_for_tags(db, "tag_extractor-1")

    assert result is None
