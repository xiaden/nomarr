"""
Navidrome integration service - facade for Navidrome utilities.

This service owns the Database dependency and provides methods for
Navidrome config/playlist generation without exposing DB to interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

    def preview_tag_stats(self) -> dict[str, dict[str, Any]]:
        """Get preview of tags for Navidrome config generation."""
        from nomarr.workflows.navidrome import preview_tag_stats_workflow

        return preview_tag_stats_workflow(self._db, namespace=self.cfg.namespace)

    def generate_navidrome_config(self) -> str:
        """Generate Navidrome config file content."""
        from nomarr.workflows.navidrome import generate_navidrome_config_workflow

        return generate_navidrome_config_workflow(self._db, namespace=self.cfg.namespace)

    def preview_playlist(
        self,
        name: str,
        rules: str,
        max_tracks: int = 50,
    ) -> dict[str, Any]:
        """Preview playlist query results."""
        from nomarr.workflows.navidrome import preview_smart_playlist_workflow

        return preview_smart_playlist_workflow(
            db=self._db,
            query=rules,
            namespace=self.cfg.namespace,
            preview_limit=max_tracks,
        )

    def get_template_summary(self) -> list[dict[str, Any]]:
        """Get list of available Navidrome templates."""
        from nomarr.helpers.navidrome_templates import get_template_summary

        return get_template_summary()

    def generate_template_files(
        self,
        template_id: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Generate files from a template."""
        from nomarr.helpers.navidrome_templates import generate_template_files

        return generate_template_files()
