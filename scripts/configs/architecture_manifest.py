"""Architecture manifest for Nomarr.

Single source of truth for Nomarr's architectural layers and module organization.
Other tooling (doc generation, dependency graphs, etc.) imports from here instead
of parsing .importlinter or guessing from directory structure.

This is intentionally minimal and contains only string constants - no imports
from nomarr.* modules.
"""

# ----------------------------------------------------------------------
# Layer Definitions
# ----------------------------------------------------------------------

# Architectural layers in dependency order (top-level → low-level)
# Higher layers may import from lower layers, but not vice versa
LAYERS = [
    "nomarr.interfaces",  # HTTP API, CLI, Web UI
    "nomarr.services",  # Runtime wiring, long-lived resources
    "nomarr.workflows",  # Use case implementations
    "nomarr.tagging",  # Tag generation and aggregation
    "nomarr.ml",  # Models, embeddings, inference
    "nomarr.analytics",  # Tag statistics and correlations
    "nomarr.persistence",  # Database and queue access
    "nomarr.helpers",  # Pure utilities and shared dataclasses
]

# ----------------------------------------------------------------------
# Documentation Groups (Future Use)
# ----------------------------------------------------------------------

# Maps high-level documentation sections to module groups
# Example:
#   DOC_GROUPS = {
#       "API & Interfaces": ["nomarr.interfaces"],
#       "Core Logic": ["nomarr.services", "nomarr.workflows"],
#       "Data Layer": ["nomarr.persistence", "nomarr.helpers"],
#       ...
#   }
DOC_GROUPS: dict[str, list[str]] = {}
