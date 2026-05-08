"""Register ONNX head models and seed missing known labels at startup.

Walks the models directory for ``*.onnx`` files under
``<backbone>/heads/<type>/``, introspects each session for output shape,
upserts model and output vertices, and seeds missing labels for known shipped
models without clobbering existing user edits.

JSON sidecar files are **not** read.  Release dates are stored as empty
strings; they do not exist for ONNX-only deployments.
"""

from __future__ import annotations

import glob
import logging
import os
from typing import TYPE_CHECKING, cast

from nomarr.components.ml.onnx.ml_head import head_parts_from_path
from nomarr.components.ml.onnx.ml_known_models_comp import get_known_outputs
from nomarr.components.ml.onnx.ml_model_registry_comp import (
    ensure_model_outputs,
    list_fully_labeled_model_outputs,
    list_registered_models,
    mark_model_fully_configured,
    mark_model_known,
    prune_registered_model,
    update_model_output_label,
    upsert_registered_model,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def register_ml_models_workflow(
    db: Database,
    models_dir: str,
) -> None:
    """Walk the models directory and register all ONNX head models.

    For each ``*.onnx`` file found under ``models/<backbone>/heads/<type>/``:

    1. Parse path metadata (backbone, head type, model stem)
    2. Introspect ONNX session for output dimension count
    3. Upsert model vertex into ``ml_models``
    4. Ensure output vertices exist in ``ml_model_outputs``
    5. Seed missing labels from known defaults if the model is shipped by nomarr

    Models with all outputs labeled are marked ``fully_configured=True``.
    Unknown models remain unconfigured until the user labels them via UI.

    Args:
        db: Database instance with ml_models and ml_model_outputs operations.
        models_dir: Root path to the ML models directory.

    """
    import onnxruntime as ort

    onnx_pattern = os.path.join(models_dir, "*", "heads", "*", "*.onnx")
    onnx_paths = sorted(glob.glob(onnx_pattern))

    if not onnx_paths:
        logger.warning("No ONNX head models found in %s — check models_dir configuration", models_dir)
        return

    logger.info("Registering %d ONNX head model(s)", len(onnx_paths))

    for onnx_path in onnx_paths:
        # Step 1: Parse path metadata
        backbone, head_type, model_stem = head_parts_from_path(onnx_path)

        # Step 2: Introspect ONNX session for output count
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        output_shape = session.get_outputs()[0].shape
        output_count = int(output_shape[-1])

        # Step 3: Upsert model vertex
        known_outputs = get_known_outputs(model_stem)
        source = "known" if known_outputs is not None else "discovered"
        model_doc = upsert_registered_model(
            db,
            path=onnx_path,
            backbone=backbone,
            head_type=head_type,
            model_stem=model_stem,
            output_count=output_count,
            source=source,
        )
        model_id: str = model_doc["_id"]

        # Step 4: Ensure output vertices exist
        outputs = ensure_model_outputs(db, model_id, output_count)

        # Step 5: Seed missing labels for known shipped models
        if known_outputs is not None:
            for output_index, label in known_outputs:
                output_doc = outputs[output_index]
                if output_doc.get("fully_labeled", False):
                    continue
                update_model_output_label(db, output_id=output_doc["_id"], label=label)
            fully_labeled = list_fully_labeled_model_outputs(db, model_id)
            if len(fully_labeled) == output_count:
                mark_model_fully_configured(db, model_id, value=True)
                logger.debug(
                    "Model %s: known, %d/%d outputs labeled, fully_configured=True",
                    model_stem,
                    len(fully_labeled),
                    output_count,
                )
            else:
                logger.warning(
                    "Model %s: labeled %d/%d outputs — not marking fully_configured"
                    " (KNOWN_MODELS may be out of date with actual output_count)",
                    model_stem,
                    len(fully_labeled),
                    output_count,
                )
            mark_model_known(db, model_id, value=True)
        else:
            logger.warning(
                "Model %s: unknown, %d outputs need labeling via UI",
                model_stem,
                output_count,
            )

    # Prune stale model vertices — models in DB whose ONNX file no longer exists
    discovered_paths: set[str] = set(onnx_paths)
    all_registered = list_registered_models(db)
    stale_models = [m for m in all_registered if m["path"] not in discovered_paths]
    for stale in stale_models:
        stale_id: str = stale["_id"]
        stale_path: str = stale["path"]
        prune_result = prune_registered_model(db, stale_id)
        output_ids = cast("list[str]", prune_result["output_ids"])
        edge_count = cast("int", prune_result["tag_model_output_edges_deleted"])
        logger.warning(
            "Pruned stale model %s: removed %d output(s) and %d edge(s)",
            stale_path,
            len(output_ids),
            edge_count,
        )

    logger.info("Model registration complete")
