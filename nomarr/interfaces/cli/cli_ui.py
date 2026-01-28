#!/usr/bin/env python3
"""
Rich UI components for CLI - consistent, professional interface across all commands.
"""

from __future__ import annotations

from collections.abc import Callable

from rich import box
from rich.console import Console
from rich.panel import Panel

console = Console()

# Color scheme constants
COLOR_SUCCESS = "green"
COLOR_ERROR = "red"
COLOR_WARNING = "yellow"
COLOR_INFO = "cyan"
COLOR_RUNNING = "blue"
COLOR_PENDING = "yellow"
COLOR_DONE = "green"


class InfoPanel:
    """
    Simple panel for displaying status/info without progress tracking.
    """

    @staticmethod
    def show(title: str, content: str, border_style: str = COLOR_INFO):
        """Show a single info panel."""
        panel = Panel(content, title=f"[bold]{title}[/bold]", border_style=border_style, box=box.ROUNDED)
        console.print(panel)

    @staticmethod
    def show_multiple(panels: list[dict[str, str]]):
        """Show multiple panels vertically."""
        for panel_info in panels:
            InfoPanel.show(
                panel_info.get("title", "Info"),
                panel_info.get("content", ""),
                panel_info.get("border_style", COLOR_INFO),
            )
            console.print()  # Blank line between panels


def show_spinner(message: str, task_fn: Callable, *args, **kwargs):
    """
    Show a spinner while executing a task.
    Returns the result of task_fn.
    """
    with console.status(f"[bold {COLOR_INFO}]{message}[/bold {COLOR_INFO}]"):
        return task_fn(*args, **kwargs)


def print_success(message: str):
    """Print a success message."""
    console.print(f"[bold {COLOR_SUCCESS}]✓[/bold {COLOR_SUCCESS}] {message}")


def print_error(message: str):
    """Print an error message."""
    console.print(f"[bold {COLOR_ERROR}]✗[/bold {COLOR_ERROR}] {message}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"[bold {COLOR_WARNING}]⚠[/bold {COLOR_WARNING}] {message}")


def print_info(message: str):
    """Print an info message."""
    console.print(f"[{COLOR_INFO}][i][/{COLOR_INFO}] {message}")
