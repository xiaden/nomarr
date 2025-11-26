"""
Navidrome integration service - facade for Navidrome utilities.

This service owns the Database dependency and provides methods for
Navidrome config/playlist generation without exposing DB to interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nomarr.helpers.dto.navidrome_dto import (
    GeneratePlaylistResult,
    GenerateTemplateFilesResult,
    GetTemplateSummaryResult,
    PreviewTagStatsResult,
)

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import PlaylistPreviewResult
    from nomarr.persistence.db import Database


@dataclass
class NavidromeConfig:
    """Configuration for NavidromeService."""

    namespace: str


class NavidromeService:
    """
    Service for Navidrome integration (config, playlists, templates).

    Wraps workflows from workflows/navidrome/* to hide DB dependency from interfaces.
    """

    def __init__(self, db: Database, cfg: NavidromeConfig) -> None:
        """
        Initialize Navidrome service.

        Args:
            db: Database instance
            cfg: Navidrome configuration
        """
        self._db = db
        self.cfg = cfg

    def preview_tag_stats(self) -> PreviewTagStatsResult:
        """Get preview of tags for Navidrome config generation."""
        from nomarr.workflows.navidrome import preview_tag_stats_workflow

        stats = preview_tag_stats_workflow(self._db, namespace=self.cfg.namespace)
        return PreviewTagStatsResult(stats=stats)

    def generate_navidrome_config(self) -> str:
        """Generate Navidrome config file content."""
        from nomarr.workflows.navidrome import generate_navidrome_config_workflow

        return generate_navidrome_config_workflow(self._db, namespace=self.cfg.namespace)

    def preview_playlist(
        self,
        query: str,
        preview_limit: int = 10,
    ) -> PlaylistPreviewResult:
        """
        Preview Smart Playlist query results.

        Args:
            query: Smart playlist query string
            preview_limit: Maximum number of tracks to return

        Returns:
            PlaylistPreviewResult with track info and query metadata
        """
        from nomarr.workflows.navidrome import preview_smart_playlist_workflow

        return preview_smart_playlist_workflow(
            db=self._db,
            query=query,
            namespace=self.cfg.namespace,
            preview_limit=preview_limit,
        )

    def generate_playlist(
        self,
        query: str,
        playlist_name: str,
        comment: str = "",
        sort: str | None = None,
        limit: int | None = None,
    ) -> GeneratePlaylistResult:
        """
        Generate Navidrome Smart Playlist (.nsp) structure.

        Args:
            query: Smart playlist query string
            playlist_name: Name for the playlist
            comment: Optional comment/description
            sort: Optional sort parameter
            limit: Optional limit on number of tracks

        Returns:
            GeneratePlaylistResult DTO with .nsp structure
        """
        from nomarr.workflows.navidrome import generate_smart_playlist_workflow

        playlist_structure = generate_smart_playlist_workflow(
            db=self._db,
            query=query,
            playlist_name=playlist_name,
            comment=comment,
            namespace=self.cfg.namespace,
            sort=sort,
            limit=limit,
        )
        return GeneratePlaylistResult(playlist_structure=playlist_structure)

    def get_template_summary(self) -> GetTemplateSummaryResult:
        """Get list of available Navidrome templates."""
        from nomarr.helpers.dto.navidrome_dto import TemplateSummaryItem
        from nomarr.helpers.navidrome_templates_helper import get_template_summary

        templates_list = get_template_summary()
        # Convert list of dicts to list of TemplateSummaryItem DTOs
        templates = [TemplateSummaryItem(**t) for t in templates_list]
        return GetTemplateSummaryResult(templates=templates)

    def generate_template_files(
        self,
        template_id: str,
        output_dir: str,
    ) -> GenerateTemplateFilesResult:
        """Generate files from a template."""
        from nomarr.helpers.navidrome_templates_helper import generate_template_files

        files_generated = generate_template_files()
        return GenerateTemplateFilesResult(files_generated=files_generated)
