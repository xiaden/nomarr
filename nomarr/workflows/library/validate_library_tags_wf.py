"""Validate that tagged files have complete nom:* tag coverage for all model heads."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.ml_discovery_comp import discover_heads

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

    A file marked tagged is considered *complete* only if it has at least one
    tag edge for every discovered head (model_key + label) under the namespace.
    Missing any head rel marks the file incomplete. Auto-repair marks incomplete
    files ``needs_tagging=true`` to trigger full reprocessing on the next scan.
    """
    heads = discover_heads(models_dir)
    expected_heads: list[dict[str, Any]] = []
    for head in heads:
        embedder_date = "unknown"
        if head.embedding_sidecar:
            embedder_release = head.embedding_sidecar.data.get("release_date", "")
            if embedder_release:
                embedder_date = embedder_release.replace("-", "")

        model_key = f"{head.backbone}-{embedder_date}"
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
    filter_library_clause = ""
    bind_vars: dict[str, Any] = {
        "namespace_prefix": namespace_prefix,
        "expected_heads": expected_heads,
    }
    if library_id:
        filter_library_clause = "FILTER file.library_id == @library_id"
        bind_vars["library_id"] = library_id

    query = f"""
    LET expected = @expected_heads
    FOR file IN library_files
      FILTER file.tagged == true
      FILTER file.is_valid == true
      {filter_library_clause}
      LET matched_heads = UNIQUE(
        FOR edge IN song_tag_edges
          FILTER edge._from == file._id
          LET tag = DOCUMENT(edge._to)
          FILTER tag != null
          FILTER STARTS_WITH(tag.rel, @namespace_prefix)
          LET rel_without_prefix = SUBSTRING(tag.rel, 4)
          LET first_underscore = FIND_FIRST(rel_without_prefix, "_")
          LET label = first_underscore >= 0 ? SUBSTRING(rel_without_prefix, 0, first_underscore) : rel_without_prefix
          FOR exp IN expected
            FILTER label IN exp.labels
            FILTER CONTAINS(rel_without_prefix, exp.model_key_for_tag)
            RETURN exp.head_key
      )
      LET missing_heads = (
        FOR exp IN expected
          FILTER exp.head_key NOT IN matched_heads
          RETURN exp.head_key
      )
      RETURN {{
        file_id: file._id,
        file_key: file._key,
        library_id: file.library_id,
        matched_count: LENGTH(matched_heads),
        missing_count: LENGTH(missing_heads),
        missing_heads: missing_heads
      }}
    """

    cursor = db.db.aql.execute(query, bind_vars=bind_vars)
    results = list(cursor)

    incomplete = [r for r in results if r["missing_count"] > 0]
    missing_counter: Counter[str] = Counter()
    for row in incomplete:
        for head_key in row["missing_heads"]:
            missing_counter[head_key] += 1

    repaired = 0
    if auto_repair and incomplete:
        repair_query = """
        FOR file_id IN @file_ids
          UPDATE PARSE_IDENTIFIER(file_id).key WITH {
            tagged: false,
            needs_tagging: true,
            tagged_version: null,
            last_tagged_at: null
          } IN library_files
        """
        db.db.aql.execute(
            repair_query,
            bind_vars={"file_ids": [row["file_id"] for row in incomplete]},
        )
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
