from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.workers.worker_tag_comp import discover_and_claim_file_for_tags


@pytest.mark.unit
def test_discover_and_claims_next_file() -> None:
    db = MagicMock()
    with (
        patch(
            "nomarr.components.workers.worker_tag_comp.discover_next_file_needing_tags",
            return_value={"id": 123},
        ) as discover,
        patch(
            "nomarr.components.workers.worker_tag_comp.claim_file",
            return_value=True,
        ) as claim,
    ):
        result = discover_and_claim_file_for_tags(db, "tag_extractor-1")

    assert result == "123"
    discover.assert_called_once_with(db, exclude_claimed=True)
    claim.assert_called_once_with(db, "123", "tag_extractor-1")


@pytest.mark.unit
def test_returns_none_when_claim_is_lost() -> None:
    db = MagicMock()
    with (
        patch(
            "nomarr.components.workers.worker_tag_comp.discover_next_file_needing_tags",
            return_value={"id": 123},
        ),
        patch(
            "nomarr.components.workers.worker_tag_comp.claim_file",
            return_value=False,
        ),
    ):
        result = discover_and_claim_file_for_tags(db, "tag_extractor-1")

    assert result is None
