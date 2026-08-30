"""Validate that tagged files have complete nom:* tag coverage for all model heads."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import get_songs_with_incomplete_tags, transition_song_state
from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads
from nomarr.helpers.constants.file_states import STATE_NOT_WRITTEN, STATE_WRITTEN

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def validate_library_tags_workflow(
    db: Database,
    models_dir: str,
    library: Library | None = None,
    namespace: str = "nom",
    auto_repair: bool = True,
) -> dict[str, Any]:
    """Validate per-file completeness of nom:* names for all discovered heads.

    A file with a ``written`` edge is considered *complete* only if it has
    at least one tag edge for every discovered head (model_key + label) under
    the namespace.  Missing any head name marks the file incomplete.  Auto-repair
    removes the ``written`` edge so the file is rediscovered for tag writing.

    Args:
        db: Database instance
        models_dir: Path to ML models
        library: Optional domain ``Library`` to restrict validation scope; when
            None, every written file across all libraries is validated.
        namespace: Tag namespace (default ``"nom"``)
        auto_repair: If True, transition incomplete files back to not_written
            so the tag worker reprocesses them.

    Returns:
        Validation summary dict with files_checked/complete_files/\n        incomplete_files/files_repaired/missing_names_summary/expected_heads/details.

    """
    heads = discover_heads(models_dir, db)
    expected_heads: list[dict[str, Any]] = []
    for head in heads:
        model_key = head.backbone
        expected_heads.append(
            {
                "head_key": f"{model_key}:{head.name}",
                "labels": head.labels,
                # Tag name contains model_key without dashes (see calibration_repo)
                "model_key_for_tag": model_key.replace("-", ""),
            }
        )

    expected_count = len(expected_heads)
    if expected_count == 0:
        return {
            "files_checked": 0,
            "complete_files": 0,
            "incomplete_files": 0,
            "files_repaired": 0,
            "missing_names_summary": {},
            "expected_heads": 0,
        }

    namespace_prefix = f"{namespace}:"

    results = get_songs_with_incomplete_tags(
        db,
        expected_heads=expected_heads,
        namespace_prefix=namespace_prefix,
        library=library,
    )

    incomplete = [r for r in results if r["missing_count"] > 0]
    missing_counter: Counter[str] = Counter()
    for row in incomplete:
        for head_key in row["missing_heads"]:
            missing_counter[head_key] += 1

    repaired = 0
    if auto_repair and incomplete:
        song_ids = [row["file_id"] for row in incomplete]
        transition_song_state(db, song_ids, STATE_WRITTEN, STATE_NOT_WRITTEN)
        repaired = len(incomplete)

    return {
        "files_checked": len(results),
        "complete_files": len(results) - len(incomplete),
        "incomplete_files": len(incomplete),
        "files_repaired": repaired,
        "missing_names_summary": dict(missing_counter),
        "expected_heads": expected_count,
        "details": incomplete,
    }
