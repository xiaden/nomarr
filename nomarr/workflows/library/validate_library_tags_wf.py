"""Validate that tagged files have complete nom:* tag coverage for all model heads."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def validate_library_tags_workflow(
    db: Database,
    models_dir: str,
    library_id: str | None = None,
    namespace: str = "nom",
    auto_repair: bool = True,
) -> dict[str, Any]:
    """Validate per-file completeness of nom:* rels for all discovered heads.

    A file with a ``tagged`` edge is considered *complete* only if it has
    at least one tag edge for every discovered head (model_key + label) under
    the namespace.  Missing any head rel marks the file incomplete.  Auto-repair
    removes the ``tagged`` edge so the file is rediscovered for tagging.
    """
    heads = discover_heads(models_dir, db)
    expected_heads: list[dict[str, Any]] = []
    for head in heads:
        model_key = head.backbone
        expected_heads.append(
            {
                "head_key": f"{model_key}:{head.name}",
                "labels": head.labels,
                # Tag rel contains model_key without dashes (see calibration_state_aql)
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
            "missing_rels_summary": {},
            "expected_heads": 0,
        }

    namespace_prefix = f"{namespace}:"

    results = db.file_states.get_files_with_incomplete_tags(
        expected_heads=expected_heads,
        namespace_prefix=namespace_prefix,
        library_id=library_id,
    )

    incomplete = [r for r in results if r["missing_count"] > 0]
    missing_counter: Counter[str] = Counter()
    for row in incomplete:
        for head_key in row["missing_heads"]:
            missing_counter[head_key] += 1

    repaired = 0
    if auto_repair and incomplete:
        file_ids = [row["file_id"] for row in incomplete]
        db.file_states.clear_tagged_batch(file_ids)
        repaired = len(incomplete)

    return {
        "files_checked": len(results),
        "complete_files": len(results) - len(incomplete),
        "incomplete_files": len(incomplete),
        "files_repaired": repaired,
        "missing_rels_summary": dict(missing_counter),
        "expected_heads": expected_count,
        "details": incomplete,
    }
