"""
Shared dataclasses used across multiple layers.

Rules:
- Only put a dataclass here if it is imported from more than one top-level package
  (e.g. services + workflows, workflows + interfaces, etc.).
- Dataclasses here must be pure: no methods with behavior, no I/O, no config loading.
- Only import standard library modules (e.g. dataclasses, typing).
- Do NOT import from nomarr.services, nomarr.workflows, nomarr.ml, nomarr.tagging,
  nomarr.persistence, or nomarr.interfaces.
- If a dataclass is only imported from a single module or package, keep it local
  to that layer instead of moving it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class TagWriteProfile:
    """
    Controls what tags are written to media files vs stored only in DB.

    Similar to a logging level - allows configuration-driven control over
    tag verbosity in media files.

    Attributes:
        file_write_mode: Controls tag writing to media files:
            - "none": No tags written to files (DB only)
            - "minimal": Only high-level summary tags (mood-*, genre, etc.)
            - "full": Rich tag set including numeric scores (but never *_tier or calibration)
    """

    file_write_mode: Literal["none", "minimal", "full"] = "minimal"


@dataclass
class ProcessorConfig:
    """
    Configuration for the audio processing pipeline.

    All fields are required to ensure explicit configuration.
    Validation should happen at the service layer when constructing this.
    """

    # Path to models directory containing embeddings and heads
    models_dir: str

    # Minimum audio duration in seconds
    min_duration_s: int

    # Allow processing files shorter than min_duration_s
    allow_short: bool

    # Batch size for head prediction (VRAM control)
    batch_size: int

    # Whether to overwrite existing tags
    overwrite_tags: bool

    # Tag namespace (e.g., "essentia")
    namespace: str

    # Key name for the version tag
    version_tag_key: str

    # Current tagger version string
    tagger_version: str

    # Whether to load calibration files
    calibrate_heads: bool

    # File write mode: controls what tags go to media files
    file_write_mode: Literal["none", "minimal", "full"] = "minimal"


@dataclass(frozen=True)
class LibraryPath:
    """
    Represents a file path with library context.

    Provides clean separation between absolute paths (for operations),
    library association (for ownership), and relative paths (for display).

    All paths are normalized and resolved to canonical form.

    Attributes:
        absolute: Absolute filesystem path (canonical, normalized)
        library_id: ID of owning library
        library_root: Absolute path to library root

    Examples:
        >>> lp = LibraryPath(absolute="/music/rock/song.mp3", library_id=1, library_root="/music")
        >>> lp.relative
        'rock/song.mp3'
    """

    absolute: str
    library_id: int
    library_root: str

    @property
    def relative(self) -> str:
        """Get path relative to library root for display/UI purposes."""
        return str(Path(self.absolute).relative_to(self.library_root))

    def __post_init__(self) -> None:
        """Validate that absolute path is within library_root."""
        abs_path = Path(self.absolute)
        root_path = Path(self.library_root)

        # Ensure absolute is actually within library_root
        try:
            abs_path.relative_to(root_path)
        except ValueError as e:
            raise ValueError(f"Path {self.absolute} is not within library root {self.library_root}") from e
