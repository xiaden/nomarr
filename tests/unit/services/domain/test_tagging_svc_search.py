"""Tests for search behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto.library_dto import LibraryFileWithTags, SearchFilesResult
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig


def _make_service(*, db: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for search tests."""
    return TaggingService(
        database=db or MagicMock(),
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=MagicMock(),
        config_service=MagicMock(),
    )


class TestSearchFilesByTag:
    """Tests for ``TaggingService.search_files_by_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_count_query_for_total_and_forwards_pagination(self) -> None:
        """Search should use the dedicated count query rather than page size for total."""
        mock_db = MagicMock()
        raw_files = [{"_id": "library_files/1"}, {"_id": "library_files/2"}]
        mapped_files = [
            LibraryFileWithTags(
                _id="library_files/1",
                path="/music/one.flac",
                library_id="libraries/1",
                file_size=None,
                modified_time=None,
                duration_seconds=None,
                artist=None,
                album=None,
                title=None,
                calibration=None,
                scanned_at=None,
                last_tagged_at=None,
                tagged=1,
                tagged_version=None,
                skip_auto_tag=0,
                created_at=None,
                updated_at=None,
                tags=[],
            ),
            LibraryFileWithTags(
                _id="library_files/2",
                path="/music/two.flac",
                library_id="libraries/1",
                file_size=None,
                modified_time=None,
                duration_seconds=None,
                artist=None,
                album=None,
                title=None,
                calibration=None,
                scanned_at=None,
                last_tagged_at=None,
                tagged=1,
                tagged_version=None,
                skip_auto_tag=0,
                created_at=None,
                updated_at=None,
                tags=[],
            ),
        ]
        service = _make_service(db=mock_db)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.query.search_files_by_tag",
                return_value=raw_files,
            ) as mock_search,
            patch(
                "nomarr.services.domain.tagging_svc.query.count_files_by_tag",
                return_value=50,
            ) as mock_count,
            patch(
                "nomarr.services.domain.tagging_svc.query.map_file_with_tags_to_dto",
                side_effect=mapped_files,
            ) as mock_mapper,
        ):
            result = service.search_files_by_tag(
                tag_key="genre",
                target_value="rock",
                limit=25,
                offset=10,
            )

        assert result == SearchFilesResult(
            files=mapped_files,
            total=50,
            limit=25,
            offset=10,
        )
        mock_search.assert_called_once_with(mock_db, "genre", "rock", 25, 10)
        mock_count.assert_called_once_with(mock_db, "genre", "rock")
        assert mock_mapper.call_count == 2
        assert result.total != len(raw_files)
