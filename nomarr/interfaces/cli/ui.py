#!/usr/bin/env python3
"""
Rich UI components for CLI - consistent, professional interface across all commands.
"""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

console = Console()

# Color scheme constants
COLOR_SUCCESS = "green"
COLOR_ERROR = "red"
COLOR_WARNING = "yellow"
COLOR_INFO = "cyan"
COLOR_RUNNING = "blue"
COLOR_PENDING = "yellow"
COLOR_DONE = "green"


class ProgressDisplay:
    """
    Multi-panel layout with progress bars, recent activity messages, and errors.
    Used for long-running batch operations.
    """

    def __init__(self, total_items: int, item_unit: str = "items"):
        # Kept for compatibility with constructor calls (not actively used after start_heads())
        self.total_items = total_items
        self.item_unit = item_unit
        self.recent_messages = deque(maxlen=5)
        self.error_list = []
        # Files/heads accounting
        self.files_total: int = 0
        self.files_completed: int = 0
        self.heads_per_file: int = 0
        self.total_heads_overall: int = 0

        # Current file tags (for real-time tag display)
        self.current_tags: dict = {}

        # Overall progress
        # Overall: percent is based on heads, label shows files x/y
        self.overall_progress = Progress(
            TextColumn("[bold green]Overall"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TextColumn("[dim]{task.fields[files_label]}[/dim]"),
            TimeRemainingColumn(),
        )

        # Current item progress
        self.item_progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TextColumn("({task.completed}/{task.total})"),
            TimeElapsedColumn(),
        )

        self.overall_task = None
        self.item_task = None
        self.live = None

    def _make_layout(self):
        """Generate the layout with progress, messages, tags, and errors."""
        # Progress bars
        progress_table = Table.grid(expand=True)
        progress_table.add_row(self.overall_progress)
        progress_table.add_row(self.item_progress)

        # Recent messages panel
        messages_text = "\n".join(self.recent_messages) if self.recent_messages else "[dim]No messages yet...[/dim]"
        messages_panel = Panel(
            messages_text, title="[bold]Activity log[/bold]", border_style=COLOR_INFO, height=7, box=box.ROUNDED
        )

        # Tags panel (current file)
        if self.current_tags:
            tags_lines = []
            # Show mood tags first
            for key in ["mood-strict", "mood-regular", "mood-loose"]:
                if key in self.current_tags:
                    val = self.current_tags[key]
                    if isinstance(val, list):
                        tags_lines.append(f"[cyan]{key}:[/cyan] {', '.join(val)}")
                    else:
                        tags_lines.append(f"[cyan]{key}:[/cyan] {val}")

            # Show other notable tags (limit to prevent overflow)
            other_keys = [
                k
                for k in sorted(self.current_tags.keys())
                if k not in ["mood-strict", "mood-regular", "mood-loose", "essentia:version"]
                and not k.endswith("_tier")
            ]  # Hide raw tier tags

            for key in other_keys[:10]:  # Limit to 10 other tags
                val = self.current_tags[key]
                if isinstance(val, list):
                    display_val = ", ".join(str(v) for v in val[:3])
                    if len(val) > 3:
                        display_val += f" +{len(val) - 3}"
                elif isinstance(val, float):
                    display_val = f"{val:.3f}"
                else:
                    display_val = str(val)
                tags_lines.append(f"[dim]{key}:[/dim] {display_val}")

            if len(other_keys) > 10:
                tags_lines.append(f"[dim]... +{len(other_keys) - 10} more tags[/dim]")

            tags_text = "\n".join(tags_lines) if tags_lines else "[dim]Building tags...[/dim]"
        else:
            tags_text = "[dim]No tags yet...[/dim]"

        tags_panel = Panel(
            tags_text,
            title="[bold magenta]Current File Tags[/bold magenta]",
            border_style="magenta",
            height=10,
            box=box.ROUNDED,
        )

        # Errors panel
        if self.error_list:
            errors_text = "\n".join(self.error_list[-10:])  # Last 10 errors
            error_count = (
                f" ({len(self.error_list)} total)" if len(self.error_list) > 10 else f" ({len(self.error_list)})"
            )
        else:
            errors_text = "[dim]No errors[/dim]"
            error_count = ""

        errors_panel = Panel(
            errors_text,
            title=f"[bold red]Errors{error_count}[/bold red]",
            border_style=COLOR_ERROR,
            height=6,
            box=box.ROUNDED,
        )

        return Group(progress_table, messages_panel, tags_panel, errors_panel)

    def start_heads(self, total_files: int, heads_per_file: int):
        """Start display where overall percent is based on total heads across all files.
        The label still shows Files X/Y.
        """
        self.files_total = int(total_files)
        self.files_completed = 0
        self.heads_per_file = int(heads_per_file)
        self.total_heads_overall = self.files_total * self.heads_per_file

        self.overall_task = self.overall_progress.add_task(
            "Processing", total=self.total_heads_overall, files_label=f"{self.files_completed}/{self.files_total} files"
        )
        self.item_task = self.item_progress.add_task("Current Item", total=self.heads_per_file)
        self.live = Live(self._make_layout(), console=console, refresh_per_second=10)
        self.live.start()

    def update_item_progress(self, completed: int, total: int | None = None):
        """Update current item progress."""
        if self.item_task is None or self.live is None:
            return
        if total is not None:
            self.item_progress.update(self.item_task, completed=completed, total=total)
        else:
            self.item_progress.update(self.item_task, completed=completed)
        self.live.update(self._make_layout())
        # Force refresh immediately for real-time updates
        self.live.refresh()

    def advance_overall_heads(self, amount: int = 1):
        """Advance overall progress by number of heads completed."""
        if self.overall_task is None or self.live is None:
            return
        self.overall_progress.update(
            self.overall_task, advance=amount, files_label=f"{self.files_completed}/{self.files_total} files"
        )
        self.live.update(self._make_layout())
        self.live.refresh()

    def mark_file_done(self):
        """Increment files completed count and refresh label."""
        self.files_completed += 1
        # Do not advance overall here (already advanced per-head)
        if self.overall_task is not None and self.live is not None:
            self.overall_progress.update(
                self.overall_task, files_label=f"{self.files_completed}/{self.files_total} files"
            )
            self.live.update(self._make_layout())
            self.live.refresh()

    def reset_item(self, total: int):
        """Reset item progress for new item."""
        if self.item_task is None or self.live is None:
            return
        self.item_progress.update(self.item_task, completed=0, total=total)
        self.live.update(self._make_layout())
        self.live.refresh()

    def set_current_head(self, head_name: str):
        """Update the current item description to show the running head."""
        desc = f"Current Item • {head_name}"
        if self.item_task is None or self.live is None:
            return
        self.item_progress.update(self.item_task, description=desc)
        self.live.update(self._make_layout())
        self.live.refresh()

    def add_message(self, message: str):
        """Add a message to recent activity."""
        self.recent_messages.append(message)
        if self.live is not None:
            self.live.update(self._make_layout())
            self.live.refresh()

    def add_error(self, error: str):
        """Add an error to the error list."""
        self.error_list.append(error)
        if self.live is not None:
            self.live.update(self._make_layout())
            self.live.refresh()

    def update_tags(self, tags: dict):
        """Update the current file's tags (incremental updates as heads complete)."""
        self.current_tags.update(tags)
        if self.live is not None:
            self.live.update(self._make_layout())
            self.live.refresh()

    def clear_tags(self):
        """Clear tags for new file."""
        self.current_tags = {}
        if self.live is not None:
            self.live.update(self._make_layout())
            self.live.refresh()

    def stop(self):
        """Stop the live display."""
        if self.live:
            self.live.stop()


# ----------------------------------------------------------------------
# Logging bridge: route Python logging warnings/errors into the UI panels
# ----------------------------------------------------------------------
_current_display: ProgressDisplay | None = None


class UILogHandler(logging.Handler):
    """
    Logging handler that forwards WARNING/ERROR records to the active
    ProgressDisplay (if any). Keeps CLI users informed in the Errors panel.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()

        disp = _current_display
        if not disp:
            return

        # Route by level
        if record.levelno >= logging.ERROR:
            disp.add_error(f"ERROR: {msg}")
        elif record.levelno >= logging.WARNING:
            disp.add_error(f"WARNING: {msg}")
        else:
            # Optionally surface infos into the Recent Activity
            disp.add_message(msg)


_ui_log_handler: UILogHandler | None = None


def attach_display_logger(display: ProgressDisplay, level: int = logging.WARNING) -> None:
    """Attach a logging handler so warnings/errors appear in the CLI panels."""
    global _current_display, _ui_log_handler
    _current_display = display
    if _ui_log_handler is None:
        _ui_log_handler = UILogHandler()
        _ui_log_handler.setLevel(level)
        # Simple formatter without timestamps (UI provides context)
        _ui_log_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(_ui_log_handler)


def detach_display_logger() -> None:
    """Detach UI logging handler and clear active display reference."""
    global _current_display, _ui_log_handler
    if _ui_log_handler is not None:
        with contextlib.suppress(Exception):
            logging.getLogger().removeHandler(_ui_log_handler)
        _ui_log_handler = None
    _current_display = None


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


class TableDisplay:
    """
    Formatted tables for lists (jobs, tags, etc).
    """

    @staticmethod
    def show_jobs(jobs: list[Any], title: str = "Jobs"):
        """Display a table of jobs."""
        table = Table(title=title, box=box.ROUNDED, show_header=True, header_style="bold")
        table.add_column("ID", style=COLOR_INFO, width=8)
        table.add_column("Status", width=12)
        table.add_column("Path", overflow="fold")
        table.add_column("Time", width=20)

        for job in jobs:
            # Color-code status
            status_color = {
                "pending": COLOR_PENDING,
                "running": COLOR_RUNNING,
                "done": COLOR_DONE,
                "error": COLOR_ERROR,
            }.get(job.status, "white")

            table.add_row(
                str(job.id),
                f"[{status_color}]{job.status}[/{status_color}]",
                str(job.path) if job.path else "",
                str(job.created_at) if job.created_at else "",
            )

        console.print(table)

    @staticmethod
    def show_tags(tags: dict[str, Any], file_path: str):
        """Display file tags in a formatted table."""
        # File info panel
        InfoPanel.show("File Information", f"Path: {file_path}", COLOR_INFO)

        # Tags table
        table = Table(title="Tags", box=box.ROUNDED, show_header=True, header_style="bold")
        table.add_column("Namespace", style=COLOR_INFO, width=15)
        table.add_column("Key", style="cyan", width=30)
        table.add_column("Value", overflow="fold")

        for key, value in sorted(tags.items()):
            # Split namespace from key
            if ":" in key:
                namespace, tag_key = key.split(":", 1)
            else:
                namespace = ""
                tag_key = key

            # Format value
            if isinstance(value, list | tuple):
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = str(value)

            table.add_row(namespace, tag_key, value_str)

        console.print(table)

    @staticmethod
    def show_summary(title: str, data: dict[str, Any], border_style: str = COLOR_INFO):
        """Display a summary table."""
        table = Table(title=title, box=box.ROUNDED, show_header=False, border_style=border_style)
        table.add_column("Metric", style="bold")
        table.add_column("Value")

        for key, value in data.items():
            table.add_row(key, str(value))

        console.print(table)


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


class WorkerPoolDisplay:
    """
    Display for parallel worker processing with per-worker progress bars.
    Shows overall progress, individual worker status, recent completions, and errors.
    """

    def __init__(self, total_files: int, worker_count: int = 4):
        self.total_files = total_files
        self.worker_count = worker_count
        self.files_completed = 0
        self.files_failed = 0

        self.recent_completions = deque(maxlen=5)
        self.error_list = []

        # Overall progress
        self.overall_progress = Progress(
            TextColumn("[bold green]Overall"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TextColumn("({task.completed}/{task.total} files)"),
            TimeRemainingColumn(),
        )
        self.overall_task = None

        # Per-worker progress bars
        self.worker_progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.fields[status]}"),
        )
        self.worker_tasks = {}  # worker_id -> task_id

        self.live = None

    def _make_layout(self):
        """Generate the layout."""
        # Overall progress bar
        progress_table = Table.grid(expand=True)
        progress_table.add_row(self.overall_progress)

        # Worker progress bars
        workers_panel = Panel(self.worker_progress, title="[bold]Workers[/bold]", border_style="cyan", box=box.ROUNDED)

        # Recent completions
        if self.recent_completions:
            completions_text = "\n".join(self.recent_completions)
        else:
            completions_text = "[dim]No files completed yet...[/dim]"

        completions_panel = Panel(
            completions_text,
            title="[bold]Recent Completions[/bold]",
            border_style=COLOR_INFO,
            height=8,
            box=box.ROUNDED,
        )

        # Errors panel
        if self.error_list:
            errors_text = "\n".join(self.error_list[-5:])
            error_count = f" ({len(self.error_list)})" if len(self.error_list) > 5 else f" ({len(self.error_list)})"
        else:
            errors_text = "[dim]No errors[/dim]"
            error_count = ""

        errors_panel = Panel(
            errors_text,
            title=f"[bold red]Errors{error_count}[/bold red]",
            border_style=COLOR_ERROR,
            height=6,
            box=box.ROUNDED,
        )

        return Group(progress_table, workers_panel, completions_panel, errors_panel)

    def start(self):
        """Start the live display."""
        # Overall progress
        self.overall_task = self.overall_progress.add_task("Files Processed", total=self.total_files, completed=0)

        # Worker tasks
        for i in range(self.worker_count):
            task_id = self.worker_progress.add_task(f"Worker {i}", total=100, completed=0, status="[dim]idle[/dim]")
            self.worker_tasks[i] = task_id

        self.live = Live(self._make_layout(), console=console, refresh_per_second=10)
        self.live.start()

    def update_worker(self, worker_id: int, status: str, progress: int = 0):
        """Update a worker's status."""
        if worker_id not in self.worker_tasks:
            return
        task_id = self.worker_tasks[worker_id]
        self.worker_progress.update(task_id, completed=progress, status=status)
        # The progress bar updates internally, but we don't need to rebuild the entire layout
        # The auto-refresh will pick up the progress bar changes

    def mark_file_complete(self, filename: str, elapsed: float, tags_written: int):
        """Mark a file as completed."""
        self.files_completed += 1
        if self.overall_task is not None:
            self.overall_progress.update(self.overall_task, completed=self.files_completed)
        self.recent_completions.append(f"[green]✓[/green] {filename} [dim]({elapsed:.1f}s, {tags_written} tags)[/dim]")
        if self.live:
            self.live.update(self._make_layout())
            self.live.refresh()

    def mark_file_failed(self, filename: str, error: str):
        """Mark a file as failed."""
        self.files_failed += 1
        self.files_completed += 1  # Count towards overall completion
        if self.overall_task is not None:
            self.overall_progress.update(self.overall_task, completed=self.files_completed)
        self.error_list.append(f"{filename}: {error}")
        if self.live:
            self.live.update(self._make_layout())
            self.live.refresh()

    def stop(self):
        """Stop the live display."""
        if self.live:
            self.live.stop()


def print_error(message: str):
    """Print an error message."""
    console.print(f"[bold {COLOR_ERROR}]✗[/bold {COLOR_ERROR}] {message}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"[bold {COLOR_WARNING}]⚠[/bold {COLOR_WARNING}] {message}")


def print_info(message: str):
    """Print an info message."""
    console.print(f"[{COLOR_INFO}]ℹ[/{COLOR_INFO}] {message}")
