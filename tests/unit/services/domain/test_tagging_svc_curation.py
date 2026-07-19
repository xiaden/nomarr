"""Tests for tag curation operations in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.domain.tagging_svc.curation import TaggingCurationMixin


def _make_service(*, db: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for curation tests."""
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


class TestTagCurationRejectNomPrefix:
    """Tests for ``TaggingCurationMixin._reject_nom_prefix``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_by_name_raises(self) -> None:
        """A name starting with 'nom:' should raise ValueError (ADR-009)."""
        with pytest.raises(ValueError, match="read-only"):
            TaggingCurationMixin._reject_nom_prefix(name="nom:genre")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_by_tag_doc_raises(self) -> None:
        """A tag_doc with a 'nom:' name should raise ValueError (ADR-009)."""
        with pytest.raises(ValueError, match="read-only"):
            TaggingCurationMixin._reject_nom_prefix(tag_doc={"name": "nom:genre", "value": "rock"})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_non_nom_passes(self) -> None:
        """A non-nom: name should not raise."""
        TaggingCurationMixin._reject_nom_prefix(name="genre")  # no exception

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reject_nom_prefix_no_args_passes(self) -> None:
        """Calling with no arguments should not raise."""
        TaggingCurationMixin._reject_nom_prefix()  # no exception


class TestGetTagOrError:
    """Tests for ``TaggingCurationMixin._get_tag_or_error``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_tag_or_error_returns_tag(self) -> None:
        """Should return the tag document when found."""
        service = _make_service()
        with patch(
            "nomarr.services.domain.tagging_svc.curation.get_tag",
            return_value={"id": 1, "name": "genre"},
        ):
            result = service._get_tag_or_error("1")

        assert result == {"id": 1, "name": "genre"}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_tag_or_error_raises_for_unknown(self) -> None:
        """Should raise ValueError when the tag is not found."""
        service = _make_service()
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.get_tag",
                return_value=None,
            ),
            pytest.raises(ValueError, match="Tag not found: 999"),
        ):
            service._get_tag_or_error("999")


class TestRenameTag:
    """Tests for ``TaggingCurationMixin.rename_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_tag_success(self) -> None:
        """Successful rename should return moved count and merged_into_existing flag."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                return_value={"name": "genre"},
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.find_or_create_tag",
                return_value=2,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value={"moved": 5, "skipped": 0, "source_orphaned": True},
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.list_songs_for_tag",
                return_value=["10", "20"],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_file_state",
            ) as mock_transition,
        ):
            result = service.rename_tag("1", "music_genre")

        assert result == RenameResult(moved=5, merged_into_existing=True)
        assert mock_transition.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rename_tag_rejects_nom_prefix(self) -> None:
        """Renaming a nom: tag should raise ValueError (ADR-009)."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                return_value={"name": "nom:genre"},
            ),
            pytest.raises(ValueError, match="read-only"),
        ):
            service.rename_tag("1", "new_value")


class TestMergeTags:
    """Tests for ``TaggingCurationMixin.merge_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_success(self) -> None:
        """Successful merge should return total_moved and sources_removed counts."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                side_effect=[
                    {"name": "genre"},  # canonical
                    {"name": "genre", "value": "rock"},  # source
                ],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value={"moved": 3, "skipped": 0, "source_orphaned": True},
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.list_songs_for_tag",
                return_value=["10"],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_file_state",
            ) as mock_transition,
        ):
            result = service.merge_tags(["2"], "1")

        assert result == MergeResult(total_moved=3, sources_removed=1)
        mock_transition.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_skips_self_reference(self) -> None:
        """Source list containing only the canonical tag ID should skip it without any merging."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                return_value={"name": "genre"},
            ) as mock_get_tag,
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
            ) as mock_relink,
            patch(
                "nomarr.services.domain.tagging_svc.curation.list_songs_for_tag",
                return_value=[],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_file_state",
            ),
        ):
            result = service.merge_tags(["1"], "1")

        # Canonical "1" is skipped entirely — no relink, no moved edges
        assert result == MergeResult(total_moved=0, sources_removed=0)
        # _get_tag_or_error called once for canonical (source "1" is skipped)
        assert mock_get_tag.call_count == 1
        mock_relink.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merge_tags_rejects_nom_prefix(self) -> None:
        """Merging into a nom: canonical tag should raise ValueError (ADR-009)."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                return_value={"name": "nom:genre"},
            ),
            pytest.raises(ValueError, match="read-only"),
        ):
            service.merge_tags(["2"], "1")


class TestSplitTag:
    """Tests for ``TaggingCurationMixin.split_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_split_tag_success(self) -> None:
        """Successful split should return moved count and new_tag_created flag."""
        service = _make_service()
        with (
            patch.object(
                service,
                "_get_tag_or_error",
                return_value={"name": "genre"},
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.find_or_create_tag",
                return_value=3,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.relink_tag_edges",
                return_value={"moved": 2, "skipped": 0, "source_orphaned": False},
            ),
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_file_state",
            ) as mock_transition,
        ):
            result = service.split_tag("1", ["10", "20"], "rock")

        assert result == SplitResult(moved=2, new_tag_created=True)
        assert mock_transition.call_count == 2


class TestUpdateFileTags:
    """Tests for ``TaggingCurationMixin.update_file_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_file_tags_success(self) -> None:
        """Successful update should return file_id, name, and tags dict."""
        service = _make_service()
        mock_tags_obj = MagicMock()
        mock_tags_obj.to_dict.return_value = {"genre": ["rock"]}
        with (
            patch(
                "nomarr.services.domain.tagging_svc.curation.set_song_tags",
            ) as mock_set,
            patch(
                "nomarr.services.domain.tagging_svc.curation.transition_file_state",
            ) as mock_transition,
            patch(
                "nomarr.services.domain.tagging_svc.curation.get_song_tags",
                return_value=mock_tags_obj,
            ),
        ):
            result = service.update_file_tags("1", "genre", ["rock"])

        assert result == {"file_id": "1", "name": "genre", "tags": {"genre": ["rock"]}}
        mock_set.assert_called_once()
        mock_transition.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_file_tags_rejects_nom_prefix(self) -> None:
        """Updating with a nom: name should raise ValueError (ADR-009)."""
        service = _make_service()
        with pytest.raises(ValueError, match="read-only"):
            service.update_file_tags("1", "nom:genre", ["rock"])
