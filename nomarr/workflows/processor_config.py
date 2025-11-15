"""
Configuration dataclass for audio processing pipeline.

This separates configuration from the core processing logic,
enabling dependency injection and clearer testing.
"""

from __future__ import annotations

from dataclasses import dataclass


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
