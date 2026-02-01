"""Data models for API coverage analysis."""

from dataclasses import dataclass


@dataclass
class EndpointUsage:
    """Information about an endpoint and its usage."""

    method: str
    path: str
    used: bool
    frontend_files: list[tuple[str, int]]  # (file_path, line_number)
    description: str | None = None
    summary: str | None = None
    backend_file: str | None = None
    backend_line: int | None = None

    @property
    def status_class(self) -> str:
        """CSS class for status indicator."""
        return "used" if self.used else "unused"

    @property
    def status_text(self) -> str:
        """Human-readable status."""
        return "✓ Used" if self.used else "✗ Unused"
