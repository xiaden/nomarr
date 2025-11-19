"""
Navidrome integration service - facade for Navidrome utilities.

This service owns the Database dependency and provides methods for
Navidrome config/playlist generation without exposing DB to interfaces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class NavidromeService:
    """
    Service for Navidrome integration (config, playlists, templates).

    Wraps utility functions from services/navidrome/* to hide DB dependency.
    """

    def __init__(self, db: Database, namespace: str) -> None:
        """
        Initialize Navidrome service.

        Args:
            db: Database instance
            namespace: Tag namespace (e.g., "nom")
        """
        self._db = db
        self._namespace = namespace

    def preview_tag_stats(self) -> dict[str, dict[str, Any]]:
        """Get preview of tags for Navidrome config generation."""
        from nomarr.services.navidrome.config_generator import preview_tag_stats

        return preview_tag_stats(self._db, namespace=self._namespace)

    def generate_navidrome_config(self, format: str = "toml") -> str:
        """Generate Navidrome config file content."""
        from nomarr.services.navidrome.config_generator import generate_navidrome_config

        return generate_navidrome_config(self._db, namespace=self._namespace, format=format)

    def preview_playlist(
        self,
        name: str,
        rules: str,
        max_tracks: int = 50,
    ) -> dict[str, Any]:
        """Preview playlist query results."""
        from nomarr.services.navidrome.playlist_generator import (
            preview_playlist_query,
        )

        return preview_playlist_query(
            db=self._db,
            query_rules=rules,
            name=name,
            max_tracks=max_tracks,
            namespace=self._namespace,
        )

    def generate_playlists(
        self,
        playlist_configs: list[dict[str, Any]],
        output_dir: str,
        format: str = "m3u",
    ) -> dict[str, Any]:
        """Generate playlist files from configs."""
        from nomarr.services.navidrome.playlist_generator import generate_playlists

        return generate_playlists(
            db=self._db,
            playlist_configs=playlist_configs,
            output_dir=output_dir,
            format=format,
            namespace=self._namespace,
        )

    def get_template_summary(self) -> list[dict[str, Any]]:
        """Get list of available Navidrome templates."""
        from nomarr.services.navidrome.templates import get_template_summary

        return get_template_summary()

    def generate_template_files(
        self,
        template_id: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Generate files from a template."""
        from nomarr.services.navidrome.templates import generate_template_files

        return generate_template_files(
            db=self._db,
            template_id=template_id,
            output_dir=output_dir,
            namespace=self._namespace,
        )
