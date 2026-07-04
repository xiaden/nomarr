"""Platform workflows — database preparation and infrastructure setup.

Provides the ``prepare_database_workflow`` which runs schema migrations,
registers known ML models, and performs vector maintenance at startup.
"""

from .prepare_database_wf import prepare_database_workflow

__all__ = [
    "prepare_database_workflow",
]
