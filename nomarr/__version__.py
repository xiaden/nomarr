"""Version information for Nomarr."""

# Semantic versioning: MAJOR.MINOR.PATCH
# MAJOR: Breaking changes to API or data structures
# MINOR: New features, backward compatible
# PATCH: Bug fixes, backward compatible

__version__ = "0.1.2"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Version history:
# 0.1.0 - Initial pre-alpha release
#         - Basic tagging functionality
#         - Library scanner with auto-tagging
#         - Calibration system with drift tracking
#         - Web UI and CLI interfaces
