"""Shared dataclasses used across multiple layers.

This file is reserved for truly cross-domain dataclasses shared by multiple domains.
For domain-specific DTOs, use helpers/dto/<domain>.py instead.

Rules:
- Only put a dataclass here if it is imported from more than one top-level package
  AND is genuinely cross-domain (not specific to Navidrome, processing, etc.)
- Dataclasses here must be pure: no methods with behavior, no I/O, no config loading.
- Only import standard library modules (e.g. dataclasses, typing).
- Do NOT import from nomarr.services, nomarr.workflows, nomarr.ml, nomarr.tagging,
  nomarr.persistence, or nomarr.interfaces.
- If a dataclass is only imported from a single module or package, keep it local
  to that layer instead of moving it here.

For domain-specific DTOs:
- Navidrome DTOs → helpers/dto/navidrome.py
- Processing DTOs → helpers/dto/processing.py
- Other domains → helpers/dto/<domain>.py
"""

from __future__ import annotations

# Currently no cross-domain dataclasses.
# Add them here only if they are genuinely shared across multiple domains.
