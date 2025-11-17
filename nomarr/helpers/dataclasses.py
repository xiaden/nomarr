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
