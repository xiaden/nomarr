"""Navidrome integration service - facade for Navidrome utilities.

This service owns the Database dependency and provides methods for
Navidrome config/playlist generation without exposing DB to interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nomarr.components.navidrome.templates_comp import generate_template_files, get_template_summary
from nomarr.helpers.dto.navidrome_dto import (
    GeneratePlaylistResult,
    GenerateTemplateFilesResult,
    GetTemplateSummaryResult,
    PreviewTagStatsResult,
    StaticPlaylistResult,
    TemplateSummaryItem,
)
from nomarr.workflows.navidrome import (
    execute_smart_playlist_filter,
    generate_navidrome_config_workflow,
    generate_smart_playlist_workflow,
    generate_static_playlist_workflow,
    parse_smart_playlist_query,
    preview_smart_playlist_workflow,
    preview_tag_stats_workflow,
)
from nomarr.workflows.navidrome.push_playlist_wf import push_playlist

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
    from nomarr.helpers.dto.navidrome_dto import PlaylistPreviewResult
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService
    from nomarr.workflows.navidrome.find_similar_tracks_wf import SimilarTrackResult
    from nomarr.workflows.navidrome.sync_song_map_wf import SyncResult


@dataclass
class NavidromeConfig:
    """Configuration for NavidromeService."""

    namespace: str


class NavidromeService:
    """Service for Navidrome integration (config, playlists, templates).

    Wraps workflows from workflows/navidrome/* to hide DB dependency from interfaces.
    API credentials are read live from ConfigService so changes via the web UI
    take effect without restarting the application.
    """

    def __init__(self, db: Database, cfg: NavidromeConfig, config_service: ConfigService) -> None:
        """Initialize Navidrome service.

        Args:
            db: Database instance
            cfg: Navidrome configuration (static settings)
            config_service: Live configuration provider (for API credentials)

        """
        self._db = db
        self.cfg = cfg
        self._config_service = config_service
        self._client: SubsonicClient | None = None
        # Track credentials used for the cached client so we can invalidate
        # when the user changes them via the web UI.
        self._client_creds: tuple[str, str, str] | None = None

    def preview_tag_stats(self) -> PreviewTagStatsResult:
        """Get preview of tags for Navidrome config generation."""
        stats = preview_tag_stats_workflow(self._db, namespace=self.cfg.namespace)
        return PreviewTagStatsResult(stats=stats)

    def get_tag_values(self, rel: str) -> list[str]:
        """Get distinct values for a specific tag relationship.

        Args:
            rel: Tag relationship key (e.g., 'artist', 'nom:mood-strict')

        Returns:
            Sorted list of distinct tag values as strings

        """
        from nomarr.components.navidrome.tag_query_comp import get_tag_value_counts

        value_counts = get_tag_value_counts(self._db, rel)
        return sorted(str(v) for v in value_counts)

    def generate_navidrome_config(self) -> str:
        """Generate Navidrome config file content."""
        return generate_navidrome_config_workflow(self._db, namespace=self.cfg.namespace)

    def preview_playlist(
        self,
        query: str,
        preview_limit: int = 10,
    ) -> PlaylistPreviewResult:
        """Preview Smart Playlist query results.

        Args:
            query: Smart playlist query string
            preview_limit: Maximum number of tracks to return

        Returns:
            PlaylistPreviewResult with track info and query metadata

        """
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
        """Generate Navidrome Smart Playlist (.nsp) structure.

        Args:
            query: Smart playlist query string
            playlist_name: Name for the playlist
            comment: Optional comment/description
            sort: Optional sort parameter
            limit: Optional limit on number of tracks

        Returns:
            GeneratePlaylistResult DTO with .nsp structure

        """
        playlist_structure = generate_smart_playlist_workflow(
            db=self._db,
            query=query,
            playlist_name=playlist_name,
            comment=comment,
            namespace=self.cfg.namespace,
            sort=sort,
            limit=limit,
        )
        result = GeneratePlaylistResult(playlist_structure=playlist_structure)

        # Optionally push an evaluated snapshot to Navidrome via Subsonic API.
        try:
            client = self._get_client()
        except ValueError:
            pass
        else:
            try:
                playlist_filter = parse_smart_playlist_query(query, namespace=self.cfg.namespace)
                matching_ids = execute_smart_playlist_filter(self._db, playlist_filter)
                file_ids = list(matching_ids)
                if limit is not None:
                    file_ids = file_ids[:limit]
                push_playlist(
                    db=self._db,
                    client=client,
                    playlist_name=playlist_name,
                    file_ids=file_ids,
                )
            except Exception:
                logger.exception("Failed to push smart playlist '%s' to Navidrome", playlist_name)

        return result

    def get_template_summary(self) -> GetTemplateSummaryResult:
        """Get list of available Navidrome templates."""
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
        files_generated = generate_template_files()
        return GenerateTemplateFilesResult(files_generated=files_generated)

    def generate_static_playlist(
        self,
        file_ids: list[str],
        playlist_name: str = "Vector Search Playlist",
    ) -> StaticPlaylistResult:
        """Generate a static M3U playlist from file IDs.

        Used by vector search to export results as a Navidrome-importable
        M3U playlist of specific tracks (not a rule-based smart playlist).

        Args:
            file_ids: List of library file document IDs (max 200)
            playlist_name: Name for the playlist header

        Returns:
            StaticPlaylistResult with M3U content, track count, and missing IDs

        """
        result = generate_static_playlist_workflow(
            db=self._db,
            file_ids=file_ids,
            playlist_name=playlist_name,
        )

        # Optionally push to Navidrome via Subsonic API.
        try:
            client = self._get_client()
        except ValueError:
            pass
        else:
            try:
                push_playlist(
                    db=self._db,
                    client=client,
                    playlist_name=playlist_name,
                    file_ids=file_ids,
                )
            except Exception:
                logger.exception("Failed to push static playlist '%s' to Navidrome", playlist_name)

        return result


    # ------------------------------------------------------------------
    # API credentials (live from ConfigService)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_path_prefix_map(raw: str | None) -> list[tuple[str, str]]:
        """Parse comma-separated 'from:to' prefix pairs.

        Format: 'navidrome_prefix:nomarr_prefix,navidrome_prefix2:nomarr_prefix2'
        Example: '/music:/media/library,/podcasts:/media/pods'

        Returns:
            List of (navidrome_prefix, nomarr_prefix) tuples.
        """
        if not raw or not raw.strip():
            return []
        pairs: list[tuple[str, str]] = []
        for entry in raw.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            parts = entry.split(":", 1)
            pairs.append((parts[0].strip(), parts[1].strip()))
        return pairs

    def _get_api_credentials(self) -> tuple[str | None, str | None, str | None]:
        """Read Navidrome API credentials live from ConfigService.

        Returns:
            Tuple of (api_url, api_user, api_password) — any may be None.
        """
        api_url = self._config_service.get("navidrome_api_url")
        api_user = self._config_service.get("navidrome_api_user")
        api_password = self._config_service.get("navidrome_api_password")
        return api_url, api_user, api_password

    # ------------------------------------------------------------------
    # Subsonic client (lazy, invalidated on credential change)
    # ------------------------------------------------------------------

    def _get_client(self) -> SubsonicClient:
        """Get or create the Subsonic API client.

        Reads credentials live from ConfigService.  If the credentials have
        changed since the last client was created, the cached client is
        discarded and rebuilt.

        Raises:
            ValueError: If Navidrome API credentials are not configured.
        """
        api_url, api_user, api_password = self._get_api_credentials()

        if not api_url or not api_user or not api_password:
            msg = "Navidrome API credentials not configured (api_url, api_user, api_password)"
            raise ValueError(msg)

        current_creds = (api_url, api_user, api_password)

        # Invalidate cached client if credentials changed
        if self._client is not None and self._client_creds == current_creds:
            return self._client

        from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient

        self._client = SubsonicClient(
            base_url=api_url,
            user=api_user,
            password=api_password,
        )
        self._client_creds = current_creds
        return self._client

    # ------------------------------------------------------------------
    # Rescan trigger
    # ------------------------------------------------------------------

    def trigger_rescan(self, full_scan: bool = False) -> bool:
        """Trigger a Navidrome library rescan if API is configured.

        Args:
            full_scan: If True, performs a full rescan instead of incremental.

        Returns:
            True if scan was triggered, False if not configured or on error.

        """
        try:
            client = self._get_client()
        except ValueError:
            return False
        try:
            client.start_scan(full_scan=full_scan)
            scan_type = "full" if full_scan else "incremental"
            logger.info("Triggered %s Navidrome library rescan", scan_type)
            return True
        except Exception:
            logger.exception("Failed to trigger Navidrome library rescan")
            return False

    def ping(self) -> tuple[bool, str]:
        """Test connectivity to the Navidrome server.

        Reads credentials live from ConfigService and constructs a fresh
        SubsonicClient.  Returns (ok, error_message).
        """
        try:
            client = self._get_client()
            client.ping()
            return True, ""
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # Song map sync
    # ------------------------------------------------------------------

    def sync_song_map(self) -> SyncResult:
        """Sync Navidrome's song inventory to the navidrome_song_map collection.

        Walks Navidrome's album inventory via the Subsonic API, matches file
        paths to Nomarr library_files, and upserts the bidirectional ID mapping.

        Returns:
            SyncResult with total_songs, resolved, unresolved, duration_ms.

        Raises:
            ValueError: If Navidrome API credentials are not configured.
        """
        from nomarr.workflows.navidrome.sync_song_map_wf import sync_song_map

        client = self._get_client()
        path_prefix_map = self._parse_path_prefix_map(
            self._config_service.get("navidrome_path_prefix_map", "")
        )
        return sync_song_map(
            client=client,
            path_prefix_map=path_prefix_map,
            db=self._db,
        )


    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    def get_similar_tracks(
        self,
        nd_song_id: str,
        count: int,
        backbone_id: str = "effnet-discogs",
    ) -> list[SimilarTrackResult]:
        """Find tracks similar to a Navidrome song via vector ANN search.

        Args:
            nd_song_id: Navidrome mediafile ID of the seed track.
            count: Maximum number of similar tracks to return.
            backbone_id: Vector backbone identifier.

        Returns:
            List of similar tracks with Navidrome IDs and metadata.

        Raises:
            ValueError: If song map has no mapping or no vector exists.

        """
        from nomarr.workflows.navidrome.find_similar_tracks_wf import find_similar_tracks

        return find_similar_tracks(
            seed_nd_id=nd_song_id,
            count=count,
            backbone_id=backbone_id,
            db=self._db,
        )
