"""ML edge write DTOs.

Data transfer objects for ML graph edge writes (tag_model_output).
Split from processing_dto to avoid coupling generic file-write DTOs
to ML graph-specific edge structures.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MLEdgeWrites:
    """Payload for writing tag→output edges to the tag_model_output collection.

    Carries the mapping from tag rel-key to ``(output_id, raw_score)`` pairs
    collected during ML inference.  Separated from :class:`DeferredFileWrites`
    so that generic per-file write DTOs carry no dependency on ML graph
    concepts.

    Attributes:
        output_edges: Mapping of tag rel-key (e.g. ``"nom:mood-strict"``) to
            a ``(output_id, raw_score)`` tuple, where *output_id* is the
            ArangoDB ``_id`` of the ``ml_model_outputs`` vertex and *raw_score*
            is the activation score that produced this tag.

    """

    output_edges: dict[str, tuple[str, float]]  # tag_rel -> (output_id, raw_score)
