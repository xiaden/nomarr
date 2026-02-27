"""Register ONNX head models and seed known labels at startup.

Walks the models directory for ``*.onnx`` files under
``<backbone>/heads/<type>/``, introspects each session for output shape,
upserts model and output vertices, and seeds labels for known shipped models.

Release dates are read from co-located JSON sidecars (one-time at
registration) and stored on the ``ml_models`` vertex so that the
inference pipeline never needs to touch sidecar files.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from typing import TYPE_CHECKING

from nomarr.components.ml.ml_known_models import get_known_outputs
from nomarr.components.ml.ml_onnx_head import _head_parts_from_path

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _read_sidecar_date(json_path: str) -> str:
    """Read ``release_date`` from a JSON sidecar file.

    Args:
        json_path: Absolute path to the ``.json`` sidecar.

    Returns:
        ISO date string (e.g. ``"2022-08-25"``) or empty string
        if the file is missing, unreadable, or lacks the key.

    """
    try:
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return str(data.get("release_date", ""))
    except Exception:
        pass
    return ""


def _find_embedder_release_date(onnx_head_path: str) -> str:
    """Resolve the backbone sidecar and return its ``release_date``.

    Given a head path like ``models/<backbone>/heads/<type>/model.onnx``,
    navigates to ``models/<backbone>/embeddings/*.json`` (or the
    ``embedding/`` variant) and reads the first sidecar found.

    """
    head_dir = os.path.dirname(onnx_head_path)          # …/heads/<type>
    heads_dir = os.path.dirname(head_dir)                # …/heads
    backbone_dir = os.path.dirname(heads_dir)            # …/<backbone>

    for embed_folder in ("embeddings", "embedding"):
        embed_dir = os.path.join(backbone_dir, embed_folder)
        if not os.path.isdir(embed_dir):
            continue
        for jf in sorted(glob.glob(os.path.join(embed_dir, "*.json"))):
            date = _read_sidecar_date(jf)
            if date:
                return date
    return ""


def register_ml_models_workflow(
    db: Database,
    models_dir: str,
) -> None:
    """Walk the models directory and register all ONNX head models.

    For each ``*.onnx`` file found under ``models/<backbone>/heads/<type>/``:

    1. Parse path metadata (backbone, head type, model stem)
    2. Introspect ONNX session for output dimension count
    3. Read release dates from co-located JSON sidecars
    4. Upsert model vertex into ``ml_models``
    5. Ensure output vertices exist in ``ml_model_outputs``
    6. Seed labels from known defaults if the model is shipped by nomarr

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
        backbone, head_type, model_stem = _head_parts_from_path(onnx_path)

        # Step 2: Introspect ONNX session for output count
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        output_shape = session.get_outputs()[0].shape
        output_count = int(output_shape[-1])

        # Step 3: Read release dates from JSON sidecars
        head_json = os.path.splitext(onnx_path)[0] + ".json"
        head_release_date = _read_sidecar_date(head_json)
        embedder_release_date = _find_embedder_release_date(onnx_path)

        # Step 4: Upsert model vertex
        known_outputs = get_known_outputs(model_stem)
        source = "known" if known_outputs is not None else "discovered"
        model_doc = db.ml_models.upsert_model(
            path=onnx_path,
            backbone=backbone,
            head_type=head_type,
            model_stem=model_stem,
            output_count=output_count,
            source=source,
            head_release_date=head_release_date,
            embedder_release_date=embedder_release_date,
        )
        model_id: str = model_doc["_id"]

        # Step 5: Ensure output vertices exist
        outputs = db.ml_model_outputs.upsert_outputs(model_id, output_count)

        # Step 6: Seed labels for known shipped models
        if known_outputs is not None:
            for output_index, label, is_positive, display_hint in known_outputs:
                output_doc = outputs[output_index]
                db.ml_model_outputs.update_label(
                    output_id=output_doc["_id"],
                    label=label,
                    is_positive=is_positive,
                    display_hint=display_hint,
                )
            fully_labeled = db.ml_model_outputs.get_fully_labeled_outputs(model_id)
            if len(fully_labeled) == output_count:
                db.ml_models.set_fully_configured(model_id, value=True)
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
            db.ml_models.set_is_known(model_id, value=True)
        else:
            logger.warning(
                "Model %s: unknown, %d outputs need labeling via UI",
                model_stem,
                output_count,
            )

    # Prune stale model vertices — models in DB whose ONNX file no longer exists
    discovered_paths: set[str] = set(onnx_paths)
    all_registered = db.ml_models.list_models()
    stale_models = [m for m in all_registered if m["path"] not in discovered_paths]
    for stale in stale_models:
        stale_id: str = stale["_id"]
        stale_path: str = stale["path"]
        output_docs = db.ml_model_outputs.get_outputs_for_model(stale_id)
        output_ids = [o["_id"] for o in output_docs]
        edge_count = db.tag_model_output.delete_edges_for_outputs(output_ids)
        db.ml_model_outputs.delete_outputs_for_model(stale_id)
        db.ml_models.delete_model(stale_id)
        logger.warning(
            "Pruned stale model %s: removed %d output(s) and %d edge(s)",
            stale_path,
            len(output_ids),
            edge_count,
        )

    logger.info("Model registration complete")
