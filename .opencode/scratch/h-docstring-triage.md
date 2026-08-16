# Docstring Cleanup — Phase 1 Discovery Triage

- Date: 2026-08-14
- HEAD: 4cda413a1bab82986a20a0296ba3bf75303d88ba
- Plan: TASK-postgresql-migration-second-pass-H-docstring-cleanup
- Scope: nomarr/ excluding nomarr/persistence/** and tests/**
- Pattern: quoted-string (in docstrings) scan, primary per plan; raw word-boundary counts secondary

## P1-S1: '_id' in quoted strings/docstrings

Raw distinct-match count: 22 (in-quotes); 271 matched-region lines (see note)

```
nomarr/helpers/dto/navidrome_dto.py:212:    """Result from pushing a static playlist to Navidrome.
nomarr/helpers/dto/navidrome_dto.py:213:
nomarr/helpers/dto/navidrome_dto.py:214:    Returned to the frontend after a vector-search playlist is pushed
nomarr/helpers/dto/navidrome_dto.py:215:    via the Subsonic API.  Platform-prefixed to distinguish from future
nomarr/helpers/dto/navidrome_dto.py:216:    Plex / Jellyfin equivalents.
nomarr/helpers/dto/navidrome_dto.py:217:
nomarr/helpers/dto/navidrome_dto.py:218:    Attributes:
nomarr/helpers/dto/navidrome_dto.py:219:        playlist_name: Display name written to Navidrome.
nomarr/helpers/dto/navidrome_dto.py:220:        playlist_id: Navidrome-assigned playlist ID.
nomarr/helpers/dto/navidrome_dto.py:221:        track_nd_ids: Navidrome song IDs that were successfully resolved.
nomarr/helpers/dto/navidrome_dto.py:222:        unresolved_file_ids: Nomarr file ``_id`` values with no ND mapping.
nomarr/helpers/dto/navidrome_dto.py:223:
nomarr/helpers/dto/navidrome_dto.py:224:    """
nomarr/interfaces/api/types/playlist_import_types.py:44:        description="Optional library _id to restrict matching scope",
nomarr/interfaces/api/types/info_types.py:176:    library_id: int = Field(..., description="Library document _id")
nomarr/interfaces/api/types/info_types.py:195:    library_id: int = Field(..., description="Library document _id")
nomarr/workflows/vectors/get_track_vector_wf.py:25:    """Get a track's promoted vector by file ID and backbone.
nomarr/workflows/vectors/get_track_vector_wf.py:26:
nomarr/workflows/vectors/get_track_vector_wf.py:27:    Single step: fetches the normalized vector from the per-backbone cold
nomarr/workflows/vectors/get_track_vector_wf.py:28:    collection. No library resolution needed.
nomarr/workflows/vectors/get_track_vector_wf.py:29:
nomarr/workflows/vectors/get_track_vector_wf.py:30:    Args:
nomarr/workflows/vectors/get_track_vector_wf.py:31:        db: Database instance.
nomarr/workflows/vectors/get_track_vector_wf.py:32:        file_id: Song document ``_id`` (e.g. ``"song/12345"``).
nomarr/workflows/navidrome/generate_playlists_wf.py:55:    """Generate personal playlists for *user_id* from caller-provided play history.
nomarr/workflows/navidrome/generate_playlists_wf.py:56:
nomarr/workflows/navidrome/generate_playlists_wf.py:57:    Pipeline:
nomarr/workflows/navidrome/generate_playlists_wf.py:58:        1. Compute taste profile (multi-cluster) from caller-provided play history.
nomarr/workflows/navidrome/generate_playlists_wf.py:59:        2. Filter provided plays by ``min_play_count``.
nomarr/workflows/navidrome/generate_playlists_wf.py:60:        3. Build ``NavidromePersonalPlaylistContext``.
nomarr/workflows/navidrome/generate_playlists_wf.py:61:        4. Dispatch each enabled playlist type to its component builder.
nomarr/workflows/navidrome/generate_playlists_wf.py:62:        5. Filter out playlists below ``min_songs``.
nomarr/workflows/navidrome/generate_playlists_wf.py:63:
nomarr/workflows/navidrome/generate_playlists_wf.py:64:    Vector collections are per-backbone (no library_key needed).
nomarr/workflows/navidrome/generate_playlists_wf.py:65:
nomarr/workflows/navidrome/generate_playlists_wf.py:66:    Args:
nomarr/workflows/navidrome/generate_playlists_wf.py:67:        db: Database instance.
nomarr/workflows/navidrome/generate_playlists_wf.py:68:        user_id: Navidrome user identifier.
nomarr/workflows/navidrome/generate_playlists_wf.py:69:        top_plays: Play history provided by the caller (e.g. Navidrome plugin).
nomarr/workflows/navidrome/generate_playlists_wf.py:70:            Each entry must include ``file_id``, ``playcount``, and ``last_played``.
nomarr/workflows/navidrome/generate_playlists_wf.py:71:        backbone_id: Vector backbone identifier.
nomarr/workflows/navidrome/generate_playlists_wf.py:72:        enabled_types: Which playlist types to generate.
nomarr/workflows/navidrome/generate_playlists_wf.py:73:        half_life_days: Recency half-life for taste profile.
nomarr/workflows/navidrome/generate_playlists_wf.py:74:        top_n: Max tracks to consider for taste profile.
nomarr/workflows/navidrome/generate_playlists_wf.py:75:        max_songs: Maximum tracks per playlist.
nomarr/workflows/navidrome/generate_playlists_wf.py:76:        min_play_count: Minimum plays for a track to count.
nomarr/workflows/navidrome/generate_playlists_wf.py:77:        min_songs: Minimum tracks for a playlist to be kept.
nomarr/workflows/navidrome/generate_playlists_wf.py:78:        max_genre_playlists: Maximum genre-specific playlists to generate (hard cap: 25).
nomarr/workflows/navidrome/generate_playlists_wf.py:79:        pp_max_clusters: Maximum number of genre clusters for taste profile computation.
nomarr/workflows/navidrome/generate_playlists_wf.py:80:
nomarr/workflows/navidrome/generate_playlists_wf.py:81:    Returns:
nomarr/workflows/navidrome/generate_playlists_wf.py:82:        List of generated playlists with ``song/_id`` track lists.
nomarr/workflows/navidrome/generate_playlists_wf.py:83:
nomarr/workflows/navidrome/generate_playlists_wf.py:84:    """
nomarr/workflows/library/scan_library_full_wf.py:66:    """Run a full library scan (ignores folder cache).
nomarr/workflows/library/scan_library_full_wf.py:67:
nomarr/workflows/library/scan_library_full_wf.py:68:    Walks every folder in the library regardless of cached mtime/file_count.
nomarr/workflows/library/scan_library_full_wf.py:69:    All files are re-examined for disk-level changes.
nomarr/workflows/library/scan_library_full_wf.py:70:
nomarr/workflows/library/scan_library_full_wf.py:71:    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
nomarr/workflows/library/scan_library_full_wf.py:72:    Pass 2: background tag extraction worker reads audio tags and seeds entities.
nomarr/workflows/library/scan_library_full_wf.py:73:
nomarr/workflows/library/scan_library_full_wf.py:74:    Args:
nomarr/workflows/library/scan_library_full_wf.py:75:        db: Database instance
nomarr/workflows/library/scan_library_full_wf.py:76:        library_id: Library document ``_id``
nomarr/workflows/library/scan_library_full_wf.py:77:        tagger_version: Model suite hash for version comparison
nomarr/workflows/library/scan_library_full_wf.py:78:        models_dir: Path to ML models (enables tag validation when provided)
nomarr/workflows/library/scan_library_full_wf.py:79:        namespace: Tag namespace (default ``"nom"``)
nomarr/workflows/library/scan_setup_wf.py:35:    """Validate a library and prepare it for scanning.
nomarr/workflows/library/scan_setup_wf.py:36:
nomarr/workflows/library/scan_setup_wf.py:37:    This workflow runs synchronously in the service layer before a scan
nomarr/workflows/library/scan_setup_wf.py:38:    workflow is dispatched as a background task.  Any error raised here
nomarr/workflows/library/scan_setup_wf.py:39:    is catchable at the HTTP layer.
nomarr/workflows/library/scan_setup_wf.py:40:
nomarr/workflows/library/scan_setup_wf.py:41:    Args:
nomarr/workflows/library/scan_setup_wf.py:42:        db: Database instance.
nomarr/workflows/library/scan_setup_wf.py:43:        library_id: Library document ``_id``.
nomarr/workflows/library/scan_setup_wf.py:44:        scan_type: ``"quick"`` or ``"full"`` (used only for logging).
nomarr/workflows/library/reconcile_paths_wf.py:23:    """Re-validate all library paths against current configuration.
nomarr/workflows/library/reconcile_paths_wf.py:24:
nomarr/workflows/library/reconcile_paths_wf.py:25:    This checks all files in the songs collection to detect paths that have
nomarr/workflows/library/reconcile_paths_wf.py:26:    become invalid due to config changes (library root moves, deletions, etc.).
nomarr/workflows/library/reconcile_paths_wf.py:27:    Useful after modifying library configurations or recovering from filesystem changes.
nomarr/workflows/library/reconcile_paths_wf.py:28:
nomarr/workflows/library/reconcile_paths_wf.py:29:    Args:
nomarr/workflows/library/reconcile_paths_wf.py:30:        db: Database instance
nomarr/workflows/library/reconcile_paths_wf.py:31:        library_id: Library document _id to scope reconciliation to
nomarr/workflows/library/reconcile_paths_wf.py:32:        library_root: Library root configuration (must be set)
nomarr/workflows/library/reconcile_paths_wf.py:33:        policy: What to do with invalid paths:
nomarr/workflows/library/reconcile_paths_wf.py:34:            - "dry_run": Only report, don't modify database
nomarr/workflows/library/scan_library_quick_wf.py:62:    """Run a quick (incremental) library scan.
nomarr/workflows/library/scan_library_quick_wf.py:63:
nomarr/workflows/library/scan_library_quick_wf.py:64:    Uses folder-level caching to skip unchanged folders.  Only folders
nomarr/workflows/library/scan_library_quick_wf.py:65:    whose mtime or file count changed since the last scan are walked.
nomarr/workflows/library/scan_library_quick_wf.py:66:
nomarr/workflows/library/scan_library_quick_wf.py:67:    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
nomarr/workflows/library/scan_library_quick_wf.py:68:    Pass 2: background tag extraction worker reads audio tags and seeds entities.
nomarr/workflows/library/scan_library_quick_wf.py:69:
nomarr/workflows/library/scan_library_quick_wf.py:70:    Args:
nomarr/workflows/library/scan_library_quick_wf.py:71:        db: Database instance
nomarr/workflows/library/scan_library_quick_wf.py:72:        library_id: Library document ``_id``
nomarr/workflows/library/scan_library_quick_wf.py:73:        tagger_version: Model suite hash for version comparison
nomarr/workflows/library/scan_library_quick_wf.py:74:
nomarr/workflows/library/scan_library_quick_wf.py:75:    Returns:
nomarr/workflows/library/scan_library_quick_wf.py:76:        Dict with scan statistics (files_discovered, files_added,
nomarr/workflows/library/scan_library_quick_wf.py:77:        files_updated, files_skipped, files_removed,
nomarr/workflows/library/scan_library_quick_wf.py:78:        files_failed, scan_duration_s, warnings, scan_id)
nomarr/workflows/library/scan_library_quick_wf.py:79:
nomarr/workflows/library/scan_library_quick_wf.py:80:    Raises:
nomarr/workflows/library/scan_library_quick_wf.py:81:        ValueError: If library not found
nomarr/workflows/library/scan_library_quick_wf.py:82:        OSError: If library root is inaccessible
nomarr/workflows/library/scan_library_quick_wf.py:83:
nomarr/workflows/library/scan_library_quick_wf.py:84:    """
nomarr/workflows/processing/process_file_wf.py:51:    """Run the full ML tagging pipeline for one audio file.
nomarr/workflows/processing/process_file_wf.py:52:
nomarr/workflows/processing/process_file_wf.py:53:    Validates the path, computes embeddings per backbone, runs all heads in parallel,
nomarr/workflows/processing/process_file_wf.py:54:    aggregates mood tiers, and optionally persists results to the database.
nomarr/workflows/processing/process_file_wf.py:55:
nomarr/workflows/processing/process_file_wf.py:56:    Args:
nomarr/workflows/processing/process_file_wf.py:57:        path: Path to the audio file.
nomarr/workflows/processing/process_file_wf.py:58:        config: Processing configuration (models_dir, namespace, tagger_version, etc.).
nomarr/workflows/processing/process_file_wf.py:59:        db: Database instance. Required for path resolution and metadata writes.
nomarr/workflows/processing/process_file_wf.py:60:        file_id: song document _id. Avoids path-based lookup when provided.
nomarr/workflows/processing/process_file_wf.py:61:        cache: ONNXModelCache instance. Required; auto-warmed if not already warm.
nomarr/workflows/processing/process_file_wf.py:62:
nomarr/workflows/processing/process_file_wf.py:63:    Returns:
nomarr/workflows/processing/process_file_wf.py:64:        ProcessFileResult with elapsed time, head outcomes, mood aggregations, and tags.
nomarr/workflows/processing/process_file_wf.py:65:
nomarr/workflows/processing/process_file_wf.py:66:    Raises:
nomarr/workflows/processing/process_file_wf.py:67:        ValueError: If path validation fails.
nomarr/workflows/processing/process_file_wf.py:68:        RuntimeError: If no heads are found or all heads fail.
nomarr/workflows/processing/process_file_wf.py:69:
nomarr/workflows/processing/process_file_wf.py:70:    """
nomarr/components/workers/worker_tag_comp.py:26:    """Discover and atomically claim the next file needing tag extraction.
nomarr/components/workers/worker_tag_comp.py:27:
nomarr/components/workers/worker_tag_comp.py:28:    Args:
nomarr/components/workers/worker_tag_comp.py:29:        db: Database instance
nomarr/components/workers/worker_tag_comp.py:30:        worker_id: Worker identifier for claim ownership
nomarr/components/workers/worker_tag_comp.py:31:
nomarr/components/workers/worker_tag_comp.py:32:    Returns:
nomarr/components/workers/worker_tag_comp.py:33:        File ``_id`` string if a file was claimed, ``None`` if no work available
nomarr/components/workers/worker_tag_comp.py:34:
nomarr/components/workers/worker_tag_comp.py:35:    """
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:19:    """Fetch a track's vector document from the cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:20:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:21:    Cold collections hold promoted, indexed vectors.  Hot collections are
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:22:    write-only (accumulation during ML processing) and must never be
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:23:    searched.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:24:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:25:    Uses per-backbone cold collections (cross-library).
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:26:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:27:    Args:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:28:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:29:        song_id: Library song document ``_id``.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:30:        backbone_id: Backbone identifier (e.g. ``"effnet"``).
nomarr/components/library/tag_hydration_comp.py:78:    of original song fields, so song["artist"], song["album"], etc. resolve to
nomarr/components/library/tag_hydration_comp.py:79:    tag-derived values.
nomarr/components/library/tag_hydration_comp.py:80:
nomarr/components/library/tag_hydration_comp.py:81:    Args:
nomarr/components/library/tag_hydration_comp.py:82:        db: Database instance
nomarr/components/library/tag_hydration_comp.py:83:        songs: List of song dicts to hydrate
nomarr/components/library/tag_hydration_comp.py:84:
nomarr/components/library/tag_hydration_comp.py:85:    Returns:
nomarr/components/library/tag_hydration_comp.py:86:        List of new dicts with metadata fields merged in. Songs without a
nomarr/components/library/tag_hydration_comp.py:87:        string _id are returned as shallow copies. Songs with no tags are
nomarr/components/library/tag_hydration_comp.py:88:        returned as-is (no ``None``-valued metadata keys are injected).
nomarr/components/library/tag_hydration_comp.py:89:
nomarr/components/library/tag_hydration_comp.py:90:    """
nomarr/components/library/tag_hydration_comp.py:126:    """Enrich a single song with canonical metadata derived from its tags.
nomarr/components/library/tag_hydration_comp.py:127:
nomarr/components/library/tag_hydration_comp.py:128:    Convenience wrapper around hydrate_songs_with_metadata() for call sites
nomarr/components/library/tag_hydration_comp.py:129:    that have exactly one song.
nomarr/components/library/tag_hydration_comp.py:130:
nomarr/components/library/tag_hydration_comp.py:131:    Args:
nomarr/components/library/tag_hydration_comp.py:132:        db: Database instance
nomarr/components/library/tag_hydration_comp.py:133:        song: Single song dict to hydrate
nomarr/components/library/tag_hydration_comp.py:134:
nomarr/components/library/tag_hydration_comp.py:135:    Returns:
nomarr/components/library/tag_hydration_comp.py:136:        New dict with metadata fields merged in. If the song has no string _id,
nomarr/components/library/tag_hydration_comp.py:137:        returns a shallow copy unchanged.
nomarr/components/library/tag_hydration_comp.py:138:
nomarr/components/library/tag_hydration_comp.py:139:    """
nomarr/components/library/move_detection_comp.py:27:    """Represents a detected file move."""
nomarr/components/library/move_detection_comp.py:28:
nomarr/components/library/move_detection_comp.py:29:    old_path: str
nomarr/components/library/move_detection_comp.py:30:    new_path: str
nomarr/components/library/move_detection_comp.py:31:    file_id: int  # DB _id of the moved file
nomarr/components/library/move_detection_comp.py:32:    chromaprint: str
nomarr/components/library/move_detection_comp.py:33:    old_duration: float | None
nomarr/components/library/move_detection_comp.py:34:    new_duration: float | None
nomarr/components/library/move_detection_comp.py:35:    new_file_size: int
nomarr/components/library/move_detection_comp.py:36:    new_modified_time: int
nomarr/components/library/move_detection_comp.py:37:
nomarr/components/library/move_detection_comp.py:38:
nomarr/components/library/move_detection_comp.py:39:@dataclass
nomarr/components/library/move_detection_comp.py:40:class MoveDetectionResult:
nomarr/components/library/move_detection_comp.py:41:    """Result of move detection analysis."""
nomarr/components/library/reconcile_paths_comp.py:30:    """Re-validate all library paths against current configuration.
nomarr/components/library/reconcile_paths_comp.py:31:
nomarr/components/library/reconcile_paths_comp.py:32:    This component scans the songs collection and re-validates each path
nomarr/components/library/reconcile_paths_comp.py:33:    using build_library_path_from_db() to check against current config.
nomarr/components/library/reconcile_paths_comp.py:34:    Useful after library root changes or library deletions.
nomarr/components/library/reconcile_paths_comp.py:35:
nomarr/components/library/reconcile_paths_comp.py:36:    Args:
nomarr/components/library/reconcile_paths_comp.py:37:        db: Database instance
nomarr/components/library/reconcile_paths_comp.py:38:        library_id: Library document _id to scope reconciliation to
nomarr/components/library/reconcile_paths_comp.py:39:        policy: What to do with invalid paths:
nomarr/components/library/reconcile_paths_comp.py:40:            - "dry_run": Only report, don't modify database
nomarr/services/domain/library_svc/songs.py:109:        """Re-validate all library paths against current configuration.
nomarr/services/domain/library_svc/songs.py:110:
nomarr/services/domain/library_svc/songs.py:111:        This checks all files in the songs collection to detect paths that have
nomarr/services/domain/library_svc/songs.py:112:        become invalid due to config changes (library root moves, deletions, etc.).
nomarr/services/domain/library_svc/songs.py:113:        Useful after modifying library configurations or recovering from filesystem changes.
nomarr/services/domain/library_svc/songs.py:114:
nomarr/services/domain/library_svc/songs.py:115:        Args:
nomarr/services/domain/library_svc/songs.py:116:            library_id: Library document _id to scope reconciliation to
nomarr/services/domain/library_svc/songs.py:117:            policy: What to do with invalid paths:
nomarr/services/domain/library_svc/songs.py:118:                - "dry_run": Only report, don't modify database
nomarr/services/domain/playlist_import_svc.py:51:        """Convert a streaming playlist URL to local M3U playlist.
nomarr/services/domain/playlist_import_svc.py:52:
nomarr/services/domain/playlist_import_svc.py:53:        Supports:
nomarr/services/domain/playlist_import_svc.py:54:        - Spotify: https://open.spotify.com/playlist/{id}
nomarr/services/domain/playlist_import_svc.py:55:        - Deezer: https://deezer.com/playlist/{id} or link.deezer.com short links
nomarr/services/domain/playlist_import_svc.py:56:
nomarr/services/domain/playlist_import_svc.py:57:        Args:
nomarr/services/domain/playlist_import_svc.py:58:            playlist_url: Full URL to a Spotify or Deezer playlist
nomarr/services/domain/playlist_import_svc.py:59:            library_id: Optional library _id to restrict matching scope
nomarr/services/domain/playlist_import_svc.py:60:
nomarr/services/domain/playlist_import_svc.py:61:        Returns:
nomarr/services/domain/playlist_import_svc.py:62:            PlaylistConversionResult with:
nomarr/services/domain/playlist_import_svc.py:63:            - m3u_content: Ready-to-save M3U file content
nomarr/services/domain/playlist_import_svc.py:64:            - Match statistics (total, matched, exact, fuzzy, ambiguous, not_found)
nomarr/services/domain/playlist_import_svc.py:65:            - Full match_results for detailed review
nomarr/services/domain/playlist_import_svc.py:66:
nomarr/services/domain/playlist_import_svc.py:67:        Raises:
nomarr/services/domain/playlist_import_svc.py:68:            PlaylistConversionError: If URL is invalid, API fails, or no library exists
nomarr/services/domain/playlist_import_svc.py:69:
nomarr/services/domain/playlist_import_svc.py:70:        """
nomarr/services/domain/analytics_svc.py:195:        """Get mood distribution with wrapper DTO.
nomarr/services/domain/analytics_svc.py:196:
nomarr/services/domain/analytics_svc.py:197:        Same data as ``get_mood_distribution`` but wrapped in a
nomarr/services/domain/analytics_svc.py:198:        ``MoodDistributionResult`` DTO suitable for API responses.
nomarr/services/domain/analytics_svc.py:199:
nomarr/services/domain/analytics_svc.py:200:        Args:
nomarr/services/domain/analytics_svc.py:201:            library_id: Optional library ``_id`` to filter by.
nomarr/services/domain/analytics_svc.py:202:
nomarr/services/domain/analytics_svc.py:203:        Returns:
nomarr/services/domain/analytics_svc.py:204:            MoodDistributionResult DTO with mood_distribution list.
nomarr/services/domain/analytics_svc.py:205:
nomarr/services/domain/analytics_svc.py:206:        """
nomarr/services/domain/tagging_svc/query.py:93:        """Get songs linked to a tag with metadata.
nomarr/services/domain/tagging_svc/query.py:94:
nomarr/services/domain/tagging_svc/query.py:95:        Args:
nomarr/services/domain/tagging_svc/query.py:96:            tag_id: Tag _id
nomarr/services/domain/tagging_svc/query.py:97:            limit: Max results
nomarr/services/domain/tagging_svc/query.py:98:            offset: Pagination offset
nomarr/services/domain/tagging_svc/query.py:99:
nomarr/services/domain/tagging_svc/query.py:100:        Returns:
nomarr/services/domain/tagging_svc/query.py:101:            Dict with songs list and total count.
nomarr/services/domain/tagging_svc/query.py:102:
nomarr/services/domain/tagging_svc/query.py:103:        """
nomarr/services/domain/tagging_svc/query.py:130:        """Commit pending tag writes by writing tags for affected libraries.
nomarr/services/domain/tagging_svc/query.py:131:
nomarr/services/domain/tagging_svc/query.py:132:        Args:
nomarr/services/domain/tagging_svc/query.py:133:            library_id: Optional library _id to scope. If None, finds libraries
nomarr/services/domain/tagging_svc/query.py:134:                        with pending files.
nomarr/services/domain/tagging_svc/query.py:135:
nomarr/services/domain/tagging_svc/query.py:136:        Returns:
nomarr/services/domain/tagging_svc/query.py:137:            CommitResult with started flag and pending file count.
nomarr/services/domain/tagging_svc/query.py:138:
nomarr/services/domain/tagging_svc/query.py:139:        """
```

## P1-S2: '_key' in quoted strings/docstrings

Raw distinct-match count: 4 (in-quotes); 30 matched-region lines (see note)

```
nomarr/workflows/processing/write_file_tags_wf.py:46:    """Result from write_file_tags_workflow."""
nomarr/workflows/processing/write_file_tags_wf.py:47:
nomarr/workflows/processing/write_file_tags_wf.py:48:    file_key: str  # Document _key of the file
nomarr/workflows/processing/write_file_tags_wf.py:49:    tags_written: int  # Number of tags written to file
nomarr/workflows/processing/write_file_tags_wf.py:50:    tags_filtered: int  # Number of tags filtered out by mode
nomarr/workflows/processing/write_file_tags_wf.py:51:    success: bool  # Whether write succeeded
nomarr/workflows/processing/write_file_tags_wf.py:52:    error: str | None = None  # Error message if failed
nomarr/workflows/processing/write_file_tags_wf.py:53:
nomarr/workflows/processing/write_file_tags_wf.py:54:
nomarr/workflows/processing/write_file_tags_wf.py:55:def _filter_tags_for_mode(
nomarr/workflows/processing/write_file_tags_wf.py:56:    db_tags: Tags,
nomarr/workflows/processing/write_file_tags_wf.py:57:    target_mode: str,
nomarr/workflows/processing/write_file_tags_wf.py:58:    has_calibration: bool,
nomarr/workflows/processing/write_file_tags_wf.py:59:) -> Tags:
nomarr/workflows/processing/write_file_tags_wf.py:60:    """Filter tags based on target mode and calibration state.
nomarr/workflows/processing/write_file_tags_wf.py:113:    """Write tags from database to an audio file based on mode.
nomarr/workflows/processing/write_file_tags_wf.py:114:
nomarr/workflows/processing/write_file_tags_wf.py:115:    This workflow reads tags from the database and writes them to the audio
nomarr/workflows/processing/write_file_tags_wf.py:116:    file using the appropriate mode filtering. It uses atomic safe writes
nomarr/workflows/processing/write_file_tags_wf.py:117:    via TagWriter to prevent file corruption.
nomarr/workflows/processing/write_file_tags_wf.py:118:
nomarr/workflows/processing/write_file_tags_wf.py:119:    Args:
nomarr/workflows/processing/write_file_tags_wf.py:120:        db: Database instance
nomarr/workflows/processing/write_file_tags_wf.py:121:        file_key: Document _key of the file to write
nomarr/workflows/processing/write_file_tags_wf.py:122:        target_mode: Desired write mode ("none", "minimal", "full")
nomarr/components/ml/calibration/ml_calibration_state_comp.py:93:    """
nomarr/components/ml/calibration/ml_calibration_state_comp.py:94:    _key = _make_calibration_state_key(head_name, label)
nomarr/components/ml/calibration/ml_calibration_state_comp.py:95:    doc = {
nomarr/components/ml/calibration/ml_calibration_state_comp.py:96:        "key": _key,
nomarr/components/ml/calibration/ml_calibration_state_comp.py:97:        "head_name": head_name,
```

## P1-S3: '_rev' in quoted strings/docstrings

Raw distinct-match count: 0 (in-quotes); 0 matched-region lines

```
```

## P1-S4: ArangoDB terminology (collection|document|vertex|edge|AQL) in quoted strings/docstrings

Raw distinct-match count: 169 (in-quotes); 1259 matched-region lines (see note)

```
nomarr/helpers/vector_params_helper.py:19:    """Compute the pgvector HNSW ``ef_search`` parameter for query-time width.
nomarr/helpers/vector_params_helper.py:20:
nomarr/helpers/vector_params_helper.py:21:    ``ef_search`` controls how many candidates are examined during an ANN
nomarr/helpers/vector_params_helper.py:22:    query.  Higher values improve recall at the cost of latency.
nomarr/helpers/vector_params_helper.py:23:
nomarr/helpers/vector_params_helper.py:24:    Guidelines:
nomarr/helpers/vector_params_helper.py:25:        - Small collections (~1K docs): 40
nomarr/helpers/vector_params_helper.py:26:        - Medium (~10K): 100
nomarr/helpers/vector_params_helper.py:27:        - Large (~100K+): 200 to 400
nomarr/helpers/vector_params_helper.py:28:
nomarr/helpers/vector_params_helper.py:29:    Args:
nomarr/helpers/vector_params_helper.py:30:        doc_count: Total number of vectors in the collection.
nomarr/helpers/vector_params_helper.py:31:
nomarr/helpers/vector_params_helper.py:32:    Returns:
nomarr/helpers/vector_params_helper.py:33:        ef_search value (minimum 20).  Returns 100 for unknown/zero counts
nomarr/helpers/vector_params_helper.py:34:        as a sensible medium-collection default.
nomarr/helpers/vector_params_helper.py:35:
nomarr/helpers/vector_params_helper.py:36:    """
nomarr/helpers/vector_params_helper.py:49:    """Compute the pgvector HNSW ``ef_construction`` parameter for build-time quality.
nomarr/helpers/vector_params_helper.py:50:
nomarr/helpers/vector_params_helper.py:51:    ``ef_construction`` controls the width of search during index creation.
nomarr/helpers/vector_params_helper.py:52:    Higher values produce a better-quality graph but slower index builds.
nomarr/helpers/vector_params_helper.py:53:
nomarr/helpers/vector_params_helper.py:54:    Guidelines:
nomarr/helpers/vector_params_helper.py:55:        - Minimum: 100
nomarr/helpers/vector_params_helper.py:56:        - Large collections (~100K+): up to 500
nomarr/helpers/vector_params_helper.py:57:
nomarr/helpers/vector_params_helper.py:58:    Args:
nomarr/helpers/vector_params_helper.py:59:        doc_count: Total number of vectors in the collection.
nomarr/helpers/vector_params_helper.py:60:
nomarr/helpers/vector_params_helper.py:61:    Returns:
nomarr/helpers/vector_params_helper.py:62:        ef_construction value (100 to 500).  Returns 200 for unknown/zero counts.
nomarr/helpers/vector_params_helper.py:63:
nomarr/helpers/vector_params_helper.py:64:    """
nomarr/helpers/constants/file_states.py:1:"""Canonical song-state axis-pair vertex identifiers shared across layers.
nomarr/helpers/constants/file_states.py:2:
nomarr/helpers/constants/file_states.py:3:State constants use bare axis names per AR-SDR-6.
nomarr/helpers/constants/file_states.py:4:"""
nomarr/helpers/filter_types.py:1:"""Filter operator types for the persistence constructor.
nomarr/helpers/filter_types.py:2:
nomarr/helpers/filter_types.py:3:These types are used across all layers (components, workflows, services)
nomarr/helpers/filter_types.py:4:to build filter expressions for collection queries.  They live in helpers
nomarr/helpers/filter_types.py:5:so that every layer can import them without violating dependency rules.
nomarr/helpers/filter_types.py:6:"""
nomarr/helpers/config_schema.py:1:"""Config schema registry — single source of truth for all config keys.
nomarr/helpers/config_schema.py:2:
nomarr/helpers/config_schema.py:3:This module defines the typed dataclasses, defaults, UI metadata, and derived
nomarr/helpers/config_schema.py:4:key sets that ConfigService and the web frontend consume.  Nothing else in the
nomarr/helpers/config_schema.py:5:codebase should hard-code config key names or defaults.
nomarr/helpers/config_schema.py:6:
nomarr/helpers/config_schema.py:7:Architecture:
nomarr/helpers/config_schema.py:8:    StaticConfig  — frozen, startup-only (paths, admin password)
nomarr/helpers/config_schema.py:9:    DynamicConfig — mutable, web-editable (worker count, flags, API creds)
nomarr/helpers/config_schema.py:10:    DYNAMIC_FIELD_META — UI labels/descriptions co-located with DynamicConfig
nomarr/helpers/config_schema.py:11:    LibraryConfigFields — per-library document sub-schema (TypedDict)
nomarr/helpers/config_schema.py:12:"""
nomarr/helpers/exceptions_helper.py:15:    """Raised when a library document cannot be found by its ID."""
nomarr/helpers/__init__.py:1:"""Helpers layer — pure utility code and cross-cutting data structures.
nomarr/helpers/__init__.py:2:
nomarr/helpers/__init__.py:3:Helpers are leaf utilities with no layer-level dependencies. They provide:
nomarr/helpers/__init__.py:4:
nomarr/helpers/__init__.py:5:- **DTOs** (``dto/``) — Domain-specific data-transfer objects used as contracts
nomarr/helpers/__init__.py:6:  between all layers (interfaces → services → workflows → components).
nomarr/helpers/__init__.py:7:- **Time utilities** (``time_helper.py``) — Type-safe wall-clock and monotonic
nomarr/helpers/__init__.py:8:  time with distinct ``Milliseconds``/``Seconds`` newtypes.
nomarr/helpers/__init__.py:9:- **File utilities** (``files_helper.py``, ``file_validation_helper.py``) —
nomarr/helpers/__init__.py:10:  Library path resolution with security validation and audio file collection.
nomarr/helpers/__init__.py:11:- **Exceptions** (``exceptions.py``) — Shared exception hierarchy across layers.
nomarr/helpers/__init__.py:12:- **Logging** (``logging_helper.py``) — Structured context logging with
nomarr/helpers/__init__.py:13:  sanitized exception messages.
nomarr/helpers/__init__.py:14:- **Vector params** (``vector_params_helper.py``) — pgvector HNSW parameter
nomarr/helpers/__init__.py:15:  computation (ef_search, ef_construction, M).
nomarr/helpers/__init__.py:16:- **Configuration** (``config_schema.py``) — Static/dynamic config models and
nomarr/helpers/__init__.py:17:  validation.
nomarr/helpers/__init__.py:18:- **Constants** (``constants/``) — Domain constants for file states and pipeline
nomarr/helpers/__init__.py:19:  axes shared across layers.
nomarr/helpers/__init__.py:20:
nomarr/helpers/__init__.py:21:Rules:
nomarr/helpers/__init__.py:22:- No I/O beyond what stdlib provides (no DB, no network).
nomarr/helpers/__init__.py:23:- No imports from services, workflows, or components.
nomarr/helpers/__init__.py:24:- Pure functions and dataclasses only.
nomarr/helpers/__init__.py:25:"""
nomarr/helpers/exceptions.py:17:    """Raised when a library document cannot be found by its ID."""
nomarr/helpers/dataclasses/tags_dataclass.py:55:    """Canonical non-empty collection of Tag objects.
nomarr/helpers/dataclasses/tags_dataclass.py:56:
nomarr/helpers/dataclasses/tags_dataclass.py:57:    Input tags are canonicalized during construction:
nomarr/helpers/dataclasses/tags_dataclass.py:58:    - duplicate tag names are merged
nomarr/helpers/dataclasses/tags_dataclass.py:59:    - duplicate values are removed per name
nomarr/helpers/dataclasses/tags_dataclass.py:60:    - tags are sorted by name for deterministic behavior
nomarr/helpers/dataclasses/tags_dataclass.py:61:    An empty tag collection is invalid in Nomarr. Use None to represent unloaded,
nomarr/helpers/dataclasses/tags_dataclass.py:62:    unreadable, or missing tags.
nomarr/helpers/dataclasses/tags_dataclass.py:63:    Frozen for immutability - create new Tags instead of mutating.
nomarr/helpers/dataclasses/tags_dataclass.py:64:    """
nomarr/interfaces/api/types/vector_types.py:18:    file_id: str = Field(..., description="Library file document ID to find similar tracks for")
nomarr/interfaces/api/types/vector_types.py:27:    file_id: int = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/vector_types.py:46:    hot_count: int = Field(..., description="Number of vectors in hot collection")
nomarr/interfaces/api/types/vector_types.py:47:    cold_count: int = Field(..., description="Number of vectors in cold collection")
nomarr/interfaces/api/types/vector_types.py:48:    index_exists: bool = Field(..., description="Whether cold collection has vector index")
nomarr/interfaces/api/types/vector_types.py:84:    file_id: int = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/analytics_types.py:180:    """Response for collection overview endpoint."""
nomarr/interfaces/api/types/analytics_types.py:194:        """Convert collection overview result dict to Pydantic response model."""
nomarr/interfaces/api/types/playlist_import_types.py:86:    file_id: str = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/ml_types.py:17:    """Response model for a registered ML model vertex."""
nomarr/interfaces/api/types/info_types.py:176:    library_id: int = Field(..., description="Library document _id")
nomarr/interfaces/api/types/info_types.py:195:    library_id: int = Field(..., description="Library document _id")
nomarr/interfaces/api/web/analytics_if.py:122:@router.get("/collection-overview", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/analytics_if.py:127:    """Get collection overview statistics.
nomarr/interfaces/api/web/analytics_if.py:128:
nomarr/interfaces/api/web/analytics_if.py:129:    Returns library stats, year/genre distributions.
nomarr/interfaces/api/web/analytics_if.py:130:    Optionally filtered by library_id.
nomarr/interfaces/api/web/analytics_if.py:131:    """
nomarr/interfaces/api/web/analytics_if.py:136:        logger.exception("[Web API] Error getting collection overview")
nomarr/interfaces/api/web/analytics_if.py:139:            detail=sanitize_exception_message(e, "Failed to get collection overview"),
nomarr/interfaces/api/web/metadata_if.py:25:router = APIRouter(tags=["metadata"], prefix="/metadata")
nomarr/interfaces/api/web/metadata_if.py:26:
nomarr/interfaces/api/web/metadata_if.py:27:# Type alias for entity collection names
nomarr/interfaces/api/web/metadata_if.py:28:EntityCollection = Literal["artist", "album", "label", "genre", "year"]
nomarr/interfaces/api/web/metadata_if.py:40:@router.get("/{collection}", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/metadata_if.py:48:    """List entities from a collection (artist, album, label, genre, year)."""
nomarr/interfaces/api/web/metadata_if.py:49:    result = await asyncio.to_thread(
nomarr/interfaces/api/web/metadata_if.py:50:        metadata_service.list_entities, collection, limit=limit, offset=offset, search=search
nomarr/interfaces/api/web/metadata_if.py:51:    )
nomarr/interfaces/api/web/metadata_if.py:52:    return EntityListResponse.from_dto(result)
nomarr/interfaces/api/web/metadata_if.py:53:
nomarr/interfaces/api/web/metadata_if.py:54:
nomarr/interfaces/api/web/metadata_if.py:55:@router.get("/{collection}/{entity_id}", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/metadata_if.py:56:async def get_entity(
nomarr/interfaces/api/web/metadata_if.py:57:    collection: EntityCollection,  # noqa: ARG001  # FastAPI path param name is part of the URL contract
nomarr/interfaces/api/web/metadata_if.py:58:    entity_id: str,
nomarr/interfaces/api/web/metadata_if.py:59:    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
nomarr/interfaces/api/web/metadata_if.py:60:) -> EntityResponse:
nomarr/interfaces/api/web/metadata_if.py:61:    """Get entity details by ID.
nomarr/interfaces/api/web/metadata_if.py:62:
nomarr/interfaces/api/web/metadata_if.py:63:    Note: entity_id should be encoded (e.g., artists:v1_abc123).
nomarr/interfaces/api/web/metadata_if.py:64:    Collection parameter is informational only (entity_id already contains collection).
nomarr/interfaces/api/web/metadata_if.py:65:    """
nomarr/interfaces/api/web/metadata_if.py:73:@router.get("/{collection}/{entity_id}/song", dependencies=[Depends(verify_session)])
nomarr/workflows/calibration/calibration_loader_wf.py:30:    """Load all calibrations from calibration_state collection.
nomarr/workflows/calibration/calibration_loader_wf.py:31:
nomarr/workflows/calibration/calibration_loader_wf.py:32:    Returns dict mapping label -> {p5, p95} for use in aggregation.
nomarr/workflows/calibration/calibration_loader_wf.py:33:    Format matches legacy sidecar structure for compatibility with aggregation logic.
nomarr/workflows/calibration/calibration_loader_wf.py:34:
nomarr/workflows/calibration/calibration_loader_wf.py:35:    Args:
nomarr/workflows/calibration/calibration_loader_wf.py:36:        db: Database instance
nomarr/workflows/calibration/calibration_loader_wf.py:37:
nomarr/workflows/calibration/calibration_loader_wf.py:38:    Returns:
nomarr/workflows/calibration/calibration_loader_wf.py:39:        Dict mapping label (e.g., "happy") to {p5: float, p95: float}
nomarr/workflows/calibration/calibration_loader_wf.py:86:    """Load calibrations with caching based on version hash.
nomarr/workflows/calibration/calibration_loader_wf.py:87:
nomarr/workflows/calibration/calibration_loader_wf.py:88:    Checks calibration_version in meta collection. If version matches cached
nomarr/workflows/calibration/calibration_loader_wf.py:89:    version, returns cached calibrations without database query.
nomarr/workflows/calibration/calibration_loader_wf.py:90:
nomarr/workflows/calibration/calibration_loader_wf.py:91:    Cache is module-level (per-process), so workers maintain separate caches.
nomarr/workflows/calibration/calibration_loader_wf.py:92:    Version check is ~2-5ms single document lookup vs ~50ms full calibration load.
nomarr/workflows/calibration/calibration_loader_wf.py:93:
nomarr/workflows/calibration/calibration_loader_wf.py:94:    Args:
nomarr/workflows/calibration/calibration_loader_wf.py:95:        db: Database instance
nomarr/workflows/calibration/calibration_loader_wf.py:96:
nomarr/workflows/calibration/calibration_loader_wf.py:97:    Returns:
nomarr/workflows/calibration/calibration_loader_wf.py:98:        Dict mapping label to {p5, p95}
nomarr/workflows/calibration/calibration_loader_wf.py:99:        Empty dict if no calibrations exist
nomarr/workflows/calibration/calibration_loader_wf.py:100:
nomarr/workflows/calibration/calibration_loader_wf.py:101:    Note:
nomarr/workflows/calibration/calibration_loader_wf.py:102:        When calibration generation completes, it updates calibration_version in meta,
nomarr/workflows/calibration/calibration_loader_wf.py:103:        causing cache invalidation on next check.
nomarr/workflows/calibration/calibration_loader_wf.py:104:
nomarr/workflows/calibration/calibration_loader_wf.py:105:    """
nomarr/workflows/calibration/import_calibration_bundle_wf.py:47:    """Import calibration bundle from disk into database.
nomarr/workflows/calibration/import_calibration_bundle_wf.py:48:
nomarr/workflows/calibration/import_calibration_bundle_wf.py:49:    Parses bundle JSON file, upserts calibrations to calibration_state,
nomarr/workflows/calibration/import_calibration_bundle_wf.py:50:    and updates global calibration version in meta collection.
nomarr/workflows/calibration/import_calibration_bundle_wf.py:51:
nomarr/workflows/calibration/import_calibration_bundle_wf.py:52:    BUNDLE FORMAT (expected JSON structure):
nomarr/workflows/calibration/import_calibration_bundle_wf.py:53:    {
nomarr/workflows/calibration/import_calibration_bundle_wf.py:54:        "labels": {
nomarr/workflows/vectors/get_track_vector_wf.py:1:"""Retrieve a track's normalized embedding vector.
nomarr/workflows/vectors/get_track_vector_wf.py:2:
nomarr/workflows/vectors/get_track_vector_wf.py:3:Fetches the promoted vector directly from the per-backbone cold collection.
nomarr/workflows/vectors/get_track_vector_wf.py:4:No library resolution needed — vector collections are per-backbone.
nomarr/workflows/vectors/get_track_vector_wf.py:5:"""
nomarr/workflows/vectors/get_track_vector_wf.py:25:    """Get a track's promoted vector by file ID and backbone.
nomarr/workflows/vectors/get_track_vector_wf.py:26:
nomarr/workflows/vectors/get_track_vector_wf.py:27:    Single step: fetches the normalized vector from the per-backbone cold
nomarr/workflows/vectors/get_track_vector_wf.py:28:    collection. No library resolution needed.
nomarr/workflows/vectors/get_track_vector_wf.py:29:
nomarr/workflows/vectors/get_track_vector_wf.py:30:    Args:
nomarr/workflows/vectors/get_track_vector_wf.py:31:        db: Database instance.
nomarr/workflows/vectors/get_track_vector_wf.py:32:        file_id: Song document ``_id`` (e.g. ``"song/12345"``).
nomarr/workflows/vectors/get_track_vector_wf.py:33:        backbone_id: Backbone identifier (e.g. ``"effnet"``).
nomarr/workflows/vectors/get_track_vector_wf.py:34:
nomarr/workflows/vectors/get_track_vector_wf.py:35:    Returns:
nomarr/workflows/vectors/get_track_vector_wf.py:36:        Vector document dict (includes ``vector_n``, ``file_id``, etc.)
nomarr/workflows/vectors/get_track_vector_wf.py:37:        or ``None`` when no promoted vector exists in the cold collection.
nomarr/workflows/vectors/get_track_vector_wf.py:38:
nomarr/workflows/vectors/get_track_vector_wf.py:39:    """
nomarr/workflows/platform/prepare_database_wf.py:73:    """
nomarr/workflows/platform/prepare_database_wf.py:74:    # Step 1: Run Alembic migrations (handles both fresh and existing databases)
nomarr/workflows/platform/prepare_database_wf.py:75:    _run_alembic_upgrade()
nomarr/workflows/platform/prepare_database_wf.py:76:
nomarr/workflows/platform/prepare_database_wf.py:77:    # Step 2: Prune orphaned song documents (no ownership edge).
nomarr/workflows/platform/prepare_database_wf.py:78:    # Runs before ML model registration so any orphan-related vector data
nomarr/workflows/platform/prepare_database_wf.py:79:    # are already clean before models are re-registered.
nomarr/workflows/platform/prepare_database_wf.py:80:    try:
nomarr/workflows/platform/prepare_database_wf.py:81:        from nomarr.workflows.platform.prune_orphaned_files_wf import prune_orphaned_files_workflow
nomarr/workflows/platform/prepare_database_wf.py:82:
nomarr/workflows/platform/prepare_database_wf.py:83:        prune_orphaned_files_workflow(db)
nomarr/workflows/platform/prepare_database_wf.py:84:    except Exception as exc:
nomarr/workflows/platform/prepare_database_wf.py:85:        logger.warning("Orphaned file pruning failed (non-fatal): %s", exc, exc_info=True)
nomarr/workflows/platform/prune_orphaned_files_wf.py:1:"""Startup-time pruning of orphaned tracks.
nomarr/workflows/platform/prune_orphaned_files_wf.py:2:
nomarr/workflows/platform/prune_orphaned_files_wf.py:3:A song document is orphaned when it has no inbound library_contains_file
nomarr/workflows/platform/prune_orphaned_files_wf.py:4:edge — this happens when a library was deleted while the deletion code was broken,
nomarr/workflows/platform/prune_orphaned_files_wf.py:5:or when a scan was interrupted after writing file docs but before writing the
nomarr/workflows/platform/prune_orphaned_files_wf.py:6:ownership edges.
nomarr/workflows/platform/prune_orphaned_files_wf.py:7:
nomarr/workflows/platform/prune_orphaned_files_wf.py:8:Orphaned files are invisible to all scan and ML pipeline queries (which traverse
nomarr/workflows/platform/prune_orphaned_files_wf.py:9:ownership edges), but they persist in the collection and bloat counts. They also
nomarr/workflows/platform/prune_orphaned_files_wf.py:10:prevent re-adding the same file path via a fresh scan because the path-uniqueness
nomarr/workflows/platform/prune_orphaned_files_wf.py:11:check finds the old document and returns it as "existing".
nomarr/workflows/platform/prune_orphaned_files_wf.py:28:    """Delete all tracks that have no owning library.
nomarr/workflows/platform/prune_orphaned_files_wf.py:29:
nomarr/workflows/platform/prune_orphaned_files_wf.py:30:    Cleans all derived data for each orphan in the same order used by
nomarr/workflows/platform/prune_orphaned_files_wf.py:31:    remove_library: output streams → vectors → tag edges → claim →
nomarr/workflows/platform/prune_orphaned_files_wf.py:32:    state edges → file document.
nomarr/workflows/platform/prune_orphaned_files_wf.py:33:
nomarr/workflows/platform/prune_orphaned_files_wf.py:34:    Returns a stats dict with ``files_pruned``.
nomarr/workflows/platform/prune_orphaned_files_wf.py:35:    """
nomarr/workflows/platform/register_ml_models_wf.py:42:    """Walk the models directory and register all ONNX head models.
nomarr/workflows/platform/register_ml_models_wf.py:43:
nomarr/workflows/platform/register_ml_models_wf.py:44:    For each ``*.onnx`` file found under ``models/<backbone>/heads/<type>/``:
nomarr/workflows/platform/register_ml_models_wf.py:45:
nomarr/workflows/platform/register_ml_models_wf.py:46:    1. Parse path metadata (backbone, head type, model stem)
nomarr/workflows/platform/register_ml_models_wf.py:47:    2. Introspect ONNX session for output dimension count
nomarr/workflows/platform/register_ml_models_wf.py:48:    3. Upsert model vertex into ``ml_models``
nomarr/workflows/platform/register_ml_models_wf.py:49:    4. Ensure output vertices exist in ``ml_model_outputs``
nomarr/workflows/platform/register_ml_models_wf.py:50:    5. Seed missing labels from known defaults if the model is shipped by nomarr
nomarr/workflows/platform/register_ml_models_wf.py:51:
nomarr/workflows/platform/register_ml_models_wf.py:52:    Models with all outputs labeled are marked ``fully_configured=True``.
nomarr/workflows/platform/register_ml_models_wf.py:53:    Unknown models remain unconfigured until the user labels them via UI.
nomarr/workflows/platform/register_ml_models_wf.py:54:
nomarr/workflows/platform/register_ml_models_wf.py:55:    Args:
nomarr/workflows/platform/register_ml_models_wf.py:56:        db: Database instance with ml_models and ml_model_outputs operations.
nomarr/workflows/platform/register_ml_models_wf.py:57:        models_dir: Root path to the ML models directory.
nomarr/workflows/platform/register_ml_models_wf.py:58:
nomarr/workflows/platform/register_ml_models_wf.py:59:    """
nomarr/workflows/platform/register_ml_models_wf.py:76:        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
nomarr/workflows/platform/register_ml_models_wf.py:77:        output_shape = session.get_outputs()[0].shape
nomarr/workflows/platform/register_ml_models_wf.py:78:        output_count = int(output_shape[-1])
nomarr/workflows/platform/register_ml_models_wf.py:79:
nomarr/workflows/platform/register_ml_models_wf.py:80:        # Step 3: Upsert model vertex
nomarr/workflows/platform/register_ml_models_wf.py:81:        known_outputs = get_known_outputs(model_stem)
nomarr/workflows/platform/register_ml_models_wf.py:82:        source = "known" if known_outputs is not None else "discovered"
nomarr/workflows/platform/register_ml_models_wf.py:146:            "Pruned stale model %s: removed %d output(s) and %d edge(s)",
nomarr/workflows/platform/backfill_vector_genres_wf.py:24:    """Backfill missing ``genres`` arrays on a cold vector collection.
nomarr/workflows/platform/backfill_vector_genres_wf.py:25:
nomarr/workflows/platform/backfill_vector_genres_wf.py:26:    Args:
nomarr/workflows/platform/backfill_vector_genres_wf.py:27:        db: Database instance.
nomarr/workflows/platform/backfill_vector_genres_wf.py:28:        backbone_id: Backbone identifier (e.g., ``"discogs_effnet"``).
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:17:    """Clean up orphaned tags from the tags collection.
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:18:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:19:    Removes tags that have no incoming edges from songs. This happens when
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:20:    songs are deleted or metadata is updated.
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:21:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:22:    Note: Function name kept for API compatibility, but now cleans tags.
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:23:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:24:    Args:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:25:        db: Database instance
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:26:        dry_run: If True, count orphaned tags but don't delete them
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:27:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:28:    Returns:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:29:        Dict with:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:30:        - 'orphaned_counts': Dict with 'tags' -> count of orphaned tags found
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:31:        - 'deleted_counts': Dict with 'tags' -> count of tags deleted (0 if dry_run)
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:32:        - 'total_orphaned': Total orphaned tags
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:33:        - 'total_deleted': Total deleted tags (0 if dry_run)
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:34:
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:35:    """
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:26:    """Generate Navidrome TOML configuration for custom tags.
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:27:
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:28:    Queries the tags collection to discover all nomarr tags, detects their types,
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:29:    and generates proper TOML configuration with user-friendly field names.
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:30:
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:31:    The field names are short (e.g., nom_happy_raw) while the aliases point to
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:32:    the full versioned storage keys for all three tag formats (ID3, iTunes, Vorbis).
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:33:
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:34:    Args:
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:35:        db: Database instance
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:36:        namespace: Tag namespace (default: "nom")
nomarr/workflows/navidrome/find_similar_tracks_wf.py:50:    """Find tracks similar to a portable seed descriptor.
nomarr/workflows/navidrome/find_similar_tracks_wf.py:51:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:52:    Pipeline:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:53:        1. Resolve seed descriptor to a library song id
nomarr/workflows/navidrome/find_similar_tracks_wf.py:54:        2. Fetch seed vector from the promoted cold collection via components
nomarr/workflows/navidrome/find_similar_tracks_wf.py:55:        3. Run ANN search on cold collection
nomarr/workflows/navidrome/find_similar_tracks_wf.py:56:        4. Enrich result song_ids with descriptor metadata
nomarr/workflows/navidrome/find_similar_tracks_wf.py:57:        5. Return up to ``count`` results sorted by similarity score
nomarr/workflows/navidrome/find_similar_tracks_wf.py:58:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:59:    Args:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:60:        seed_descriptor: Portable seed track descriptor from plugin.
nomarr/workflows/navidrome/find_similar_tracks_wf.py:61:        count: Maximum number of similar tracks to return.
nomarr/workflows/navidrome/find_similar_tracks_wf.py:62:        backbone_id: Vector backbone identifier (e.g., "effnet").
nomarr/workflows/navidrome/find_similar_tracks_wf.py:83:    logger.debug("Seed descriptor resolved to file_id %s", seed_file_id)
nomarr/workflows/navidrome/find_similar_tracks_wf.py:84:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:85:    # 2. Get seed vector from per-backbone cold collection (no library_key needed)
nomarr/workflows/navidrome/find_similar_tracks_wf.py:86:    seed_doc = get_cold_track_vector(db, seed_file_id, backbone_id)
nomarr/workflows/navidrome/find_similar_tracks_wf.py:87:    if seed_doc is None:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:88:        msg = (
nomarr/workflows/navidrome/find_similar_tracks_wf.py:89:            f"No vector embedding found for file '{seed_file_id}' "
nomarr/workflows/navidrome/find_similar_tracks_wf.py:95:    logger.debug("Seed vector retrieved, dim=%d", len(seed_vector))
nomarr/workflows/navidrome/find_similar_tracks_wf.py:96:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:97:    # 3. ANN search on per-backbone cold collection
nomarr/workflows/navidrome/find_similar_tracks_wf.py:98:    fetch_limit = count + 1  # +1 for potential self-match
nomarr/workflows/navidrome/find_similar_tracks_wf.py:99:    raw_results = search_similar_cold_track_vectors(
nomarr/workflows/navidrome/find_similar_tracks_wf.py:100:        db=db,
nomarr/workflows/navidrome/find_similar_tracks_wf.py:101:        backbone_id=backbone_id,
nomarr/workflows/navidrome/find_similar_tracks_wf.py:102:        seed_vector=seed_vector,
nomarr/workflows/navidrome/find_similar_tracks_wf.py:103:        result_limit=fetch_limit,
nomarr/workflows/navidrome/find_similar_tracks_wf.py:104:    )
nomarr/workflows/navidrome/find_similar_tracks_wf.py:105:
nomarr/workflows/navidrome/find_similar_tracks_wf.py:106:    # Exclude the seed track itself from results
nomarr/workflows/navidrome/find_similar_tracks_wf.py:107:    results = [r for r in raw_results if r["song_id"] != seed_file_id]
nomarr/workflows/navidrome/generate_static_playlist_wf.py:1:"""Generate static M3U playlist from a list of file IDs.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:2:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:3:This workflow accepts a list of library file document IDs,
nomarr/workflows/navidrome/generate_static_playlist_wf.py:4:resolves their paths and metadata from the database, and
nomarr/workflows/navidrome/generate_static_playlist_wf.py:5:generates M3U playlist content suitable for Navidrome import.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:6:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:7:Unlike smart playlists (.nsp) which are rule-based, this produces
nomarr/workflows/navidrome/generate_static_playlist_wf.py:8:a fixed, static playlist of specific tracks.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:9:"""
nomarr/workflows/navidrome/generate_static_playlist_wf.py:35:    """Generate a static M3U playlist from file IDs.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:36:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:37:    Resolves file IDs to library metadata (path, artist, title, duration)
nomarr/workflows/navidrome/generate_static_playlist_wf.py:38:    and generates M3U content with relative paths (relative to the library
nomarr/workflows/navidrome/generate_static_playlist_wf.py:39:    root resolved from the file records).
nomarr/workflows/navidrome/generate_static_playlist_wf.py:40:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:41:    When *m3u_output_path* is non-empty the M3U file is also written to
nomarr/workflows/navidrome/generate_static_playlist_wf.py:42:    ``{library_root}/{m3u_output_path}/{playlist_name}.m3u``.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:43:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:44:    Args:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:45:        db: Database instance for file lookup.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:46:        file_ids: List of library file document IDs (max 200).
nomarr/workflows/navidrome/generate_static_playlist_wf.py:47:        playlist_name: Name for the playlist header.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:48:        m3u_output_path: Sub-directory (relative to library root) for
nomarr/workflows/navidrome/generate_static_playlist_wf.py:49:            server-side M3U output.  Empty string disables file output.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:50:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:51:    Returns:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:52:        StaticPlaylistResult with M3U content, track count, missing IDs,
nomarr/workflows/navidrome/generate_static_playlist_wf.py:53:        and optionally the server-side save path.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:54:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:55:    Raises:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:56:        ValueError: If file_ids exceeds the 200 track limit.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:57:
nomarr/workflows/navidrome/generate_static_playlist_wf.py:58:    """
nomarr/workflows/library/scan_library_full_wf.py:66:    """Run a full library scan (ignores folder cache).
nomarr/workflows/library/scan_library_full_wf.py:67:
nomarr/workflows/library/scan_library_full_wf.py:68:    Walks every folder in the library regardless of cached mtime/file_count.
nomarr/workflows/library/scan_library_full_wf.py:69:    All files are re-examined for disk-level changes.
nomarr/workflows/library/scan_library_full_wf.py:70:
nomarr/workflows/library/scan_library_full_wf.py:71:    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
nomarr/workflows/library/scan_library_full_wf.py:72:    Pass 2: background tag extraction worker reads audio tags and seeds entities.
nomarr/workflows/library/scan_library_full_wf.py:73:
nomarr/workflows/library/scan_library_full_wf.py:74:    Args:
nomarr/workflows/library/scan_library_full_wf.py:75:        db: Database instance
nomarr/workflows/library/scan_library_full_wf.py:76:        library_id: Library document ``_id``
nomarr/workflows/library/scan_library_full_wf.py:77:        tagger_version: Model suite hash for version comparison
nomarr/workflows/library/scan_library_full_wf.py:78:        models_dir: Path to ML models (enables tag validation when provided)
nomarr/workflows/library/scan_library_full_wf.py:79:        namespace: Tag namespace (default ``"nom"``)
nomarr/workflows/library/scan_setup_wf.py:35:    """Validate a library and prepare it for scanning.
nomarr/workflows/library/scan_setup_wf.py:36:
nomarr/workflows/library/scan_setup_wf.py:37:    This workflow runs synchronously in the service layer before a scan
nomarr/workflows/library/scan_setup_wf.py:38:    workflow is dispatched as a background task.  Any error raised here
nomarr/workflows/library/scan_setup_wf.py:39:    is catchable at the HTTP layer.
nomarr/workflows/library/scan_setup_wf.py:40:
nomarr/workflows/library/scan_setup_wf.py:41:    Args:
nomarr/workflows/library/scan_setup_wf.py:42:        db: Database instance.
nomarr/workflows/library/scan_setup_wf.py:43:        library_id: Library document ``_id``.
nomarr/workflows/library/scan_setup_wf.py:44:        scan_type: ``"quick"`` or ``"full"`` (used only for logging).
nomarr/workflows/library/scan_setup_wf.py:45:
nomarr/workflows/library/scan_setup_wf.py:46:    Returns:
nomarr/workflows/library/scan_setup_wf.py:47:        The library document dict.
nomarr/workflows/library/scan_setup_wf.py:48:
nomarr/workflows/library/scan_setup_wf.py:49:    Raises:
nomarr/workflows/library/scan_setup_wf.py:50:        LibraryNotFoundError: If no library with the given ID exists.
nomarr/workflows/library/scan_setup_wf.py:51:        LibraryAlreadyScanningError: If the library is already being scanned.
nomarr/workflows/library/scan_setup_wf.py:52:
nomarr/workflows/library/scan_setup_wf.py:53:    """
nomarr/workflows/library/reconcile_paths_wf.py:23:    """Re-validate all library paths against current configuration.
nomarr/workflows/library/reconcile_paths_wf.py:24:
nomarr/workflows/library/reconcile_paths_wf.py:25:    This checks all files in the songs collection to detect paths that have
nomarr/workflows/library/reconcile_paths_wf.py:26:    become invalid due to config changes (library root moves, deletions, etc.).
nomarr/workflows/library/reconcile_paths_wf.py:27:    Useful after modifying library configurations or recovering from filesystem changes.
nomarr/workflows/library/reconcile_paths_wf.py:28:
nomarr/workflows/library/reconcile_paths_wf.py:29:    Args:
nomarr/workflows/library/reconcile_paths_wf.py:30:        db: Database instance
nomarr/workflows/library/reconcile_paths_wf.py:31:        library_id: Library document _id to scope reconciliation to
nomarr/workflows/library/reconcile_paths_wf.py:32:        library_root: Library root configuration (must be set)
nomarr/workflows/library/reconcile_paths_wf.py:33:        policy: What to do with invalid paths:
nomarr/workflows/library/reconcile_paths_wf.py:34:            - "dry_run": Only report, don't modify database
nomarr/workflows/library/validate_library_tags_wf.py:26:    """Validate per-file completeness of nom:* names for all discovered heads.
nomarr/workflows/library/validate_library_tags_wf.py:27:
nomarr/workflows/library/validate_library_tags_wf.py:28:    A file with a ``written`` edge is considered *complete* only if it has
nomarr/workflows/library/validate_library_tags_wf.py:29:    at least one tag edge for every discovered head (model_key + label) under
nomarr/workflows/library/validate_library_tags_wf.py:30:    the namespace.  Missing any head name marks the file incomplete.  Auto-repair
nomarr/workflows/library/validate_library_tags_wf.py:31:    removes the ``written`` edge so the file is rediscovered for tag writing.
nomarr/workflows/library/validate_library_tags_wf.py:32:    """
nomarr/workflows/library/scan_library_quick_wf.py:62:    """Run a quick (incremental) library scan.
nomarr/workflows/library/scan_library_quick_wf.py:63:
nomarr/workflows/library/scan_library_quick_wf.py:64:    Uses folder-level caching to skip unchanged folders.  Only folders
nomarr/workflows/library/scan_library_quick_wf.py:65:    whose mtime or file count changed since the last scan are walked.
nomarr/workflows/library/scan_library_quick_wf.py:66:
nomarr/workflows/library/scan_library_quick_wf.py:67:    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
nomarr/workflows/library/scan_library_quick_wf.py:68:    Pass 2: background tag extraction worker reads audio tags and seeds entities.
nomarr/workflows/library/scan_library_quick_wf.py:69:
nomarr/workflows/library/scan_library_quick_wf.py:70:    Args:
nomarr/workflows/library/scan_library_quick_wf.py:71:        db: Database instance
nomarr/workflows/library/scan_library_quick_wf.py:72:        library_id: Library document ``_id``
nomarr/workflows/library/scan_library_quick_wf.py:73:        tagger_version: Model suite hash for version comparison
nomarr/workflows/library/scan_library_quick_wf.py:74:
nomarr/workflows/library/scan_library_quick_wf.py:75:    Returns:
nomarr/workflows/library/scan_library_quick_wf.py:76:        Dict with scan statistics (files_discovered, files_added,
nomarr/workflows/library/scan_library_quick_wf.py:77:        files_updated, files_skipped, files_removed,
nomarr/workflows/library/scan_library_quick_wf.py:78:        files_failed, scan_duration_s, warnings, scan_id)
nomarr/workflows/library/scan_library_quick_wf.py:79:
nomarr/workflows/library/scan_library_quick_wf.py:80:    Raises:
nomarr/workflows/library/scan_library_quick_wf.py:81:        ValueError: If library not found
nomarr/workflows/library/scan_library_quick_wf.py:82:        OSError: If library root is inaccessible
nomarr/workflows/library/scan_library_quick_wf.py:83:
nomarr/workflows/library/scan_library_quick_wf.py:84:    """
nomarr/workflows/processing/process_file_wf.py:51:    """Run the full ML tagging pipeline for one audio file.
nomarr/workflows/processing/process_file_wf.py:52:
nomarr/workflows/processing/process_file_wf.py:53:    Validates the path, computes embeddings per backbone, runs all heads in parallel,
nomarr/workflows/processing/process_file_wf.py:54:    aggregates mood tiers, and optionally persists results to the database.
nomarr/workflows/processing/process_file_wf.py:55:
nomarr/workflows/processing/process_file_wf.py:56:    Args:
nomarr/workflows/processing/process_file_wf.py:57:        path: Path to the audio file.
nomarr/workflows/processing/process_file_wf.py:58:        config: Processing configuration (models_dir, namespace, tagger_version, etc.).
nomarr/workflows/processing/process_file_wf.py:59:        db: Database instance. Required for path resolution and metadata writes.
nomarr/workflows/processing/process_file_wf.py:60:        file_id: song document _id. Avoids path-based lookup when provided.
nomarr/workflows/processing/process_file_wf.py:61:        cache: ONNXModelCache instance. Required; auto-warmed if not already warm.
nomarr/workflows/processing/process_file_wf.py:62:
nomarr/workflows/processing/process_file_wf.py:63:    Returns:
nomarr/workflows/processing/process_file_wf.py:64:        ProcessFileResult with elapsed time, head outcomes, mood aggregations, and tags.
nomarr/workflows/processing/process_file_wf.py:65:
nomarr/workflows/processing/process_file_wf.py:66:    Raises:
nomarr/workflows/processing/process_file_wf.py:67:        ValueError: If path validation fails.
nomarr/workflows/processing/process_file_wf.py:68:        RuntimeError: If no heads are found or all heads fail.
nomarr/workflows/processing/process_file_wf.py:69:
nomarr/workflows/processing/process_file_wf.py:70:    """
nomarr/workflows/processing/write_file_tags_wf.py:135:    """
nomarr/workflows/processing/write_file_tags_wf.py:136:    try:
nomarr/workflows/processing/write_file_tags_wf.py:137:        # Get file document via component
nomarr/workflows/processing/write_file_tags_wf.py:138:        file_id, file_key, file_doc = get_file_for_writing(db, file_key)
nomarr/workflows/processing/write_file_tags_wf.py:139:
nomarr/workflows/processing/write_file_tags_wf.py:140:        if not file_doc:
nomarr/workflows/processing/write_file_tags_wf.py:141:            return WriteResult(
nomarr/workflows/processing/write_file_tags_wf.py:142:                file_key=file_key,
nomarr/workflows/processing/write_file_tags_wf.py:143:                tags_written=0,
nomarr/workflows/processing/write_file_tags_wf.py:144:                tags_filtered=0,
nomarr/workflows/processing/write_file_tags_wf.py:145:                success=False,
nomarr/workflows/processing/write_file_tags_wf.py:146:                error=f"File not found: {file_id}",
nomarr/app.py:326:                    logger.debug("[Application] File watchers synced with library collection")
nomarr/components/workers/worker_discovery_comp.py:55:    """Attempt to claim file for processing.
nomarr/components/workers/worker_discovery_comp.py:56:
nomarr/components/workers/worker_discovery_comp.py:57:    Uses deterministic key based on file id to enforce uniqueness.
nomarr/components/workers/worker_discovery_comp.py:58:    PostgreSQL unique constraint prevents duplicate claims.
nomarr/components/workers/worker_discovery_comp.py:59:
nomarr/components/workers/worker_discovery_comp.py:60:    Args:
nomarr/components/workers/worker_discovery_comp.py:61:        db: Database instance
nomarr/components/workers/worker_discovery_comp.py:62:        file_id: File document id (e.g., ``12345``)
nomarr/components/workers/worker_discovery_comp.py:63:        worker_id: Worker identifier (e.g., "worker:tag:0")
nomarr/components/workers/worker_discovery_comp.py:83:    """Release claim on file (after processing or error).
nomarr/components/workers/worker_discovery_comp.py:84:
nomarr/components/workers/worker_discovery_comp.py:85:    Args:
nomarr/components/workers/worker_discovery_comp.py:86:        db: Database instance
nomarr/components/workers/worker_discovery_comp.py:87:        file_id: File document id
nomarr/components/workers/worker_discovery_comp.py:88:
nomarr/components/workers/worker_discovery_comp.py:89:    """
nomarr/components/workers/worker_discovery_comp.py:99:    """Try to insert a claim, stealing it if the existing one is expired.
nomarr/components/workers/worker_discovery_comp.py:100:
nomarr/components/workers/worker_discovery_comp.py:101:    Args:
nomarr/components/workers/worker_discovery_comp.py:102:        db: Database handle.
nomarr/components/workers/worker_discovery_comp.py:103:        payload: Full claim document payload including ``key``, ``file_id``,
nomarr/components/workers/worker_discovery_comp.py:104:            ``worker_id``, and ``claimed_at``.
nomarr/components/workers/worker_discovery_comp.py:105:        now: Current timestamp in milliseconds.
nomarr/components/workers/worker_discovery_comp.py:106:        lease_ms: Claim lease duration in ms; existing claims older than this
nomarr/components/workers/worker_discovery_comp.py:107:            threshold are considered expired and may be stolen.
nomarr/components/workers/worker_discovery_comp.py:108:
nomarr/components/workers/worker_discovery_comp.py:109:    Returns:
nomarr/components/workers/worker_discovery_comp.py:110:        True if the claim was successfully inserted (new or stolen);
nomarr/components/workers/worker_discovery_comp.py:111:        False if an active un-expired claim already exists.
nomarr/components/workers/worker_discovery_comp.py:112:
nomarr/components/workers/worker_discovery_comp.py:113:    """
nomarr/components/tagging/tag_write_comp.py:18:    """Find or create one tag vertex and return its id."""
nomarr/components/tagging/tag_write_comp.py:104:    """Move song tag references from one tag vertex to another via library intents."""
nomarr/components/tagging/tag_query_comp.py:111:    """Get one tag document by ``id``."""
nomarr/components/tagging/tag_stats_comp.py:19:    """Return all library song documents across every library.
nomarr/components/tagging/tag_stats_comp.py:20:
nomarr/components/tagging/tag_stats_comp.py:21:    The intent-level facade has no global ``list_songs`` (song listing requires a
nomarr/components/tagging/tag_stats_comp.py:22:    ``library_id``), so a whole-collection listing is assembled by iterating the
nomarr/components/tagging/tag_stats_comp.py:23:    known libraries and collecting each library's songs. Behavior is equivalent
nomarr/components/tagging/tag_stats_comp.py:24:    to the pre-migration global ``count_files``/``list_files`` listing.
nomarr/components/tagging/tag_stats_comp.py:25:    """
nomarr/components/tagging/tag_stats_comp.py:33:    """Return song documents scoped to one library or the whole collection."""
nomarr/components/tagging/tag_stats_comp.py:63:    """Return ``tag_id -> song_count`` using one batched edge lookup."""
nomarr/components/tagging/tag_stats_comp.py:64:    valid_tag_ids = [tag_id for tag_id in tag_ids if isinstance(tag_id, int)]
nomarr/components/tagging/tag_stats_comp.py:65:    if not valid_tag_ids:
nomarr/components/tagging/tag_stats_comp.py:66:        return {}
nomarr/components/tagging/tag_stats_comp.py:67:
nomarr/components/tagging/tag_stats_comp.py:68:    count_by_tag_id = dict.fromkeys(valid_tag_ids, 0)
nomarr/components/tagging/tag_stats_comp.py:69:    for edge in _narrow_tag_list(
nomarr/components/tagging/tag_stats_comp.py:70:        db.library.list_song_tag_edges(valid_tag_ids),
nomarr/components/tagging/tag_stats_comp.py:71:    ):
nomarr/components/tagging/tag_stats_comp.py:72:        if isinstance(tag_id := edge.get("tag_id"), int) and tag_id in count_by_tag_id:
nomarr/components/tagging/tag_stats_comp.py:233:    """Return aggregate collection stats for the whole library or one library."""
nomarr/components/tagging/tag_stats_comp.py:255:    """Return year distribution rows for collection overview."""
nomarr/components/tagging/tag_stats_comp.py:306:    """Return genre distribution rows for collection overview."""
nomarr/components/ml/resources/ml_vram_probe_comp.py:1:"""Per-model VRAM probe component.
nomarr/components/ml/resources/ml_vram_probe_comp.py:2:
nomarr/components/ml/resources/ml_vram_probe_comp.py:3:Measures the actual VRAM consumed by each ONNX model on the current GPU and stores
nomarr/components/ml/resources/ml_vram_probe_comp.py:4:results in the ``meta`` collection as:
nomarr/components/ml/resources/ml_vram_probe_comp.py:5:
nomarr/components/ml/resources/ml_vram_probe_comp.py:6:    ``ml_model_vram:{model_path}`` -> bytes (str), or ``str(sys.maxsize)`` if not measured
nomarr/components/ml/resources/ml_vram_probe_comp.py:7:
nomarr/components/ml/resources/ml_vram_probe_comp.py:8:Design constraints:
nomarr/components/ml/resources/ml_vram_probe_comp.py:9:- Models are probed sequentially — only one session live at a time.
nomarr/components/ml/resources/ml_vram_probe_comp.py:10:- CUDA context is pre-warmed with a minimal identity model before any real
nomarr/components/ml/resources/ml_vram_probe_comp.py:11:  measurement, so context overhead (~400-600 MB) is not attributed to the
nomarr/components/ml/resources/ml_vram_probe_comp.py:12:  first backbone.
nomarr/components/ml/resources/ml_vram_probe_comp.py:13:- Measurements are stored in bytes — same unit as ``gpu_mem_limit`` in
nomarr/components/ml/resources/ml_vram_probe_comp.py:14:  the ONNX CUDAExecutionProvider options (Plan B consumer).
nomarr/components/ml/resources/ml_vram_probe_comp.py:15:- ``sys.maxsize`` means the model was not measured (GPU unavailable, load failed,
nomarr/components/ml/resources/ml_vram_probe_comp.py:16:  etc.) — the VRAM coordinator will naturally reject GPU placement for that model.
nomarr/components/ml/resources/ml_vram_probe_comp.py:17:"""
nomarr/components/ml/calibration/ml_calibration_state_comp.py:151:    """Delete one calibration state record and its edge."""
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:18:    """Find backbone IDs with pending hot vectors.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:19:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:20:    Enumerates backbones from the filesystem and checks each for a
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:21:    non-empty hot collection.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:22:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:23:    Args:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:24:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:25:        models_dir: Root directory containing model folders.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:26:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:27:    Returns:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:28:        List of backbone IDs where the hot collection exists and has at
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:29:        least one document.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:30:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:31:    """
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:46:    """Compute optimal HNSW ef_construction for a backbone.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:47:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:48:    Sums hot and cold counts to determine total document count, then
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:49:    derives the build-time HNSW parameter.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:50:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:51:    Args:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:52:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:53:        backbone_id: Backbone identifier.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:54:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:55:    Returns:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:56:        Optimal ef_construction value (100-500).
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:57:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:58:    """
nomarr/components/ml/vectors/ml_vector_registry_comp.py:21:    """Delete vectors for a song from every registered vector collection.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:22:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:23:    Args:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:24:        db: Database façade.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:25:        song_id: Document identifier used by registered vector namespaces.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:26:            Converted to ``int`` for the PostgreSQL API.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:27:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:28:    Returns:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:29:        Total number of vector documents deleted across all registered
nomarr/components/ml/vectors/ml_vector_registry_comp.py:30:        collections.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:31:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:32:    """
nomarr/components/ml/vectors/ml_vector_registry_comp.py:45:    """Delete vectors for multiple songs from every registered vector collection.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:46:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:47:    Args:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:48:        db: Database façade.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:49:        song_ids: Document identifiers used by registered vector namespaces.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:50:            Each value is converted to ``int`` for the PostgreSQL API.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:51:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:52:    Returns:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:53:        Total number of vector documents deleted across all registered
nomarr/components/ml/vectors/ml_vector_registry_comp.py:54:        collections.  Returns ``0`` if ``song_ids`` is empty.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:55:
nomarr/components/ml/vectors/ml_vector_registry_comp.py:56:    """
nomarr/components/ml/vectors/ml_vector_persist_comp.py:43:    """Upsert one pooled track vector into the active vector store.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:44:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:45:    Builds the hot vector document for the given song and model suite,
nomarr/components/ml/vectors/ml_vector_persist_comp.py:46:    replaces that song's vectors in the selected hot namespace through the
nomarr/components/ml/vectors/ml_vector_persist_comp.py:47:    normalized ``db.ml`` intent API, and returns the stored vector document id.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:48:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:49:    Args:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:50:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:51:        song_id: Library song document ``id``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:52:        backbone: Backbone model name used to select the hot vector namespace.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:53:        model_suite_hash: Hash of the model suite that produced the vector.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:54:        embed_dim: Embedding dimensionality of ``vector``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:55:        vector: Pooled track-level embedding vector.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:56:        num_segments: Number of source segments pooled into ``vector``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:57:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:58:    Returns:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:59:        The stored vector document ``id``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:60:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:61:    Raises:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:62:        RuntimeError: If the persisted vector cannot be reloaded after replacement.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:63:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:64:    """
nomarr/components/ml/vectors/ml_vector_persist_comp.py:104:    """Persist a pooled track-level embedding vector for one backbone.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:105:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:106:    Pools the segment-level embeddings, writes the result to the appropriate
nomarr/components/ml/vectors/ml_vector_persist_comp.py:107:    vector collection, and returns elapsed milliseconds.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:108:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:109:    Args:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:110:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:111:        song_id: song document id.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:112:        backbone: Backbone model name (used to select the vector collection).
nomarr/components/ml/vectors/ml_vector_persist_comp.py:113:        embeddings_2d: Shape ``[num_segments, embed_dim]`` backbone output.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:114:        model_suite_hash: Hash of the model suite used to produce the embeddings.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:115:        path: File path — used only for warning log messages on failure.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:116:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:117:    Returns:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:118:        Elapsed milliseconds on success, ``None`` on failure (warning logged).
nomarr/components/ml/vectors/ml_vector_persist_comp.py:119:
nomarr/components/ml/vectors/ml_vector_persist_comp.py:120:    """
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:19:    """Fetch a track's vector document from the cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:20:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:21:    Cold collections hold promoted, indexed vectors.  Hot collections are
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:22:    write-only (accumulation during ML processing) and must never be
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:23:    searched.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:24:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:25:    Uses per-backbone cold collections (cross-library).
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:26:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:27:    Args:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:28:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:29:        song_id: Library song document ``_id``.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:30:        backbone_id: Backbone identifier (e.g. ``"effnet"``).
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:31:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:32:    Returns:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:33:        Vector document dict (includes ``vector_n``, ``score``, etc.)
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:34:        or ``None`` if no promoted vector exists.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:35:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:36:    """
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:41:            "[vectors] Cold collection is empty for backbone=%s",
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:58:    """Run ANN similarity search against the promoted cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:59:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:60:    Searches the per-backbone cold vector namespace.  If the cold collection
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:61:    is empty, returns an empty result set and logs a debug message instead
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:62:    of issuing a search.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:63:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:64:    Args:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:65:        db: Database instance.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:66:        backbone_id: Backbone identifier used to select the cold namespace.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:67:        seed_vector: Query embedding vector used as the ANN search seed.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:68:        result_limit: Maximum number of similar vector documents to return.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:69:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:70:    Returns:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:71:        List of matching cold vector documents.  Returns an empty list when
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:72:        the promoted cold collection contains no documents.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:73:
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:74:    """
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:78:            "Skipping ANN search because cold collection is empty for backbone=%s",
nomarr/components/ml/onnx/ml_model_registry_comp.py:21:    """Return the stable document key used for one registered model path."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:26:    """Return the stable document key used for one model output vertex."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:31:    """Return every registered ML model document."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:37:    """Return the registered model document for ``path`` if present."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:54:    """Insert or update one registered model via constructor verbs.
nomarr/components/ml/onnx/ml_model_registry_comp.py:55:
nomarr/components/ml/onnx/ml_model_registry_comp.py:56:    Args:
nomarr/components/ml/onnx/ml_model_registry_comp.py:57:        db: Database instance
nomarr/components/ml/onnx/ml_model_registry_comp.py:58:        path: Model file path used as the registry identity.
nomarr/components/ml/onnx/ml_model_registry_comp.py:59:        backbone: Backbone name associated with the model.
nomarr/components/ml/onnx/ml_model_registry_comp.py:60:        head_type: Head type produced by the model.
nomarr/components/ml/onnx/ml_model_registry_comp.py:61:        model_stem: Stem name used to group related model artifacts.
nomarr/components/ml/onnx/ml_model_registry_comp.py:62:        output_count: Number of output vertices expected for the model.
nomarr/components/ml/onnx/ml_model_registry_comp.py:63:        source: Registration source label.
nomarr/components/ml/onnx/ml_model_registry_comp.py:64:        head_release_date: Release date recorded for the head artifact.
nomarr/components/ml/onnx/ml_model_registry_comp.py:65:        embedder_release_date: Release date recorded for the embedder artifact.
nomarr/components/ml/onnx/ml_model_registry_comp.py:66:
nomarr/components/ml/onnx/ml_model_registry_comp.py:67:    Returns:
nomarr/components/ml/onnx/ml_model_registry_comp.py:68:        Persisted ``ml_models`` document, including database fields such as
nomarr/components/ml/onnx/ml_model_registry_comp.py:69:        primary key plus the registered model metadata.
nomarr/components/ml/onnx/ml_model_registry_comp.py:70:
nomarr/components/ml/onnx/ml_model_registry_comp.py:71:    """
nomarr/components/ml/onnx/ml_model_registry_comp.py:106:            raise RuntimeError(f"Failed to load persisted ml_models document for path={path}")
nomarr/components/ml/onnx/ml_model_registry_comp.py:109:        msg = f"Failed to load persisted ml_models document for path={path}"
nomarr/components/ml/onnx/ml_model_registry_comp.py:144:    """Delete one registered model vertex by ID."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:180:    """Write label metadata for one output vertex."""
nomarr/components/metadata/metadata_cache_comp.py:1:"""Metadata cache rebuild component.
nomarr/components/metadata/metadata_cache_comp.py:2:
nomarr/components/metadata/metadata_cache_comp.py:3:Rebuilds derived song metadata fields from authoritative tags collection.
nomarr/components/metadata/metadata_cache_comp.py:4:Part of hybrid entity graph: tags are truth, embedded fields are read cache.
nomarr/components/metadata/metadata_cache_comp.py:5:"""
nomarr/components/metadata/metadata_cache_comp.py:38:    """Extract embedded cache fields from raw metadata.
nomarr/components/metadata/metadata_cache_comp.py:39:
nomarr/components/metadata/metadata_cache_comp.py:40:    Pure function — takes a metadata dict from tag parsing and returns only
nomarr/components/metadata/metadata_cache_comp.py:41:    the fields that belong on the song document's embedded cache.
nomarr/components/metadata/metadata_cache_comp.py:42:
nomarr/components/metadata/metadata_cache_comp.py:43:    Args:
nomarr/components/metadata/metadata_cache_comp.py:44:        metadata: Raw metadata key-value dict from tag extraction.
nomarr/components/metadata/metadata_cache_comp.py:45:
nomarr/components/metadata/metadata_cache_comp.py:46:    Returns:
nomarr/components/metadata/metadata_cache_comp.py:47:        Filtered dict with only cache-relevant fields.
nomarr/components/metadata/metadata_cache_comp.py:48:
nomarr/components/metadata/metadata_cache_comp.py:49:    """
nomarr/components/metadata/metadata_cache_comp.py:66:    """Write metadata cache fields to song documents in batch.
nomarr/components/metadata/metadata_cache_comp.py:67:
nomarr/components/metadata/metadata_cache_comp.py:68:    Each update dict must include a ``song_id`` key identifying the file
nomarr/components/metadata/metadata_cache_comp.py:69:    document, plus any of the recognised cache fields.
nomarr/components/metadata/metadata_cache_comp.py:70:
nomarr/components/metadata/metadata_cache_comp.py:71:    Args:
nomarr/components/metadata/metadata_cache_comp.py:72:        db: Database instance.
nomarr/components/metadata/metadata_cache_comp.py:73:        updates: List of ``{song_id, artist, artists, album, labels,
nomarr/components/metadata/metadata_cache_comp.py:74:            genres, year, ...}`` dicts to write.
nomarr/components/metadata/metadata_cache_comp.py:75:
nomarr/components/metadata/metadata_cache_comp.py:76:    """
nomarr/components/navidrome/playlist_builder_comp.py:1:"""Personal playlist builders from taste profiles and play history.
nomarr/components/navidrome/playlist_builder_comp.py:2:
nomarr/components/navidrome/playlist_builder_comp.py:3:Each public function builds one playlist type via ANN search against the
nomarr/components/navidrome/playlist_builder_comp.py:4:cold vector collection.  Builders return ``songs/id`` values;
nomarr/components/navidrome/playlist_builder_comp.py:5:nd_id resolution is the interface layer's responsibility.
nomarr/components/navidrome/playlist_builder_comp.py:6:"""
nomarr/components/navidrome/playlist_builder_comp.py:67:    """Run ANN search across every taste cluster and combine results deduplicated.
nomarr/components/navidrome/playlist_builder_comp.py:68:    Returns ``None`` only when every cluster search returned ``None`` (empty collection).
nomarr/components/navidrome/playlist_builder_comp.py:69:    Returns ``[]`` when searches ran but produced zero results.
nomarr/components/navidrome/playlist_builder_comp.py:70:    """
nomarr/components/library/work_status_comp.py:18:    """Shape of a library document consumed by ``compute_work_status``."""
nomarr/components/library/library_scan_file_ops_comp.py:44:    """Return the canonical folder document id for a library/path pair."""
nomarr/components/library/library_scan_file_ops_comp.py:54:    """Build the folder-cache document persisted for quick scans."""
nomarr/components/library/scan_lifecycle_comp.py:46:    """Return whether the library pipeline is currently in the scanning state.
nomarr/components/library/scan_lifecycle_comp.py:47:
nomarr/components/library/scan_lifecycle_comp.py:48:    Args:
nomarr/components/library/scan_lifecycle_comp.py:49:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:50:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:51:
nomarr/components/library/scan_lifecycle_comp.py:52:    Returns:
nomarr/components/library/scan_lifecycle_comp.py:53:        ``True`` when the library scan_state equals ``scanning``;
nomarr/components/library/scan_lifecycle_comp.py:54:        otherwise ``False``.
nomarr/components/library/scan_lifecycle_comp.py:55:
nomarr/components/library/scan_lifecycle_comp.py:56:    """
nomarr/components/library/scan_lifecycle_comp.py:65:    """Fetch a library document, raising if not found.
nomarr/components/library/scan_lifecycle_comp.py:66:
nomarr/components/library/scan_lifecycle_comp.py:67:    Args:
nomarr/components/library/scan_lifecycle_comp.py:68:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:69:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:70:
nomarr/components/library/scan_lifecycle_comp.py:71:    Returns:
nomarr/components/library/scan_lifecycle_comp.py:72:        ``LibraryDict`` domain object
nomarr/components/library/scan_lifecycle_comp.py:73:
nomarr/components/library/scan_lifecycle_comp.py:74:    Raises:
nomarr/components/library/scan_lifecycle_comp.py:75:        LibraryNotFoundError: If library not found
nomarr/components/library/scan_lifecycle_comp.py:76:
nomarr/components/library/scan_lifecycle_comp.py:77:    """
nomarr/components/library/scan_lifecycle_comp.py:93:    """Check whether a previous scan was interrupted.
nomarr/components/library/scan_lifecycle_comp.py:94:
nomarr/components/library/scan_lifecycle_comp.py:95:    Args:
nomarr/components/library/scan_lifecycle_comp.py:96:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:97:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:98:
nomarr/components/library/scan_lifecycle_comp.py:99:    Returns:
nomarr/components/library/scan_lifecycle_comp.py:100:        Tuple of (was_interrupted, scan_type).  *scan_type* is ``"quick"``
nomarr/components/library/scan_lifecycle_comp.py:140:    """Transition a library pipeline into the scanning state.
nomarr/components/library/scan_lifecycle_comp.py:141:
nomarr/components/library/scan_lifecycle_comp.py:142:    Args:
nomarr/components/library/scan_lifecycle_comp.py:143:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:144:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:145:
nomarr/components/library/scan_lifecycle_comp.py:146:    """
nomarr/components/library/scan_lifecycle_comp.py:189:    """Record that a scan has started.
nomarr/components/library/scan_lifecycle_comp.py:190:
nomarr/components/library/scan_lifecycle_comp.py:191:    Args:
nomarr/components/library/scan_lifecycle_comp.py:192:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:193:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:194:        scan_type: ``"quick"`` or ``"full"``
nomarr/components/library/scan_lifecycle_comp.py:208:    """Record that a scan has completed successfully.
nomarr/components/library/scan_lifecycle_comp.py:209:
nomarr/components/library/scan_lifecycle_comp.py:210:    Args:
nomarr/components/library/scan_lifecycle_comp.py:211:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:212:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:213:
nomarr/components/library/scan_lifecycle_comp.py:214:    """
nomarr/components/library/scan_lifecycle_comp.py:233:    """Update scan progress counters and/or status.
nomarr/components/library/scan_lifecycle_comp.py:234:
nomarr/components/library/scan_lifecycle_comp.py:235:    Only updates fields that are explicitly provided.
nomarr/components/library/scan_lifecycle_comp.py:236:
nomarr/components/library/scan_lifecycle_comp.py:237:    Args:
nomarr/components/library/scan_lifecycle_comp.py:238:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:239:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:240:        status: Scan status (``'idle'``, ``'scanning'``, ``'complete'``, ``'error'``)
nomarr/components/library/scan_lifecycle_comp.py:241:        progress: Files processed so far
nomarr/components/library/scan_lifecycle_comp.py:242:        total: Total files to scan
nomarr/components/library/scan_lifecycle_comp.py:243:        scan_error: Error message (only when ``status='error'``)
nomarr/components/library/scan_lifecycle_comp.py:244:
nomarr/components/library/scan_lifecycle_comp.py:245:    """
nomarr/components/library/scan_lifecycle_comp.py:260:    """Check whether a running scan has exceeded the timeout.
nomarr/components/library/scan_lifecycle_comp.py:261:
nomarr/components/library/scan_lifecycle_comp.py:262:    Args:
nomarr/components/library/scan_lifecycle_comp.py:263:        db: Database instance.
nomarr/components/library/scan_lifecycle_comp.py:264:        library_id: Library document ``id``.
nomarr/components/library/scan_lifecycle_comp.py:265:        timeout_ms: Maximum allowed duration in milliseconds (default 5 min).
nomarr/components/library/scan_lifecycle_comp.py:266:
nomarr/components/library/scan_lifecycle_comp.py:267:    Returns:
nomarr/components/library/scan_lifecycle_comp.py:268:        ``True`` when the library's scan_state is ``"scanning"`` and the
nomarr/components/library/scan_lifecycle_comp.py:291:    """Transition pipeline state after scan completion based on file count.
nomarr/components/library/scan_lifecycle_comp.py:292:
nomarr/components/library/scan_lifecycle_comp.py:293:    If the library contains files, transitions the ml axis to ``ML_IN_PROGRESS``.
nomarr/components/library/scan_lifecycle_comp.py:294:    Otherwise transitions to ``ML_NOT_PROCESSED``.
nomarr/components/library/scan_lifecycle_comp.py:295:
nomarr/components/library/scan_lifecycle_comp.py:296:    Args:
nomarr/components/library/scan_lifecycle_comp.py:297:        db: Database instance
nomarr/components/library/scan_lifecycle_comp.py:298:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:299:
nomarr/components/library/scan_lifecycle_comp.py:300:    """
nomarr/components/library/file_batch_scanner_comp.py:25:    """Result of scanning a single folder."""
nomarr/components/library/file_batch_scanner_comp.py:26:
nomarr/components/library/file_batch_scanner_comp.py:27:    file_entries: list[dict[str, Any]]  # Ready for DB upsert (no state fields)
nomarr/components/library/file_batch_scanner_comp.py:28:    discovered_paths: set[str]  # All paths found
nomarr/components/library/file_batch_scanner_comp.py:29:    new_file_paths: set[str]  # Paths that are new (not in existing_files)
nomarr/components/library/file_batch_scanner_comp.py:30:    stats: dict[str, int]  # files_updated, files_failed, files_skipped
nomarr/components/library/file_batch_scanner_comp.py:31:    warnings: list[str]
nomarr/components/library/file_batch_scanner_comp.py:32:    edge_bootstraps: list[dict[str, Any]] = field(default_factory=list)  # Post-upsert edge creation metadata
nomarr/components/library/file_batch_scanner_comp.py:33:
nomarr/components/library/file_batch_scanner_comp.py:34:
nomarr/components/library/file_batch_scanner_comp.py:35:def scan_folder_files(
nomarr/components/library/file_batch_scanner_comp.py:36:    folder_path: Path,
nomarr/components/library/file_batch_scanner_comp.py:37:    library_root: Path,
nomarr/components/library/file_batch_scanner_comp.py:38:    library_id: str,
nomarr/components/library/file_batch_scanner_comp.py:39:    existing_files: dict[str, dict],
nomarr/components/library/file_batch_scanner_comp.py:40:    tagger_version: str,
nomarr/components/library/file_batch_scanner_comp.py:41:    db: Database,
nomarr/components/library/file_batch_scanner_comp.py:42:) -> FileBatchResult:
nomarr/components/library/file_batch_scanner_comp.py:43:    """Scan all files in a single folder and return batch-ready data.
nomarr/components/library/library_id_comp.py:1:"""Library ID normalization helpers.
nomarr/components/library/library_id_comp.py:2:
nomarr/components/library/library_id_comp.py:3:Shared utility functions for converting between bare library keys and full
nomarr/components/library/library_id_comp.py:4:``libraries/{key}`` document ids. Kept in a leaf module so that all other
nomarr/components/library/library_id_comp.py:5:library components can import from here without creating circular dependencies.
nomarr/components/library/library_id_comp.py:6:"""
nomarr/components/library/library_song_query_comp.py:24:    """Get one library-song document by ``id``."""
nomarr/components/library/library_song_query_comp.py:123:    """Return song docs across all libraries.
nomarr/components/library/library_song_query_comp.py:124:
nomarr/components/library/library_song_query_comp.py:125:    The intent-level facade has no global ``list_songs`` (song listing requires a
nomarr/components/library/library_song_query_comp.py:126:    ``library_id``), so a whole-collection listing is assembled by iterating the
nomarr/components/library/library_song_query_comp.py:127:    known libraries and collecting each library's songs, then applying the cap.
nomarr/components/library/library_song_query_comp.py:128:    """
nomarr/components/library/library_song_query_comp.py:242:    edges = cast("list[dict[str, Any]]", db.library.list_song_tag_edges(list(tag_ids)))
nomarr/components/library/library_song_query_comp.py:243:    return {edge["song_id"] for edge in edges if isinstance(edge.get("song_id"), int)}
nomarr/components/library/library_song_query_comp.py:262:    """Get a library-song document by normalized or absolute path.
nomarr/components/library/library_song_query_comp.py:263:
nomarr/components/library/library_song_query_comp.py:264:    TODO(migrate): library_id branch fetches all library songs into Python then
nomarr/components/library/library_song_query_comp.py:265:    filters by path. Replace with db.library.get_song_by_path(path, library_id)
nomarr/components/library/library_song_query_comp.py:266:    once that method supports normalized_path lookup in addition to raw path.
nomarr/components/library/library_song_query_comp.py:267:    """
nomarr/components/library/library_song_query_comp.py:683:        for song_id in db.library.list_library_song_ids(lib["id"], limit=None):
nomarr/components/library/library_song_query_comp.py:684:            delete_output_streams(db, song_id)
nomarr/components/library/library_song_query_comp.py:685:    # Link/junction tables
nomarr/components/library/library_song_query_comp.py:686:    db.library.truncate_song_tag_edges()
nomarr/components/library/library_song_query_comp.py:687:    db.app.truncate_song_state_edges()
nomarr/components/library/library_song_query_comp.py:688:    db.library.truncate_song_links()
nomarr/components/library/library_song_query_comp.py:689:    db.library.truncate_folder_links()
nomarr/components/library/library_song_query_comp.py:690:    # Core tables
nomarr/components/library/library_song_query_comp.py:691:    db.library.truncate_tags()
nomarr/components/library/library_song_query_comp.py:692:    db.library.truncate_songs()
nomarr/components/library/library_song_query_comp.py:693:    db.library.truncate_folders()
nomarr/components/library/library_song_query_comp.py:694:    db.library.truncate_scan_records()
nomarr/components/library/library_song_query_comp.py:695:    # Pipeline states live in the `pipeline_states` rows table (scan_state, ml_state, etc.),
nomarr/components/library/library_song_query_comp.py:696:    # not as fields on library documents. They are not reset here: this clear wipes
nomarr/components/library/library_song_query_comp.py:697:    # song/tag/folder/scan-record/edge/vector data and output streams, leaving
nomarr/components/library/library_song_query_comp.py:698:    # pipeline-state rows intact.
nomarr/components/library/library_song_query_comp.py:699:
nomarr/components/library/library_song_query_comp.py:700:
nomarr/components/library/library_song_query_comp.py:701:def search_songs_by_tag(
nomarr/components/library/library_song_query_comp.py:702:    db: Database,
nomarr/components/library/library_song_query_comp.py:703:    tag_key: str,
nomarr/components/library/library_song_query_comp.py:704:    target_value: float | str,
nomarr/components/library/library_song_query_comp.py:705:    limit: int = 100,
nomarr/components/library/library_song_query_comp.py:706:    offset: int = 0,
nomarr/components/library/library_song_query_comp.py:707:) -> list[dict[str, Any]]:
nomarr/components/library/library_song_query_comp.py:708:    """Search songs by tag value with numeric-distance or exact-match semantics."""
nomarr/components/library/library_song_query_comp.py:723:            "list[dict[str, Any]]",
nomarr/components/library/library_song_query_comp.py:724:            db.library.list_song_tag_edges(list(tag_value_by_id.keys()), limit=DEFAULT_LIMIT),
nomarr/components/library/library_song_query_comp.py:725:        )
nomarr/components/library/library_song_query_comp.py:726:        best_match_by_song_id: dict[int, dict[str, Any]] = {}
nomarr/components/library/library_song_query_comp.py:727:        for edge in edges:
nomarr/components/library/library_song_query_comp.py:728:            song_id = edge.get("song_id")
nomarr/components/library/library_song_query_comp.py:729:            tag_id = edge.get("tag_id")
nomarr/components/library/library_song_query_comp.py:800:    edges = cast("list[dict[str, Any]]", db.library.list_song_tag_edges(tag_ids))
nomarr/components/library/library_song_query_comp.py:801:    return len({edge["song_id"] for edge in edges if isinstance(edge.get("song_id"), (int, str))})
nomarr/components/library/move_detection_comp.py:150:                removed_chromaprint = removed_file.get("chromaprint")
nomarr/components/library/move_detection_comp.py:151:                if new_chromaprint and removed_chromaprint and removed_chromaprint == new_chromaprint:
nomarr/components/library/move_detection_comp.py:152:                    # Chromaprint matches - verify duration to catch edge cases
nomarr/components/library/move_detection_comp.py:153:                    removed_duration = removed_file.get("duration_seconds")
nomarr/components/library/library_records_comp.py:1:"""Library document composition helpers."""
nomarr/components/library/library_records_comp.py:33:    """Insert a library document.
nomarr/components/library/library_records_comp.py:34:
nomarr/components/library/library_records_comp.py:35:    Raises ValueError if watch_mode or file_write_mode is invalid.
nomarr/components/library/library_records_comp.py:36:    """
nomarr/components/library/library_records_comp.py:109:    """Update a library document by ``id`` through the constructor namespace."""
nomarr/components/library/library_records_comp.py:146:    """Return all library document keys for bootstrap-style callers."""
nomarr/components/library/library_records_comp.py:201:    """Merge library scan state into a library document for API compatibility."""
nomarr/components/library/library_song_state_comp.py:1:"""Library song state helpers extracted from legacy persistence mixins."""
nomarr/components/library/library_song_state_comp.py:2:
nomarr/components/library/library_song_state_comp.py:3:from __future__ import annotations
nomarr/components/library/library_song_state_comp.py:4:
nomarr/components/library/library_song_state_comp.py:5:import contextlib
nomarr/components/library/library_song_state_comp.py:6:import logging
nomarr/components/library/library_song_state_comp.py:7:from collections import defaultdict
nomarr/components/library/library_song_state_comp.py:8:from typing import TYPE_CHECKING, Any
nomarr/components/library/library_song_state_comp.py:9:
nomarr/components/library/library_song_state_comp.py:10:from nomarr.helpers.constants.file_states import (
nomarr/components/library/library_song_state_comp.py:11:    ALL_STATE_VERTICES,
nomarr/components/library/library_song_state_comp.py:12:    AXIS_PAIRS,
nomarr/components/library/library_song_state_comp.py:13:    STATE_CALIBRATED,
nomarr/components/library/library_song_state_comp.py:14:    STATE_ERRORED,
nomarr/components/library/library_song_state_comp.py:15:    STATE_HYDRATED,
nomarr/components/library/library_song_state_comp.py:16:    STATE_NOT_CALIBRATED,
nomarr/components/library/library_song_state_comp.py:17:    STATE_NOT_HYDRATED,
nomarr/components/library/library_song_state_comp.py:18:    STATE_NOT_PROCESSED,
nomarr/components/library/library_song_state_comp.py:19:    STATE_NOT_VECTORS_EXTRACTED,
nomarr/components/library/library_song_state_comp.py:20:    STATE_NOT_WRITTEN,
nomarr/components/library/library_song_state_comp.py:21:    STATE_PROCESSED,
nomarr/components/library/library_song_state_comp.py:22:    STATE_TAGS_CURRENT,
nomarr/components/library/library_song_state_comp.py:23:    STATE_TAGS_NOT_FRESH,
nomarr/components/library/library_song_state_comp.py:24:    STATE_VECTORS_EXTRACTED,
nomarr/components/library/library_song_state_comp.py:25:    STATE_WRITTEN,
nomarr/components/library/library_song_state_comp.py:26:)
nomarr/components/library/library_song_state_comp.py:27:from nomarr.helpers.exceptions import DuplicateEntityError
nomarr/components/library/library_song_state_comp.py:28:
nomarr/components/library/library_song_state_comp.py:29:if TYPE_CHECKING:
nomarr/components/library/library_song_state_comp.py:30:    from nomarr.persistence.db import Database
nomarr/components/library/library_song_state_comp.py:31:
nomarr/components/library/library_song_state_comp.py:32:logger = logging.getLogger(__name__)
nomarr/components/library/library_song_state_comp.py:33:
nomarr/components/library/library_song_state_comp.py:34:
nomarr/components/library/library_song_state_comp.py:35:# Build reverse lookup: given (from_vertex, to_vertex), verify the pair belongs to the same axis.
nomarr/components/library/library_song_state_comp.py:36:_VALID_TRANSITIONS: set[tuple[str, str]] = set()
nomarr/components/library/library_song_state_comp.py:37:for _positive, _negative in AXIS_PAIRS.values():
nomarr/components/library/library_song_state_comp.py:38:    _VALID_TRANSITIONS.add((_positive, _negative))
nomarr/components/library/library_song_state_comp.py:39:    _VALID_TRANSITIONS.add((_negative, _positive))
nomarr/components/library/library_song_state_comp.py:40:
nomarr/components/library/library_song_state_comp.py:41:# The 8 negative poles are the second element of each axis pair. Deriving them
nomarr/components/library/library_song_state_comp.py:42:# from AXIS_PAIRS (rather than a ``not_`` name prefix) is required because one
nomarr/components/library/library_song_state_comp.py:43:# negative pole (``tags_not_fresh``) is not ``not_``-prefixed and would be
nomarr/components/library/library_song_state_comp.py:44:# missed by a prefix check (AR-SDR-6 stripped the legacy doc-collection
nomarr/components/library/library_song_state_comp.py:45:# prefix from these bare constants).
nomarr/components/library/library_song_state_comp.py:46:_NEGATIVE_STATE_VERTICES: frozenset[str] = frozenset(neg for _, neg in AXIS_PAIRS.values())
nomarr/components/library/library_song_state_comp.py:47:
nomarr/components/library/library_song_state_comp.py:48:
nomarr/components/library/library_song_state_comp.py:49:def transition_song_state(db: Database, song_ids: list[int], from_state: str, to_state: str) -> None:
nomarr/components/library/library_song_state_comp.py:50:    """Transition songs between boolean state vertices with axis-pair validation.
nomarr/components/library/library_song_state_comp.py:122:    """Return the current state memberships for the given song IDs.
nomarr/components/library/library_song_state_comp.py:123:
nomarr/components/library/library_song_state_comp.py:124:    Uses a single targeted edge-traversal query — no full state scan,
nomarr/components/library/library_song_state_comp.py:125:    no document fetch.
nomarr/components/library/library_song_state_comp.py:126:    """
nomarr/components/library/library_song_state_comp.py:333:    """Return whether one song currently has the tagged-state edge."""
nomarr/components/library/library_song_state_comp.py:425:    """Transition all library songs needing it to not_hydrated, forcing re-hydration.
nomarr/components/library/library_song_state_comp.py:426:
nomarr/components/library/library_song_state_comp.py:427:    Songs can exist without any hydration-state edge at all (hydration axis
nomarr/components/library/library_song_state_comp.py:428:    was introduced after initial scan).  This function handles three cases:
nomarr/components/library/library_song_state_comp.py:429:      - already hydrated  → transition to not_hydrated
nomarr/components/library/library_song_state_comp.py:430:      - no hydration edge → add        not_hydrated edge
nomarr/components/library/library_song_state_comp.py:431:      - already not_hydrated → no-op
nomarr/components/library/library_song_state_comp.py:432:
nomarr/components/library/library_song_state_comp.py:433:    Returns the number of songs that were changed.
nomarr/components/library/library_song_state_comp.py:434:    """
nomarr/components/library/library_scan_state_comp.py:1:"""Pipeline and scan state management for library scans.
nomarr/components/library/library_scan_state_comp.py:2:
nomarr/components/library/library_scan_state_comp.py:3:Extracted from ``scan_lifecycle_comp`` — owns scan-document read/write and
nomarr/components/library/library_scan_state_comp.py:4:pipeline-axis transition logic.
nomarr/components/library/library_scan_state_comp.py:5:"""
nomarr/components/library/library_scan_state_comp.py:53:    """Return the canonical scan document id for a library."""
nomarr/components/library/library_scan_state_comp.py:58:    """Build the canonical default scan document payload."""
nomarr/components/library/library_scan_state_comp.py:67:    """Return the scan document for a library, creating it when missing."""
nomarr/components/library/library_scan_state_comp.py:79:    """Return the scan document for a library, or None when no scan exists."""
nomarr/components/library/library_song_mutation_comp.py:31:    """Insert or update a library-song document and its ownership/state edges.
nomarr/components/library/library_song_mutation_comp.py:32:
nomarr/components/library/library_song_mutation_comp.py:33:    Raises ValueError if the path is not valid.
nomarr/components/library/library_song_mutation_comp.py:34:    """
nomarr/components/library/library_song_mutation_comp.py:58:    """Delete a library-song document and its edges.
nomarr/components/library/library_song_mutation_comp.py:59:
nomarr/components/library/library_song_mutation_comp.py:60:    Accepts a song ID (integer) or a raw file path (resolved via path lookup).
nomarr/components/library/library_song_mutation_comp.py:61:    No-op if the file is not found.
nomarr/components/library/library_song_mutation_comp.py:62:    """
nomarr/components/library/library_song_mutation_comp.py:133:    """Delete multiple library-song documents by path.
nomarr/components/library/library_song_mutation_comp.py:134:
nomarr/components/library/library_song_mutation_comp.py:135:    Silently skips paths with no matching document. Returns the number deleted.
nomarr/components/library/library_song_mutation_comp.py:136:    """
nomarr/components/library/reconcile_paths_comp.py:1:"""Component for reconciling library paths after configuration changes.
nomarr/components/library/reconcile_paths_comp.py:2:
nomarr/components/library/reconcile_paths_comp.py:3:This component re-validates all paths in the songs collection against
nomarr/components/library/reconcile_paths_comp.py:4:the current library configuration. It detects paths that have become invalid
nomarr/components/library/reconcile_paths_comp.py:5:due to config changes (library root moves, library deletions, etc.).
nomarr/components/library/reconcile_paths_comp.py:6:"""
nomarr/components/library/reconcile_paths_comp.py:30:    """Re-validate all library paths against current configuration.
nomarr/components/library/reconcile_paths_comp.py:31:
nomarr/components/library/reconcile_paths_comp.py:32:    This component scans the songs collection and re-validates each path
nomarr/components/library/reconcile_paths_comp.py:33:    using build_library_path_from_db() to check against current config.
nomarr/components/library/reconcile_paths_comp.py:34:    Useful after library root changes or library deletions.
nomarr/components/library/reconcile_paths_comp.py:35:
nomarr/components/library/reconcile_paths_comp.py:36:    Args:
nomarr/components/library/reconcile_paths_comp.py:37:        db: Database instance
nomarr/components/library/reconcile_paths_comp.py:38:        library_id: Library document _id to scope reconciliation to
nomarr/components/library/reconcile_paths_comp.py:39:        policy: What to do with invalid paths:
nomarr/components/library/reconcile_paths_comp.py:40:            - "dry_run": Only report, don't modify database
nomarr/components/analytics/collection_overview_comp.py:29:    """Get collection overview: library stats, year/genre distributions.
nomarr/components/analytics/collection_overview_comp.py:30:
nomarr/components/analytics/collection_overview_comp.py:31:    Args:
nomarr/components/analytics/collection_overview_comp.py:32:        db: Database instance.
nomarr/components/analytics/collection_overview_comp.py:33:        library_id: Optional library id to filter by.
nomarr/components/analytics/collection_overview_comp.py:34:
nomarr/components/analytics/collection_overview_comp.py:35:    """
nomarr/components/processing/file_write_comp.py:36:    """Normalise *file_key* and fetch the library-file document.
nomarr/components/processing/file_write_comp.py:37:
nomarr/components/processing/file_write_comp.py:38:    Returns:
nomarr/components/processing/file_write_comp.py:39:        (file_id, file_key, file_doc) — *file_doc* is ``None`` when the
nomarr/components/processing/file_write_comp.py:40:        document does not exist.
nomarr/components/processing/file_write_comp.py:41:
nomarr/components/processing/file_write_comp.py:42:    """
nomarr/components/processing/file_write_comp.py:128:    """Write mood tags for multiple files via constructor-backed verbs.
nomarr/components/processing/file_write_comp.py:129:
nomarr/components/processing/file_write_comp.py:130:    Delegates to ``set_song_tags_batch`` which performs component-layer
nomarr/components/processing/file_write_comp.py:131:    coordination: edge discovery per ``(song_id, name)`` pair, targeted edge
nomarr/components/processing/file_write_comp.py:132:    deletion, tag upsert per unique ``(name, value)`` pair, and bulk edge
nomarr/components/processing/file_write_comp.py:133:    insert.  Query count scales with the number of files and distinct tag
nomarr/components/processing/file_write_comp.py:134:    values.
nomarr/components/processing/file_write_comp.py:135:
nomarr/components/processing/file_write_comp.py:136:    Args:
nomarr/components/processing/file_write_comp.py:137:        db: Database instance
nomarr/components/processing/file_write_comp.py:138:        items: List of (file_id, mood_tags) tuples
nomarr/components/processing/file_write_comp.py:139:
nomarr/components/processing/file_write_comp.py:140:    Returns:
nomarr/components/processing/file_write_comp.py:141:        Number of (file_id, name) pairs written
nomarr/components/processing/file_write_comp.py:142:
nomarr/components/processing/file_write_comp.py:143:    """
nomarr/components/infrastructure/path_comp.py:109:    """Build LibraryPath from database-stored path.
nomarr/components/infrastructure/path_comp.py:110:
nomarr/components/infrastructure/path_comp.py:111:    This is used when reading paths from queue tables, the file collection, etc.
nomarr/components/infrastructure/path_comp.py:112:    The stored path may be absolute or relative depending on storage format.
nomarr/components/infrastructure/path_comp.py:113:
nomarr/components/infrastructure/path_comp.py:114:    This function re-validates stored paths against the CURRENT configuration,
nomarr/components/infrastructure/path_comp.py:115:    detecting cases where config has changed (library root moved/changed).
nomarr/components/infrastructure/path_comp.py:116:
nomarr/components/infrastructure/path_comp.py:117:    Args:
nomarr/components/infrastructure/path_comp.py:118:        stored_path: Path as stored in database (may be relative or absolute)
nomarr/components/infrastructure/path_comp.py:119:        db: Database instance to look up current library configuration
nomarr/components/infrastructure/path_comp.py:120:        library_id: Optional library ID if known from DB join
nomarr/components/infrastructure/path_comp.py:121:        check_disk: Whether to check if file exists (default: True)
nomarr/components/infrastructure/path_comp.py:122:
nomarr/components/infrastructure/path_comp.py:123:    Returns:
nomarr/components/infrastructure/path_comp.py:124:        LibraryPath with status reflecting current config validity
nomarr/components/infrastructure/path_comp.py:125:
nomarr/components/infrastructure/path_comp.py:126:    """
nomarr/services/infrastructure/ml_svc.py:140:        """Write a human-readable label for a model output vertex.
nomarr/services/infrastructure/ml_svc.py:141:
nomarr/services/infrastructure/ml_svc.py:142:        Args:
nomarr/services/infrastructure/ml_svc.py:143:            model_id: Model identifier (e.g., 'effnet-v1' or int DB key).
nomarr/services/infrastructure/ml_svc.py:144:            output_id: Output identifier string or int DB key.
nomarr/services/infrastructure/ml_svc.py:145:            label: Human-readable tag label for this activation.
nomarr/services/infrastructure/ml_svc.py:146:
nomarr/services/infrastructure/ml_svc.py:147:        """
nomarr/services/infrastructure/ml_svc.py:151:        """Set the fully_configured flag on a model vertex.
nomarr/services/infrastructure/ml_svc.py:152:
nomarr/services/infrastructure/ml_svc.py:153:        Args:
nomarr/services/infrastructure/ml_svc.py:154:            model_id: Model identifier (e.g., 'effnet-v1' or int DB key).
nomarr/services/infrastructure/ml_svc.py:155:            value: True to enable model for inference, False to disable.
nomarr/services/infrastructure/ml_svc.py:156:
nomarr/services/infrastructure/ml_svc.py:157:        """
nomarr/services/infrastructure/file_watcher_svc.py:201:        """Sync watchers with the library collection (DB is source of truth).
nomarr/services/infrastructure/file_watcher_svc.py:202:
nomarr/services/infrastructure/file_watcher_svc.py:203:        - Starts watchers for libraries in DB with watch_mode != 'off'
nomarr/services/infrastructure/file_watcher_svc.py:204:        - Stops watchers for libraries no longer in DB or with watch_mode == 'off'
nomarr/services/infrastructure/file_watcher_svc.py:205:
nomarr/services/infrastructure/file_watcher_svc.py:206:        Should be called on startup and can be called periodically if needed.
nomarr/services/infrastructure/file_watcher_svc.py:207:        """
nomarr/services/domain/vector_maintenance_svc.py:133:        """Calculate optimal HNSW ef_construction for vector index based on document count.
nomarr/services/domain/vector_maintenance_svc.py:134:
nomarr/services/domain/vector_maintenance_svc.py:135:        Delegates to :func:`~nomarr.helpers.vector_params_helper.get_ef_construction`
nomarr/services/domain/vector_maintenance_svc.py:136:        which scales the build-time parameter by collection size.
nomarr/services/domain/vector_maintenance_svc.py:137:
nomarr/services/domain/vector_maintenance_svc.py:138:        Args:
nomarr/services/domain/vector_maintenance_svc.py:139:            doc_count: Total number of documents
nomarr/services/domain/vector_maintenance_svc.py:140:
nomarr/services/domain/vector_maintenance_svc.py:141:        Returns:
nomarr/services/domain/vector_maintenance_svc.py:142:            Optimal ef_construction value (100-500)
nomarr/services/domain/vector_maintenance_svc.py:143:
nomarr/services/domain/vector_maintenance_svc.py:144:        """
nomarr/services/domain/vector_search_svc.py:42:        """Search for similar tracks using vector similarity.
nomarr/services/domain/vector_search_svc.py:43:
nomarr/services/domain/vector_search_svc.py:44:        Resolves the source track's vector from ``file_id``, then performs a
nomarr/services/domain/vector_search_svc.py:45:        single ANN query against the per-backbone cold collection. Cross-library
nomarr/services/domain/vector_search_svc.py:46:        search is the default (collections are per-backbone, not per-library).
nomarr/services/domain/vector_search_svc.py:47:
nomarr/services/domain/vector_search_svc.py:48:        Args:
nomarr/services/domain/vector_search_svc.py:49:            file_id: Library file document ID to find similar tracks for.
nomarr/services/domain/vector_search_svc.py:50:            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
nomarr/services/domain/vector_search_svc.py:51:            limit: Maximum number of results
nomarr/services/domain/vector_search_svc.py:52:            min_score: Minimum cosine similarity threshold (0-1). Results below
nomarr/services/domain/vector_search_svc.py:53:                this value are filtered out.
nomarr/services/domain/vector_search_svc.py:54:            nprobe: Centroids to probe per query. When ``None`` (default),
nomarr/services/domain/vector_search_svc.py:55:                auto-calculated from ``vector_group_size`` and
nomarr/services/domain/vector_search_svc.py:56:                ``vector_search_thoroughness`` in dynamic config.
nomarr/services/domain/vector_search_svc.py:57:                Pass an explicit int to override.
nomarr/services/domain/vector_search_svc.py:58:
nomarr/services/domain/vector_search_svc.py:59:        Returns:
nomarr/services/domain/vector_search_svc.py:60:            List of matching results with keys:
nomarr/services/domain/vector_search_svc.py:61:                - file_id: Library file document ID
nomarr/services/domain/vector_search_svc.py:62:                - score: Cosine similarity (0-1, higher = more similar)
nomarr/services/domain/vector_search_svc.py:63:                - vector: The stored embedding vector
nomarr/services/domain/vector_search_svc.py:64:                - Other document fields
nomarr/services/domain/vector_search_svc.py:65:
nomarr/services/domain/vector_search_svc.py:66:        Raises:
nomarr/services/domain/vector_search_svc.py:67:            ValueError: If file not found, no vector exists, or cold collection
nomarr/services/domain/vector_search_svc.py:68:                has no vector index.
nomarr/services/domain/vector_search_svc.py:69:            RuntimeError: If search query fails
nomarr/services/domain/vector_search_svc.py:70:
nomarr/services/domain/vector_search_svc.py:71:        """
nomarr/services/domain/vector_search_svc.py:72:        # Step 1: Get the source track's vector from the per-backbone cold collection
nomarr/services/domain/vector_search_svc.py:73:        vector_doc = get_cold_track_vector(self.db, file_id, backbone_id)
nomarr/services/domain/vector_search_svc.py:74:        if vector_doc is None:
nomarr/services/domain/vector_search_svc.py:75:            msg = (
nomarr/services/domain/vector_search_svc.py:76:                f"No vector found for file '{file_id}' with backbone "
nomarr/services/domain/vector_search_svc.py:80:        vector: list[float] = vector_doc["vector_n"]
nomarr/services/domain/vector_search_svc.py:81:
nomarr/services/domain/vector_search_svc.py:82:        # Step 2: Single ANN search on per-backbone cold collection
nomarr/services/domain/vector_search_svc.py:83:        raw_results = search_similar_cold_track_vectors(
nomarr/services/domain/vector_search_svc.py:84:            db=self.db,
nomarr/services/domain/vector_search_svc.py:85:            backbone_id=backbone_id,
nomarr/services/domain/vector_search_svc.py:86:            seed_vector=vector,
nomarr/services/domain/vector_search_svc.py:87:            result_limit=limit,
nomarr/services/domain/vector_search_svc.py:88:        )
nomarr/services/domain/vector_search_svc.py:89:
nomarr/services/domain/vector_search_svc.py:90:        # Apply min_score filtering
nomarr/services/domain/vector_search_svc.py:91:        filtered_results = [result for result in raw_results if result.get("score", 0.0) >= min_score]
nomarr/services/domain/vector_search_svc.py:101:        """Get vector for a specific track.
nomarr/services/domain/vector_search_svc.py:102:
nomarr/services/domain/vector_search_svc.py:103:        Delegates to the get_track_vector workflow, which fetches from the
nomarr/services/domain/vector_search_svc.py:104:        per-backbone cold collection directly (no library resolution needed).
nomarr/services/domain/vector_search_svc.py:105:
nomarr/services/domain/vector_search_svc.py:106:        Args:
nomarr/services/domain/vector_search_svc.py:107:            backbone_id: Backbone identifier
nomarr/services/domain/vector_search_svc.py:108:            file_id: Library file document ID
nomarr/services/domain/vector_search_svc.py:109:
nomarr/services/domain/vector_search_svc.py:110:        Returns:
nomarr/services/domain/vector_search_svc.py:111:            Vector document or None if not found
nomarr/services/domain/vector_search_svc.py:112:
nomarr/services/domain/vector_search_svc.py:113:        """
nomarr/services/domain/library_svc/songs.py:109:        """Re-validate all library paths against current configuration.
nomarr/services/domain/library_svc/songs.py:110:
nomarr/services/domain/library_svc/songs.py:111:        This checks all files in the songs collection to detect paths that have
nomarr/services/domain/library_svc/songs.py:112:        become invalid due to config changes (library root moves, deletions, etc.).
nomarr/services/domain/library_svc/songs.py:113:        Useful after modifying library configurations or recovering from filesystem changes.
nomarr/services/domain/library_svc/songs.py:114:
nomarr/services/domain/library_svc/songs.py:115:        Args:
nomarr/services/domain/library_svc/songs.py:116:            library_id: Library document _id to scope reconciliation to
nomarr/services/domain/library_svc/songs.py:117:            policy: What to do with invalid paths:
nomarr/services/domain/library_svc/songs.py:118:                - "dry_run": Only report, don't modify database
nomarr/services/domain/navidrome_svc.py:207:        """Generate a static M3U playlist from file IDs.
nomarr/services/domain/navidrome_svc.py:208:
nomarr/services/domain/navidrome_svc.py:209:        Produces M3U content with relative paths (relative to the library
nomarr/services/domain/navidrome_svc.py:210:        root, resolved from the file records).  When the ``m3u_output_path``
nomarr/services/domain/navidrome_svc.py:211:        config key is set, the M3U file is also saved server-side.
nomarr/services/domain/navidrome_svc.py:212:
nomarr/services/domain/navidrome_svc.py:213:        Does **not** push to Navidrome — call
nomarr/services/domain/navidrome_svc.py:214:        :meth:`push_static_playlist` explicitly for that.
nomarr/services/domain/navidrome_svc.py:215:
nomarr/services/domain/navidrome_svc.py:216:        Args:
nomarr/services/domain/navidrome_svc.py:217:            file_ids: List of library file document IDs (max 200).
nomarr/services/domain/navidrome_svc.py:218:            playlist_name: Name for the playlist header.
nomarr/services/domain/navidrome_svc.py:219:
nomarr/services/domain/navidrome_svc.py:220:        Returns:
nomarr/services/domain/navidrome_svc.py:221:            StaticPlaylistResult with M3U content, track count, missing IDs,
nomarr/services/domain/navidrome_svc.py:222:            and optionally the server-side save path.
nomarr/services/domain/navidrome_svc.py:223:
nomarr/services/domain/navidrome_svc.py:224:        """
nomarr/services/domain/metadata_svc.py:1:"""Metadata service - tag-based entity navigation.
nomarr/services/domain/metadata_svc.py:2:
nomarr/services/domain/metadata_svc.py:3:Provides read-only access to tag collections and song-tag relationships.
nomarr/services/domain/metadata_svc.py:4:Uses the unified tags schema where entities are just tags with specific name values.
nomarr/services/domain/metadata_svc.py:5:
nomarr/services/domain/metadata_svc.py:6:TAG_UNIFICATION_REFACTOR: Entities are now tags. Route collection values map to name values:
nomarr/services/domain/metadata_svc.py:7:    - "artist" → name="artist"
nomarr/services/domain/metadata_svc.py:12:"""
nomarr/services/domain/metadata_svc.py:13:
nomarr/services/domain/metadata_svc.py:14:from __future__ import annotations
nomarr/services/domain/metadata_svc.py:15:
nomarr/services/domain/metadata_svc.py:16:import logging
nomarr/services/domain/metadata_svc.py:17:from typing import TYPE_CHECKING, Literal
nomarr/services/domain/metadata_svc.py:18:
nomarr/services/domain/metadata_svc.py:19:from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count
nomarr/services/domain/metadata_svc.py:20:from nomarr.components.tagging.tag_query_comp import (
nomarr/services/domain/metadata_svc.py:21:    count_songs_for_tag,
nomarr/services/domain/metadata_svc.py:22:    count_tags_by_name,
nomarr/services/domain/metadata_svc.py:23:    get_song_tags,
nomarr/services/domain/metadata_svc.py:24:    get_tag,
nomarr/services/domain/metadata_svc.py:25:    list_songs_for_tag,
nomarr/services/domain/metadata_svc.py:26:    list_tags_by_name,
nomarr/services/domain/metadata_svc.py:27:)
nomarr/services/domain/metadata_svc.py:28:from nomarr.components.tagging.tag_write_comp import find_or_create_tag
nomarr/services/domain/metadata_svc.py:29:from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult
nomarr/services/domain/metadata_svc.py:30:
nomarr/services/domain/metadata_svc.py:31:if TYPE_CHECKING:
nomarr/services/domain/metadata_svc.py:32:    from nomarr.persistence.db import Database
nomarr/services/domain/metadata_svc.py:33:
nomarr/services/domain/metadata_svc.py:34:logger = logging.getLogger(__name__)
nomarr/services/domain/metadata_svc.py:35:
nomarr/services/domain/metadata_svc.py:36:# Type alias for entity collection names (for API compatibility)
nomarr/services/domain/metadata_svc.py:37:EntityCollection = Literal["artist", "album", "label", "genre", "year"]
nomarr/services/domain/metadata_svc.py:38:
nomarr/services/domain/metadata_svc.py:39:# Mapping of collection name to name value(s) for queries
nomarr/services/domain/metadata_svc.py:40:COLLECTION_REL_MAP: dict[EntityCollection, str] = {
nomarr/services/domain/metadata_svc.py:41:    "artist": "artist",
nomarr/services/domain/metadata_svc.py:58:        """
nomarr/services/domain/metadata_svc.py:59:        self.db = db
nomarr/services/domain/metadata_svc.py:60:
nomarr/services/domain/metadata_svc.py:61:    def list_entities(
nomarr/services/domain/metadata_svc.py:62:        self,
nomarr/services/domain/metadata_svc.py:63:        collection: EntityCollection,
nomarr/services/domain/metadata_svc.py:64:        limit: int = 100,
nomarr/services/domain/metadata_svc.py:65:        offset: int = 0,
nomarr/services/domain/metadata_svc.py:66:        search: str | None = None,
nomarr/services/domain/metadata_svc.py:67:    ) -> EntityListResult:
nomarr/services/domain/metadata_svc.py:68:        """List entities (tags) from a collection.
nomarr/services/domain/metadata_svc.py:69:
nomarr/services/domain/metadata_svc.py:70:        Args:
nomarr/services/domain/metadata_svc.py:71:            collection: Entity collection name (maps to name)
nomarr/services/domain/metadata_svc.py:72:            limit: Maximum results
nomarr/services/domain/metadata_svc.py:73:            offset: Skip first N results
nomarr/services/domain/metadata_svc.py:74:            search: Optional substring search on value
nomarr/services/domain/metadata_svc.py:75:
nomarr/services/domain/metadata_svc.py:76:        Returns:
nomarr/services/domain/metadata_svc.py:77:            EntityListResult with entities, total, limit, offset
nomarr/services/domain/metadata_svc.py:78:
nomarr/services/domain/metadata_svc.py:79:        """
nomarr/services/domain/metadata_svc.py:80:        name = COLLECTION_REL_MAP[collection]
nomarr/services/domain/metadata_svc.py:81:        tags = list_tags_by_name(self.db, name, limit=limit, offset=offset, search=search)
nomarr/services/domain/metadata_svc.py:82:        total = count_tags_by_name(self.db, name, search=search)
nomarr/services/domain/metadata_svc.py:83:
nomarr/services/domain/metadata_svc.py:84:        entity_dicts: list[EntityDict] = [
nomarr/services/domain/metadata_svc.py:85:            {
nomarr/services/domain/metadata_svc.py:86:                "id": t["id"],
nomarr/services/domain/metadata_svc.py:238:        """Get total counts for all entity types (tag names).
nomarr/services/domain/metadata_svc.py:239:
nomarr/services/domain/metadata_svc.py:240:        Returns:
nomarr/services/domain/metadata_svc.py:241:            Dict mapping collection name to count
nomarr/services/domain/metadata_svc.py:242:
nomarr/services/domain/metadata_svc.py:243:        """
nomarr/services/domain/analytics_svc.py:283:        """Get collection overview data for Insights tab.
nomarr/services/domain/analytics_svc.py:284:
nomarr/services/domain/analytics_svc.py:285:        Simple persistence pass-through: library stats, year/genre distributions.
nomarr/services/domain/analytics_svc.py:286:
nomarr/services/domain/analytics_svc.py:287:        Args:
nomarr/services/domain/analytics_svc.py:288:            library_id: Optional library ID to filter by.
nomarr/services/domain/analytics_svc.py:289:
nomarr/services/domain/analytics_svc.py:290:        Returns:
nomarr/services/domain/analytics_svc.py:291:            Dict with: stats, year_distribution, genre_distribution
nomarr/services/domain/analytics_svc.py:292:
nomarr/services/domain/analytics_svc.py:293:        """
nomarr/services/domain/tagging_svc/curation.py:36:        """Fetch a tag document or raise ValueError."""
```

## Secondary: Raw word-boundary counts (no quoted-string filter)

### raw \b_id\b — match-line count: 22
```
nomarr/helpers/dto/navidrome_dto.py:222:        unresolved_file_ids: Nomarr file ``_id`` values with no ND mapping.
nomarr/interfaces/api/types/playlist_import_types.py:44:        description="Optional library _id to restrict matching scope",
nomarr/interfaces/api/types/info_types.py:176:    library_id: int = Field(..., description="Library document _id")
nomarr/interfaces/api/types/info_types.py:195:    library_id: int = Field(..., description="Library document _id")
nomarr/workflows/vectors/get_track_vector_wf.py:32:        file_id: Song document ``_id`` (e.g. ``"song/12345"``).
nomarr/workflows/navidrome/generate_playlists_wf.py:82:        List of generated playlists with ``song/_id`` track lists.
nomarr/workflows/library/scan_library_full_wf.py:76:        library_id: Library document ``_id``
nomarr/workflows/library/scan_setup_wf.py:43:        library_id: Library document ``_id``.
nomarr/workflows/library/reconcile_paths_wf.py:31:        library_id: Library document _id to scope reconciliation to
nomarr/workflows/library/scan_library_quick_wf.py:72:        library_id: Library document ``_id``
nomarr/workflows/processing/process_file_wf.py:60:        file_id: song document _id. Avoids path-based lookup when provided.
nomarr/components/workers/worker_tag_comp.py:33:        File ``_id`` string if a file was claimed, ``None`` if no work available
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:29:        song_id: Library song document ``_id``.
nomarr/components/library/tag_hydration_comp.py:87:        string _id are returned as shallow copies. Songs with no tags are
nomarr/components/library/tag_hydration_comp.py:136:        New dict with metadata fields merged in. If the song has no string _id,
nomarr/components/library/move_detection_comp.py:31:    file_id: int  # DB _id of the moved file
nomarr/components/library/reconcile_paths_comp.py:38:        library_id: Library document _id to scope reconciliation to
nomarr/services/domain/library_svc/songs.py:116:            library_id: Library document _id to scope reconciliation to
nomarr/services/domain/playlist_import_svc.py:59:            library_id: Optional library _id to restrict matching scope
nomarr/services/domain/analytics_svc.py:201:            library_id: Optional library ``_id`` to filter by.
nomarr/services/domain/tagging_svc/query.py:96:            tag_id: Tag _id
nomarr/services/domain/tagging_svc/query.py:133:            library_id: Optional library _id to scope. If None, finds libraries
```

### raw \b_key\b — match-line count: 4
```
nomarr/workflows/processing/write_file_tags_wf.py:48:    file_key: str  # Document _key of the file
nomarr/workflows/processing/write_file_tags_wf.py:121:        file_key: Document _key of the file to write
nomarr/components/ml/calibration/ml_calibration_state_comp.py:94:    _key = _make_calibration_state_key(head_name, label)
nomarr/components/ml/calibration/ml_calibration_state_comp.py:96:        "key": _key,
```

### raw \b_rev\b — match-line count: 0
```
```

### raw \bcollection\b — match-line count: 86
```
nomarr/helpers/vector_params_helper.py:30:        doc_count: Total number of vectors in the collection.
nomarr/helpers/vector_params_helper.py:34:        as a sensible medium-collection default.
nomarr/helpers/vector_params_helper.py:59:        doc_count: Total number of vectors in the collection.
nomarr/helpers/filter_types.py:4:to build filter expressions for collection queries.  They live in helpers
nomarr/helpers/__init__.py:10:  Library path resolution with security validation and audio file collection.
nomarr/helpers/dataclasses/tags_dataclass.py:55:    """Canonical non-empty collection of Tag objects.
nomarr/helpers/dataclasses/tags_dataclass.py:61:    An empty tag collection is invalid in Nomarr. Use None to represent unloaded,
nomarr/interfaces/api/types/vector_types.py:46:    hot_count: int = Field(..., description="Number of vectors in hot collection")
nomarr/interfaces/api/types/vector_types.py:47:    cold_count: int = Field(..., description="Number of vectors in cold collection")
nomarr/interfaces/api/types/vector_types.py:48:    index_exists: bool = Field(..., description="Whether cold collection has vector index")
nomarr/interfaces/api/types/analytics_types.py:180:    """Response for collection overview endpoint."""
nomarr/interfaces/api/types/analytics_types.py:194:        """Convert collection overview result dict to Pydantic response model."""
nomarr/interfaces/api/web/analytics_if.py:122:@router.get("/collection-overview", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/analytics_if.py:127:    """Get collection overview statistics.
nomarr/interfaces/api/web/analytics_if.py:136:        logger.exception("[Web API] Error getting collection overview")
nomarr/interfaces/api/web/analytics_if.py:139:            detail=sanitize_exception_message(e, "Failed to get collection overview"),
nomarr/interfaces/api/web/metadata_if.py:27:# Type alias for entity collection names
nomarr/interfaces/api/web/metadata_if.py:40:@router.get("/{collection}", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/metadata_if.py:42:    collection: EntityCollection,
nomarr/interfaces/api/web/metadata_if.py:48:    """List entities from a collection (artist, album, label, genre, year)."""
nomarr/interfaces/api/web/metadata_if.py:50:        metadata_service.list_entities, collection, limit=limit, offset=offset, search=search
nomarr/interfaces/api/web/metadata_if.py:55:@router.get("/{collection}/{entity_id}", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/metadata_if.py:57:    collection: EntityCollection,  # noqa: ARG001  # FastAPI path param name is part of the URL contract
nomarr/interfaces/api/web/metadata_if.py:64:    Collection parameter is informational only (entity_id already contains collection).
nomarr/interfaces/api/web/metadata_if.py:73:@router.get("/{collection}/{entity_id}/song", dependencies=[Depends(verify_session)])
nomarr/interfaces/api/web/metadata_if.py:75:    collection: EntityCollection,  # noqa: ARG001  # FastAPI path param name is part of the URL contract
nomarr/workflows/calibration/calibration_loader_wf.py:30:    """Load all calibrations from calibration_state collection.
nomarr/workflows/calibration/calibration_loader_wf.py:88:    Checks calibration_version in meta collection. If version matches cached
nomarr/workflows/calibration/import_calibration_bundle_wf.py:50:    and updates global calibration version in meta collection.
nomarr/workflows/vectors/get_track_vector_wf.py:3:Fetches the promoted vector directly from the per-backbone cold collection.
nomarr/workflows/vectors/get_track_vector_wf.py:28:    collection. No library resolution needed.
nomarr/workflows/vectors/get_track_vector_wf.py:37:        or ``None`` when no promoted vector exists in the cold collection.
nomarr/workflows/platform/prune_orphaned_files_wf.py:9:ownership edges), but they persist in the collection and bloat counts. They also
nomarr/workflows/platform/backfill_vector_genres_wf.py:24:    """Backfill missing ``genres`` arrays on a cold vector collection.
nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:17:    """Clean up orphaned tags from the tags collection.
nomarr/workflows/navidrome/generate_navidrome_config_wf.py:28:    Queries the tags collection to discover all nomarr tags, detects their types,
nomarr/workflows/navidrome/find_similar_tracks_wf.py:54:        2. Fetch seed vector from the promoted cold collection via components
nomarr/workflows/navidrome/find_similar_tracks_wf.py:55:        3. Run ANN search on cold collection
nomarr/workflows/navidrome/find_similar_tracks_wf.py:85:    # 2. Get seed vector from per-backbone cold collection (no library_key needed)
nomarr/workflows/navidrome/find_similar_tracks_wf.py:97:    # 3. ANN search on per-backbone cold collection
nomarr/workflows/library/reconcile_paths_wf.py:25:    This checks all files in the songs collection to detect paths that have
nomarr/app.py:326:                    logger.debug("[Application] File watchers synced with library collection")
nomarr/components/tagging/tag_stats_comp.py:22:    ``library_id``), so a whole-collection listing is assembled by iterating the
nomarr/components/tagging/tag_stats_comp.py:33:    """Return song documents scoped to one library or the whole collection."""
nomarr/components/tagging/tag_stats_comp.py:233:    """Return aggregate collection stats for the whole library or one library."""
nomarr/components/tagging/tag_stats_comp.py:255:    """Return year distribution rows for collection overview."""
nomarr/components/tagging/tag_stats_comp.py:306:    """Return genre distribution rows for collection overview."""
nomarr/components/ml/resources/ml_vram_probe_comp.py:4:results in the ``meta`` collection as:
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:21:    non-empty hot collection.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:28:        List of backbone IDs where the hot collection exists and has at
nomarr/components/ml/vectors/ml_vector_registry_comp.py:21:    """Delete vectors for a song from every registered vector collection.
nomarr/components/ml/vectors/ml_vector_registry_comp.py:45:    """Delete vectors for multiple songs from every registered vector collection.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:107:    vector collection, and returns elapsed milliseconds.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:112:        backbone: Backbone model name (used to select the vector collection).
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:19:    """Fetch a track's vector document from the cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:41:            "[vectors] Cold collection is empty for backbone=%s",
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:58:    """Run ANN similarity search against the promoted cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:60:    Searches the per-backbone cold vector namespace.  If the cold collection
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:72:        the promoted cold collection contains no documents.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:78:            "Skipping ANN search because cold collection is empty for backbone=%s",
nomarr/components/metadata/metadata_cache_comp.py:3:Rebuilds derived song metadata fields from authoritative tags collection.
nomarr/components/navidrome/playlist_builder_comp.py:4:cold vector collection.  Builders return ``songs/id`` values;
nomarr/components/navidrome/playlist_builder_comp.py:68:    Returns ``None`` only when every cluster search returned ``None`` (empty collection).
nomarr/components/library/library_song_query_comp.py:126:    ``library_id``), so a whole-collection listing is assembled by iterating the
nomarr/components/library/library_song_state_comp.py:44:# missed by a prefix check (AR-SDR-6 stripped the legacy doc-collection
nomarr/components/library/reconcile_paths_comp.py:3:This component re-validates all paths in the songs collection against
nomarr/components/library/reconcile_paths_comp.py:32:    This component scans the songs collection and re-validates each path
nomarr/components/analytics/collection_overview_comp.py:29:    """Get collection overview: library stats, year/genre distributions.
nomarr/components/infrastructure/path_comp.py:111:    This is used when reading paths from queue tables, the file collection, etc.
nomarr/services/infrastructure/file_watcher_svc.py:201:        """Sync watchers with the library collection (DB is source of truth).
nomarr/services/domain/vector_maintenance_svc.py:136:        which scales the build-time parameter by collection size.
nomarr/services/domain/vector_search_svc.py:45:        single ANN query against the per-backbone cold collection. Cross-library
nomarr/services/domain/vector_search_svc.py:67:            ValueError: If file not found, no vector exists, or cold collection
nomarr/services/domain/vector_search_svc.py:72:        # Step 1: Get the source track's vector from the per-backbone cold collection
nomarr/services/domain/vector_search_svc.py:82:        # Step 2: Single ANN search on per-backbone cold collection
nomarr/services/domain/vector_search_svc.py:104:        per-backbone cold collection directly (no library resolution needed).
nomarr/services/domain/library_svc/songs.py:111:        This checks all files in the songs collection to detect paths that have
nomarr/services/domain/metadata_svc.py:6:TAG_UNIFICATION_REFACTOR: Entities are now tags. Route collection values map to name values:
nomarr/services/domain/metadata_svc.py:36:# Type alias for entity collection names (for API compatibility)
nomarr/services/domain/metadata_svc.py:39:# Mapping of collection name to name value(s) for queries
nomarr/services/domain/metadata_svc.py:63:        collection: EntityCollection,
nomarr/services/domain/metadata_svc.py:68:        """List entities (tags) from a collection.
nomarr/services/domain/metadata_svc.py:71:            collection: Entity collection name (maps to name)
nomarr/services/domain/metadata_svc.py:80:        name = COLLECTION_REL_MAP[collection]
nomarr/services/domain/metadata_svc.py:241:            Dict mapping collection name to count
nomarr/services/domain/analytics_svc.py:283:        """Get collection overview data for Insights tab.
```

### raw \bdocument\b — match-line count: 89
```
nomarr/helpers/config_schema.py:11:    LibraryConfigFields — per-library document sub-schema (TypedDict)
nomarr/helpers/exceptions_helper.py:15:    """Raised when a library document cannot be found by its ID."""
nomarr/helpers/exceptions.py:17:    """Raised when a library document cannot be found by its ID."""
nomarr/interfaces/api/types/vector_types.py:18:    file_id: str = Field(..., description="Library file document ID to find similar tracks for")
nomarr/interfaces/api/types/vector_types.py:27:    file_id: int = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/vector_types.py:84:    file_id: int = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/playlist_import_types.py:86:    file_id: str = Field(..., description="Library file document ID")
nomarr/interfaces/api/types/info_types.py:176:    library_id: int = Field(..., description="Library document _id")
nomarr/interfaces/api/types/info_types.py:195:    library_id: int = Field(..., description="Library document _id")
nomarr/workflows/calibration/calibration_loader_wf.py:92:    Version check is ~2-5ms single document lookup vs ~50ms full calibration load.
nomarr/workflows/vectors/get_track_vector_wf.py:32:        file_id: Song document ``_id`` (e.g. ``"song/12345"``).
nomarr/workflows/vectors/get_track_vector_wf.py:36:        Vector document dict (includes ``vector_n``, ``file_id``, etc.)
nomarr/workflows/platform/prune_orphaned_files_wf.py:3:A song document is orphaned when it has no inbound library_contains_file
nomarr/workflows/platform/prune_orphaned_files_wf.py:11:check finds the old document and returns it as "existing".
nomarr/workflows/platform/prune_orphaned_files_wf.py:32:    state edges → file document.
nomarr/workflows/navidrome/generate_static_playlist_wf.py:3:This workflow accepts a list of library file document IDs,
nomarr/workflows/navidrome/generate_static_playlist_wf.py:46:        file_ids: List of library file document IDs (max 200).
nomarr/workflows/library/scan_library_full_wf.py:76:        library_id: Library document ``_id``
nomarr/workflows/library/scan_setup_wf.py:43:        library_id: Library document ``_id``.
nomarr/workflows/library/scan_setup_wf.py:47:        The library document dict.
nomarr/workflows/library/reconcile_paths_wf.py:31:        library_id: Library document _id to scope reconciliation to
nomarr/workflows/library/scan_library_quick_wf.py:72:        library_id: Library document ``_id``
nomarr/workflows/processing/process_file_wf.py:60:        file_id: song document _id. Avoids path-based lookup when provided.
nomarr/workflows/processing/write_file_tags_wf.py:137:        # Get file document via component
nomarr/components/workers/worker_discovery_comp.py:62:        file_id: File document id (e.g., ``12345``)
nomarr/components/workers/worker_discovery_comp.py:87:        file_id: File document id
nomarr/components/workers/worker_discovery_comp.py:103:        payload: Full claim document payload including ``key``, ``file_id``,
nomarr/components/tagging/tag_query_comp.py:111:    """Get one tag document by ``id``."""
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:29:        least one document.
nomarr/components/ml/vectors/ml_vector_idle_promotion_comp.py:48:    Sums hot and cold counts to determine total document count, then
nomarr/components/ml/vectors/ml_vector_persist_comp.py:45:    Builds the hot vector document for the given song and model suite,
nomarr/components/ml/vectors/ml_vector_persist_comp.py:47:    normalized ``db.ml`` intent API, and returns the stored vector document id.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:51:        song_id: Library song document ``id``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:59:        The stored vector document ``id``.
nomarr/components/ml/vectors/ml_vector_persist_comp.py:111:        song_id: song document id.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:19:    """Fetch a track's vector document from the cold collection.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:29:        song_id: Library song document ``_id``.
nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:33:        Vector document dict (includes ``vector_n``, ``score``, etc.)
nomarr/components/ml/onnx/ml_model_registry_comp.py:21:    """Return the stable document key used for one registered model path."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:26:    """Return the stable document key used for one model output vertex."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:31:    """Return every registered ML model document."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:37:    """Return the registered model document for ``path`` if present."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:68:        Persisted ``ml_models`` document, including database fields such as
nomarr/components/ml/onnx/ml_model_registry_comp.py:106:            raise RuntimeError(f"Failed to load persisted ml_models document for path={path}")
nomarr/components/ml/onnx/ml_model_registry_comp.py:109:        msg = f"Failed to load persisted ml_models document for path={path}"
nomarr/components/metadata/metadata_cache_comp.py:41:    the fields that belong on the song document's embedded cache.
nomarr/components/metadata/metadata_cache_comp.py:69:    document, plus any of the recognised cache fields.
nomarr/components/library/work_status_comp.py:18:    """Shape of a library document consumed by ``compute_work_status``."""
nomarr/components/library/library_scan_file_ops_comp.py:44:    """Return the canonical folder document id for a library/path pair."""
nomarr/components/library/library_scan_file_ops_comp.py:54:    """Build the folder-cache document persisted for quick scans."""
nomarr/components/library/scan_lifecycle_comp.py:50:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:65:    """Fetch a library document, raising if not found.
nomarr/components/library/scan_lifecycle_comp.py:69:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:97:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:144:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:193:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:212:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:239:        library_id: Library document ``id``
nomarr/components/library/scan_lifecycle_comp.py:264:        library_id: Library document ``id``.
nomarr/components/library/scan_lifecycle_comp.py:298:        library_id: Library document ``id``
nomarr/components/library/library_id_comp.py:4:``libraries/{key}`` document ids. Kept in a leaf module so that all other
nomarr/components/library/library_song_query_comp.py:24:    """Get one library-song document by ``id``."""
nomarr/components/library/library_song_query_comp.py:262:    """Get a library-song document by normalized or absolute path.
nomarr/components/library/library_records_comp.py:1:"""Library document composition helpers."""
nomarr/components/library/library_records_comp.py:33:    """Insert a library document.
nomarr/components/library/library_records_comp.py:109:    """Update a library document by ``id`` through the constructor namespace."""
nomarr/components/library/library_records_comp.py:146:    """Return all library document keys for bootstrap-style callers."""
nomarr/components/library/library_records_comp.py:201:    """Merge library scan state into a library document for API compatibility."""
nomarr/components/library/library_song_state_comp.py:125:    no document fetch.
nomarr/components/library/library_scan_state_comp.py:3:Extracted from ``scan_lifecycle_comp`` — owns scan-document read/write and
nomarr/components/library/library_scan_state_comp.py:53:    """Return the canonical scan document id for a library."""
nomarr/components/library/library_scan_state_comp.py:58:    """Build the canonical default scan document payload."""
nomarr/components/library/library_scan_state_comp.py:67:    """Return the scan document for a library, creating it when missing."""
nomarr/components/library/library_scan_state_comp.py:79:    """Return the scan document for a library, or None when no scan exists."""
nomarr/components/library/library_song_mutation_comp.py:31:    """Insert or update a library-song document and its ownership/state edges.
nomarr/components/library/library_song_mutation_comp.py:58:    """Delete a library-song document and its edges.
nomarr/components/library/library_song_mutation_comp.py:135:    Silently skips paths with no matching document. Returns the number deleted.
nomarr/components/library/reconcile_paths_comp.py:38:        library_id: Library document _id to scope reconciliation to
nomarr/components/processing/file_write_comp.py:36:    """Normalise *file_key* and fetch the library-file document.
nomarr/components/processing/file_write_comp.py:40:        document does not exist.
nomarr/services/domain/vector_maintenance_svc.py:133:        """Calculate optimal HNSW ef_construction for vector index based on document count.
nomarr/services/domain/vector_search_svc.py:49:            file_id: Library file document ID to find similar tracks for.
nomarr/services/domain/vector_search_svc.py:61:                - file_id: Library file document ID
nomarr/services/domain/vector_search_svc.py:64:                - Other document fields
nomarr/services/domain/vector_search_svc.py:108:            file_id: Library file document ID
nomarr/services/domain/vector_search_svc.py:111:            Vector document or None if not found
nomarr/services/domain/library_svc/songs.py:116:            library_id: Library document _id to scope reconciliation to
nomarr/services/domain/navidrome_svc.py:217:            file_ids: List of library file document IDs (max 200).
nomarr/services/domain/tagging_svc/curation.py:36:        """Fetch a tag document or raise ValueError."""
```

### raw \bvertex\b — match-line count: 11
```
nomarr/helpers/constants/file_states.py:1:"""Canonical song-state axis-pair vertex identifiers shared across layers.
nomarr/interfaces/api/types/ml_types.py:17:    """Response model for a registered ML model vertex."""
nomarr/workflows/platform/register_ml_models_wf.py:48:    3. Upsert model vertex into ``ml_models``
nomarr/workflows/platform/register_ml_models_wf.py:80:        # Step 3: Upsert model vertex
nomarr/components/tagging/tag_write_comp.py:18:    """Find or create one tag vertex and return its id."""
nomarr/components/tagging/tag_write_comp.py:104:    """Move song tag references from one tag vertex to another via library intents."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:26:    """Return the stable document key used for one model output vertex."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:144:    """Delete one registered model vertex by ID."""
nomarr/components/ml/onnx/ml_model_registry_comp.py:180:    """Write label metadata for one output vertex."""
nomarr/services/infrastructure/ml_svc.py:140:        """Write a human-readable label for a model output vertex.
nomarr/services/infrastructure/ml_svc.py:151:        """Set the fully_configured flag on a model vertex.
```

### raw \bedge\b — match-line count: 24
```
nomarr/workflows/platform/prepare_database_wf.py:77:    # Step 2: Prune orphaned song documents (no ownership edge).
nomarr/workflows/platform/prune_orphaned_files_wf.py:4:edge — this happens when a library was deleted while the deletion code was broken,
nomarr/workflows/platform/register_ml_models_wf.py:146:            "Pruned stale model %s: removed %d output(s) and %d edge(s)",
nomarr/workflows/library/validate_library_tags_wf.py:28:    A file with a ``written`` edge is considered *complete* only if it has
nomarr/workflows/library/validate_library_tags_wf.py:29:    at least one tag edge for every discovered head (model_key + label) under
nomarr/workflows/library/validate_library_tags_wf.py:31:    removes the ``written`` edge so the file is rediscovered for tag writing.
nomarr/components/tagging/tag_stats_comp.py:63:    """Return ``tag_id -> song_count`` using one batched edge lookup."""
nomarr/components/tagging/tag_stats_comp.py:69:    for edge in _narrow_tag_list(
nomarr/components/tagging/tag_stats_comp.py:72:        if isinstance(tag_id := edge.get("tag_id"), int) and tag_id in count_by_tag_id:
nomarr/components/ml/calibration/ml_calibration_state_comp.py:151:    """Delete one calibration state record and its edge."""
nomarr/components/library/file_batch_scanner_comp.py:32:    edge_bootstraps: list[dict[str, Any]] = field(default_factory=list)  # Post-upsert edge creation metadata
nomarr/components/library/library_song_query_comp.py:243:    return {edge["song_id"] for edge in edges if isinstance(edge.get("song_id"), int)}
nomarr/components/library/library_song_query_comp.py:697:    # song/tag/folder/scan-record/edge/vector data and output streams, leaving
nomarr/components/library/library_song_query_comp.py:727:        for edge in edges:
nomarr/components/library/library_song_query_comp.py:728:            song_id = edge.get("song_id")
nomarr/components/library/library_song_query_comp.py:729:            tag_id = edge.get("tag_id")
nomarr/components/library/library_song_query_comp.py:801:    return len({edge["song_id"] for edge in edges if isinstance(edge.get("song_id"), (int, str))})
nomarr/components/library/move_detection_comp.py:152:                    # Chromaprint matches - verify duration to catch edge cases
nomarr/components/library/library_song_state_comp.py:124:    Uses a single targeted edge-traversal query — no full state scan,
nomarr/components/library/library_song_state_comp.py:333:    """Return whether one song currently has the tagged-state edge."""
nomarr/components/library/library_song_state_comp.py:427:    Songs can exist without any hydration-state edge at all (hydration axis
nomarr/components/library/library_song_state_comp.py:430:      - no hydration edge → add        not_hydrated edge
nomarr/components/processing/file_write_comp.py:131:    coordination: edge discovery per ``(song_id, name)`` pair, targeted edge
nomarr/components/processing/file_write_comp.py:132:    deletion, tag upsert per unique ``(name, value)`` pair, and bulk edge
```

### raw \bAQL\b — match-line count: 0
```
```


## Methodology note
- In-quotes scan uses `rg -U` (multiline): `[^"]*` spans newlines, so a single regex match drags in the whole enclosing docstring block. Distinct-match counts above were computed with `rg --count-matches -U`. The matched-region-line count is higher because each match spans many docstring lines.
- Terminology (collection/document/vertex/edge/AQL) in-quotes count is therefore inflated: it matches any docstring containing one of those words. The raw word-boundary counts are the reliable per-word signal.
- Raw word-boundary counts are `rg -n` matching-line counts (== distinct matches here; single-line matches).
- `nomarr/persistence/**` and `tests/**` excluded per plan scope.
