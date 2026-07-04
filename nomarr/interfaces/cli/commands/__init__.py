"""CLI commands subpackage.

Provides CLI subcommand implementations for the ``nom`` entry-point:
- ``cleanup`` — Remove orphaned entities (artists, albums, genres, etc.)
- ``manage-password`` — Show, verify, or reset the admin web UI password
"""

from .cleanup_cli import cmd_cleanup
from .manage_password_cli import cmd_manage_password

__all__ = [
    "cmd_cleanup",
    "cmd_manage_password",
]
