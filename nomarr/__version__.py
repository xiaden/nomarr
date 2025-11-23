"""Version information for Nomarr."""

# Semantic versioning: MAJOR.MINOR.PATCH
# MAJOR: Breaking changes to API or data structures
# MINOR: New features, backward compatible
# PATCH: Bug fixes, backward compatible

__version__ = "0.1.3"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Version history:
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
