#!/usr/bin/env python3
"""Discovery module — finds and organises model files using folder structure.

Structure: ``models/<backbone>/embeddings/*.onnx`` and
``models/<backbone>/heads/<type>/*.onnx``.

When a :class:`~nomarr.persistence.db.Database` is available,
:func:`discover_heads` resolves labels from
``ml_models`` / ``ml_model_outputs`` vertices.  JSON sidecar files are
**not** read at runtime — they are irrelevant for ONNX-only deployments.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.components.ml.onnx.ml_backbone import ONNXBackboneModel
from nomarr.components.ml.onnx.ml_head import ONNXHeadModel
from nomarr.components.ml.onnx.ml_model_registry_comp import (
    list_fully_labeled_model_outputs,
    list_registered_models,
)
from nomarr.helpers.dto.ml_head_dto import HeadInfo

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_embedding_output_node(backbone: str) -> str:
    """Return the ONNX output node name for embedding extractors.

    All Essentia ONNX backbone models expose two outputs: 'activations'
    (classification logits) and 'embeddings' (the penultimate dense layer).
    This is consistent across effnet, musicnn, vggish, and yamnet exports.
    """
    _known = {"yamnet", "vggish", "effnet", "musicnn"}
    if backbone not in _known:
        msg = f"Unknown backbone {backbone!r}: no embedding output node defined"
        raise ValueError(msg)
    return "embeddings"


# Known regression heads (output continuous values, not class labels)
_REGRESSION_HEADS = {"approachability_regression", "engagement_regression"}


def _resolve_embedding_graph(models_dir: str, backbone: str) -> str | None:
    """Find the ONNX embedding graph for *backbone*.

    Checks ``embeddings/`` then ``embedding/`` (musicnn convention).
    Returns the first ``.onnx`` file found, or ``None``.
    """
    backbone_dir = os.path.join(models_dir, backbone)
    for embed_folder in ("embeddings", "embedding"):
        embed_dir = os.path.join(backbone_dir, embed_folder)
        if not os.path.isdir(embed_dir):
            continue
        onnx_files = sorted(glob.glob(os.path.join(embed_dir, "*.onnx")))
        if onnx_files:
            return onnx_files[0]
    return None


def discover_backbones(models_dir: str) -> list[str]:
    """Discover available embedding backbones from folder structure.

    A backbone is valid if it has an ``embeddings/`` (or ``embedding/``)
    subdirectory containing at least one ``.onnx`` graph file.

    Structure expected::

        models/<backbone>/embeddings/*.onnx  (or embedding/*.onnx for musicnn)

    Args:
        models_dir: Root directory containing model folders

    Returns:
        Sorted list of backbone identifiers (e.g., ``["effnet", "musicnn"]``)

    """
    backbones: list[str] = []

    for backbone_dir in glob.glob(os.path.join(models_dir, "*")):
        if not os.path.isdir(backbone_dir):
            continue

        backbone = os.path.basename(backbone_dir)

        # Try both "embeddings" (plural) and "embedding" (singular) for compatibility
        embeddings_dir = os.path.join(backbone_dir, "embeddings")
        if not os.path.isdir(embeddings_dir):
            embeddings_dir = os.path.join(backbone_dir, "embedding")

        if not os.path.isdir(embeddings_dir):
            continue

        # Require at least one .onnx graph file
        if glob.glob(os.path.join(embeddings_dir, "*.onnx")):
            backbones.append(backbone)

    return sorted(backbones)


# ---------------------------------------------------------------------------
# discover_heads — DB-first with filesystem fallback
# ---------------------------------------------------------------------------


def _discover_heads_from_db(models_dir: str, db: Database) -> list[HeadInfo]:
    """Build :class:`HeadInfo` objects from ``ml_models`` / ``ml_model_outputs``.

    Only models with ``fully_configured=True`` are returned.  Embedding
    graph paths are resolved from the filesystem so that the returned
    objects are ready for inference.
    """
    heads: list[HeadInfo] = []
    all_models = list_registered_models(db)

    for doc in all_models:
        if not doc.get("fully_configured", False):
            continue

        backbone: str = doc["backbone"]
        head_type: str = doc["head_type"]
        model_stem: str = doc["model_stem"]
        model_path: str = doc["path"]

        embedding_graph = _resolve_embedding_graph(models_dir, backbone)
        if not embedding_graph:
            logger.warning(
                "Skipping %s: no embedding graph found for backbone %s",
                model_stem,
                backbone,
            )
            continue

        # Labels from fully-labeled output vertices
        model_id: str = doc["_id"]
        output_docs = list_fully_labeled_model_outputs(db, model_id)
        labels = [od["label"] for od in output_docs]

        heads.append(
            HeadInfo(
                name=model_stem,
                labels=labels,
                backbone=backbone,
                head_type=head_type,
                model_stem=model_stem,
                model_path=model_path,
                embedding_graph=embedding_graph,
                is_regression_head=model_stem in _REGRESSION_HEADS,
            )
        )

    heads.sort(key=lambda h: h.name)
    return heads


def discover_heads_no_db(models_dir: str) -> list[HeadInfo]:
    """Discover heads WITHOUT a database by walking ``*.onnx`` files.

    **For capacity probing and model-suite hashing only.**  Returns
    :class:`HeadInfo` objects with empty labels — label data requires a
    live database.  Inference-path code must use :func:`discover_heads`
    with a real :class:`Database` handle.

    JSON sidecar files are **not** read; they do not exist for ONNX-only
    deployments.
    """
    heads: list[HeadInfo] = []

    for backbone_dir in sorted(glob.glob(os.path.join(models_dir, "*"))):
        if not os.path.isdir(backbone_dir):
            continue

        backbone = os.path.basename(backbone_dir)

        embedding_graph = _resolve_embedding_graph(models_dir, backbone)
        if not embedding_graph:
            continue

        heads_dir = os.path.join(backbone_dir, "heads")
        if not os.path.isdir(heads_dir):
            continue

        for head_type_dir in sorted(glob.glob(os.path.join(heads_dir, "*"))):
            if not os.path.isdir(head_type_dir):
                continue

            head_type = os.path.basename(head_type_dir)

            for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx"))):
                model_stem = os.path.splitext(os.path.basename(onnx_path))[0]
                heads.append(
                    HeadInfo(
                        name=model_stem,
                        labels=[],
                        backbone=backbone,
                        head_type=head_type,
                        model_stem=model_stem,
                        model_path=onnx_path,
                        embedding_graph=embedding_graph,
                    )
                )

    heads.sort(key=lambda h: h.name)
    return heads


def discover_heads(
    models_dir: str,
    db: Database,
) -> list[HeadInfo]:
    """Discover all classification/regression heads from the database.

    Queries ``ml_models`` (filtered to ``fully_configured=True``) and
    ``ml_model_outputs`` for labels, producing a list of
    :class:`HeadInfo` objects ready for inference.

    Use :func:`discover_heads_no_db` for capacity-probe / hashing paths
    that do not have access to a database handle.

    Args:
        models_dir: Root directory containing model folders.
        db: Database handle.  Required.

    Returns:
        Sorted list of :class:`HeadInfo` objects.

    """
    return _discover_heads_from_db(models_dir, db)


def filter_configured_heads(
    heads: list[HeadInfo],
    model_config: dict[str, tuple[bool, int]],
) -> list[HeadInfo]:
    """Filter heads to only those with fully-configured model registrations.

    Compares each head's ``model_stem`` against the *model_config* lookup
    built from ``ml_models`` documents.  Heads whose model is not
    fully configured (missing labels) are dropped with a warning.

    .. note::

       When :func:`discover_heads` is called with a *db* handle the
       returned heads are *already* filtered to ``fully_configured``.
       This helper is only needed for the filesystem-fallback path.

    Args:
        heads: Discovered heads from :func:`discover_heads`.
        model_config: Mapping of ``model_stem`` to
            ``(fully_configured, output_count)`` built from
            ``list_registered_models(db)``.

    Returns:
        Filtered list containing only heads with fully-configured models.

    """
    configured: list[HeadInfo] = []
    for head in heads:
        info = model_config.get(head.model_stem)
        if info is None:
            logger.warning(
                "Skipping head %s: no ml_models registration found",
                head.name,
            )
            continue
        fully_configured, output_count = info
        if not fully_configured:
            logger.warning(
                "Skipping head %s: model not fully configured (%d output(s) need labeling via UI)",
                head.name,
                output_count,
            )
            continue
        configured.append(head)
    return configured


def compute_model_suite_hash(
    models_dir: str,
) -> str:
    """Compute a deterministic hash representing the installed ML model suite.

    This hash changes when:
    - Model files are added/removed
    - A model file is replaced with different weights (file size changes)

    Hashes sorted ``(relative_path, file_size)`` tuples for every ``*.onnx``
    file under *models_dir*.  No database connection or sidecar files required.

    Args:
        models_dir: Directory containing model files.

    Returns:
        Short hex hash (12 chars) representing the model suite version.
        Returns ``"unknown"`` if no models found or discovery fails.

    """
    try:
        entries: list[tuple[str, int]] = []
        for root, _dirs, files in sorted(os.walk(models_dir)):
            for filename in sorted(files):
                if filename.endswith(".onnx"):
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, models_dir)
                    entries.append((rel_path, os.path.getsize(filepath)))
        if not entries:
            return "unknown"
        sig_str = "|".join(f"{p}:{s}" for p, s in entries)
        return hashlib.md5(sig_str.encode("utf-8")).hexdigest()[:12]

    except Exception:
        return "unknown"


def discover_backbone_models(models_dir: str) -> list[ONNXBackboneModel]:
    """Discover backbone ONNX models and return ready-to-use ONNXBackboneModel instances.

    Walks ``models/<backbone>/embeddings/*.onnx`` (``embedding/`` variant for
    musicnn) and constructs one :class:`ONNXBackboneModel` per ``.onnx`` file
    found.  Only ``.onnx`` files are considered — ``.pb`` falls outside the
    scope of the new model classes.

    Args:
        models_dir: Root directory containing backbone sub-directories.

    Returns:
        List of :class:`ONNXBackboneModel` instances sorted by backbone name.
    """
    models: list[ONNXBackboneModel] = []

    for backbone_dir in glob.glob(os.path.join(models_dir, "*")):
        if not os.path.isdir(backbone_dir):
            continue

        # Try both "embeddings" (plural) and "embedding" (singular for musicnn)
        embeddings_dir = os.path.join(backbone_dir, "embeddings")
        if not os.path.isdir(embeddings_dir):
            embeddings_dir = os.path.join(backbone_dir, "embedding")

        if not os.path.isdir(embeddings_dir):
            continue

        models.extend(
            ONNXBackboneModel(onnx_path) for onnx_path in sorted(glob.glob(os.path.join(embeddings_dir, "*.onnx")))
        )

    models.sort(key=lambda m: m.backbone_name)
    return models


def discover_head_models_no_db(models_dir: str) -> list[ONNXHeadModel]:
    """Discover head ONNX models with empty labels — no database required.

    Walks ``models/<backbone>/heads/<type>/*.onnx`` and constructs one
    :class:`ONNXHeadModel` per ``.onnx`` file found, with empty labels.

    **For VRAM probing and capacity checks only.**  Inference-path code
    must use :func:`discover_head_models` with a real database handle.

    Args:
        models_dir: Root directory containing backbone sub-directories.

    Returns:
        List of :class:`ONNXHeadModel` instances sorted by
        ``(meta.backbone, meta.head_type, meta.model_stem)``.
    """
    models: list[ONNXHeadModel] = []

    for backbone_dir in glob.glob(os.path.join(models_dir, "*")):
        if not os.path.isdir(backbone_dir):
            continue

        heads_dir = os.path.join(backbone_dir, "heads")
        if not os.path.isdir(heads_dir):
            continue

        for head_type_dir in sorted(glob.glob(os.path.join(heads_dir, "*"))):
            if not os.path.isdir(head_type_dir):
                continue

            backbone = os.path.basename(backbone_dir)
            head_type = os.path.basename(head_type_dir)

            for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx"))):
                model_stem = Path(onnx_path).stem
                meta = HeadInfo(
                    name=model_stem,
                    labels=[],
                    backbone=backbone,
                    head_type=head_type,
                    model_stem=model_stem,
                    model_path=onnx_path,
                    embedding_graph="",
                    is_regression_head=model_stem in _REGRESSION_HEADS,
                )
                models.append(ONNXHeadModel(onnx_path, meta=meta))

    models.sort(key=lambda m: (m.meta.backbone, m.meta.head_type, m.meta.model_stem))
    return models


def discover_head_models(
    models_dir: str,
    db: Database,
) -> list[ONNXHeadModel]:
    """Discover head ONNX models with labels sourced from the database.

    Walks ``models/<backbone>/heads/<type>/*.onnx`` and constructs one
    :class:`ONNXHeadModel` per ``.onnx`` file found. Labels are injected
    from the database via :func:`discover_heads`.

    Use :func:`discover_head_models_no_db` for VRAM probing and capacity
    checks that do not require label data.

    Args:
        models_dir: Root directory containing backbone sub-directories.
        db: Database handle.  Required for label injection.

    Returns:
        List of :class:`ONNXHeadModel` instances sorted by
        ``(meta.backbone, meta.head_type, meta.model_stem)``.
    """
    # Build metadata lookup from HeadInfo (DB-backed).
    head_info_map: dict[tuple[str, str, str], HeadInfo] = {}
    try:
        heads = discover_heads(models_dir, db)
        for hi in heads:
            key = (hi.backbone, hi.head_type, hi.model_stem)
            head_info_map[key] = hi
    except Exception:
        logger.warning("Failed to load HeadInfo from DB; labels will be empty")

    models: list[ONNXHeadModel] = []

    for backbone_dir in glob.glob(os.path.join(models_dir, "*")):
        if not os.path.isdir(backbone_dir):
            continue

        heads_dir = os.path.join(backbone_dir, "heads")
        if not os.path.isdir(heads_dir):
            continue

        for head_type_dir in sorted(glob.glob(os.path.join(heads_dir, "*"))):
            if not os.path.isdir(head_type_dir):
                continue
            backbone = os.path.basename(backbone_dir)
            head_type = os.path.basename(head_type_dir)

            for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx"))):
                stem = Path(onnx_path).stem
                info = head_info_map.get((backbone, head_type, stem))
                if info is None:
                    info = HeadInfo(
                        name=stem,
                        labels=[],
                        backbone=backbone,
                        head_type=head_type,
                        model_stem=stem,
                        model_path=onnx_path,
                        embedding_graph="",
                        is_regression_head=stem in _REGRESSION_HEADS,
                    )
                model = ONNXHeadModel(
                    onnx_path,
                    meta=info,
                )
                models.append(model)

    models.sort(key=lambda m: (m.meta.backbone, m.meta.head_type, m.meta.model_stem))
    return models
