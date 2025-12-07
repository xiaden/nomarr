"""Version information for Nomarr."""

# Semantic versioning: MAJOR.MINOR.PATCH
# MAJOR: Breaking changes to API or data structures
# MINOR: New features, backward compatible
# PATCH: Bug fixes, backward compatible

__version__ = "0.1.4"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Version history:
# 0.1.4 - Frontend improvements and architecture refactoring
#         Frontend:
#         - New Browse Files page with search, pagination, and expandable file cards
#         - Two-step tag filtering: select key → select value (replaces pointless key-only filter)
#         - Dashboard SSE progress tracking and library file count preview
#         Backend:
#         - /files/search endpoint with full-text search (artist/album/title) and tag filtering
#         - /files/tags/values endpoint for dynamic value dropdowns
#         - search_library_files_with_tags() supports tag_key+tag_value filtering
#         - get_unique_tag_values() for populating value dropdowns
#         - Fixed UpdateLibraryFileFromTagsParams missing fields (calibration, library_id)
#         Architecture & Refactoring:
#         - Worker crash handling and job recovery system
#         - Queue refactor: interfaces now use queue components/workflows (not QueueService)
#         - DTO consolidation: reduced from 71 to 64 DTOs (JobDict→Job, proper DTO rules)
#         - Smart playlists refactored with SQL helpers and DTO reorganization
#         - All tag filtering properly layered (persistence → component → service → interface)
#         - Removed 22 dead code nodes across codebase
#         Fixes:
#         - Correct Essentia import path (essentia.standard, not essentia_tensorflow)
#         - Package-relative path for public_html (not fragile __file__ traversal)
#         - Public_html path resolution and root route registration
# 0.1.3 - API routing refactor and database schema v2
#         - Unified API structure: Integration (/api/v1) and Web UI (/api/web)
#         - Multi-library support with library_id foreign keys
#         - Normalized tag storage in file_tags table with is_nomarr_tag flag
#         - Frontend multi-library management UI
#         - Config improvements: nomarr.db default, /media library_root
#         - Fixed calibration queries for new schema
#         - All 141 non-ML tests passing
# 0.1.2 - React frontend and web refactoring
#         - Complete TypeScript React frontend with all feature pages
#         - Modular web API package structure
#         - Eliminated raw SQL from web endpoints
#         - CI optimization: only build on version changes
#         - Architecture improvements and circular import fixes
# 0.1.1 - Quality control and type safety
#         - Achieved clean mypy (72 files, 0 errors)
#         - Automated slop & drift detection system
#         - Comprehensive QC tooling with venv setup
#         - Real integration tests replacing smoke tests
#         - Comprehensive smoke test suite with generated audio fixtures
# 0.1.0 - Initial pre-alpha release
#         - Basic tagging functionality
#         - Library scanner with auto-tagging
#         - Calibration system with drift tracking
#         - Web UI and CLI interfaces
