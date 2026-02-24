#!/usr/bin/env python3
"""Discovery module - finds and organizes model files using folder structure.
Structure: models/<backbone>/embeddings/*.pb and models/<backbone>/heads/<type>/*.pb.
"""

import glob
import hashlib
import json
import os
from typing import Any

from nomarr.components.ml.ml_onnx_types import MODEL_SUITE_VERSION, Sidecar


class HeadInfo:
    """Container for a head model with its associated embedding model info.
    Derived purely from folder structure.

    Structured metadata eliminates fragile substring matching in tag keys.
    """

    def __init__(
        self,
        sidecar: Sidecar,
        backbone: str,
        head_type: str,
        embedding_graph: str,
        embedding_sidecar: Sidecar | None = None,
        is_regression_head: bool = False,
    ) -> None:
        self.sidecar = sidecar
        self.backbone = backbone
        self.head_type = head_type
        self.embedding_graph = embedding_graph
        self.embedding_sidecar = embedding_sidecar
        self.is_regression_head = is_regression_head  # Regression head for mood tiers

    @property
    def name(self) -> str:
        return self.sidecar.name

    @property
    def kind(self) -> str:
        """Return head kind: 'regression', 'multilabel', 'multiclass', or 'embedding'."""
        # Derive from head_type (folder name: classification, multilabel, regression, etc.)
        head_type_lower = self.head_type.lower()
        if "regression" in head_type_lower:
            return "regression"
        if "multilabel" in head_type_lower:
            return "multilabel"
        if "multiclass" in head_type_lower or "classification" in head_type_lower:
            return "multiclass"
        # Default to multiclass for backward compatibility
        return "multiclass"

    @property
    def labels(self) -> list[str]:
        """Return labels from sidecar."""
        return self.sidecar.labels

    def build_versioned_tag_key(
        self, label: str, calib_method: str = "none", calib_version: int = 0,
    ) -> tuple[str, str]:
        """Build versioned tag key from model metadata and stable suite version.

        Format:
        - model_key: {label}_{suite_version}_{embedder}{date}_{head}{date}
        - calibration_id: {calib_method}_{calib_version}

        The suite version is the module-level MODEL_SUITE_VERSION constant (e.g. "v1"),
        which tracks deployed model weights — not the inference runtime.  Switching
        runtimes (TF → ONNX) does not change the key.

        Example:
        - model_key: "happy_v1_yamnet20210604_happy20220825"
        - calibration_id: "platt_1"

        Args:
            label: Friendly label (e.g., "happy", "approachable")
            calib_method: Calibration method ("platt", "isotonic", "none")
            calib_version: Calibration version number

        Returns:
            Tuple of (model_tag_key, calibration_id)

        """
        # Use stable suite version rather than runtime-library version string
        framework_part = MODEL_SUITE_VERSION

        # Extract embedder release date from embedding sidecar
        embedder_date = "unknown"
        if self.embedding_sidecar:
            embedder_release = self.embedding_sidecar.data.get("release_date", "")
            if embedder_release:
                embedder_date = embedder_release.replace("-", "")  # 2022-08-25 -> 20220825

        # Extract head release date from head sidecar
        head_release = self.sidecar.data.get("release_date", "")
        head_date = head_release.replace("-", "") if head_release else "unknown"

        # Build embedder name (backbone + date)
        embedder_part = f"{self.backbone}{embedder_date}"

        # Build head name (label + date)
        head_part = f"{label}{head_date}"

        # Build model key WITHOUT calibration suffix
        model_key = f"{label}_{framework_part}_{embedder_part}_{head_part}"

        # Build calibration ID separately
        calibration_id = f"{calib_method}_{calib_version}"

        return (model_key, calibration_id)


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


def get_head_output_node(head_type: str, sidecar: Sidecar) -> str:
    """Return the documented output node name for classification heads.
    Based on modelsinfo.md examples and folder structure.
    """
    schema_out = sidecar.head_output_name()
    if schema_out:
        return schema_out

    type_lower = head_type.lower()
    if "identity" in type_lower or "regression" in type_lower:
        return "model/Identity"
    if "softmax" in type_lower or "classification" in type_lower:
        return "model/Softmax"

    return "model/Softmax"


# Known regression heads (output continuous values, not class labels)
_REGRESSION_HEADS = {"approachability_regression", "engagement_regression"}



def discover_backbones(models_dir: str) -> list[str]:
    """Discover available embedding backbones from folder structure.

    A backbone is valid if it has an embeddings/ (or embedding/) subdirectory
    containing at least one .pb graph file.

    Structure expected:
        models/<backbone>/embeddings/*.pb  (or embedding/*.pb for musicnn)

    Args:
        models_dir: Root directory containing model folders

    Returns:
        Sorted list of backbone identifiers (e.g., ["effnet", "musicnn"])

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

        # Verify at least one .onnx or .pb graph file exists (.onnx preferred)
        embedding_graph_files = glob.glob(os.path.join(embeddings_dir, "*.onnx")) or glob.glob(
            os.path.join(embeddings_dir, "*.pb")
        )
        if embedding_graph_files:
            backbones.append(backbone)

    return sorted(backbones)


def discover_heads(models_dir: str) -> list[HeadInfo]:
    """Discover all classification/regression heads using folder structure.

    Structure expected:
        models/<backbone>/embeddings/*.pb  (or embedding/*.pb for musicnn)
        models/<backbone>/heads/<type>/*.json

    Returns HeadInfo objects with backbone, head_type, and embedding graph resolved.
    """
    heads: list[HeadInfo] = []

    for backbone_dir in glob.glob(os.path.join(models_dir, "*")):
        if not os.path.isdir(backbone_dir):
            continue

        backbone = os.path.basename(backbone_dir)

        # Try both "embeddings" (plural) and "embedding" (singular) for compatibility
        embeddings_dir = os.path.join(backbone_dir, "embeddings")
        if not os.path.isdir(embeddings_dir):
            embeddings_dir = os.path.join(backbone_dir, "embedding")

        heads_dir = os.path.join(backbone_dir, "heads")

        if not os.path.isdir(embeddings_dir) or not os.path.isdir(heads_dir):
            continue

        # Prefer .onnx graph files; fall back to .pb for the transition period
        embedding_graph_files = glob.glob(os.path.join(embeddings_dir, "*.onnx")) or glob.glob(
            os.path.join(embeddings_dir, "*.pb")
        )
        if not embedding_graph_files:
            continue

        embedding_graph = embedding_graph_files[0]

        # Load embedding sidecar JSON (for metadata)
        embedding_sidecar = None
        embedding_json = embedding_graph.rsplit(".", 1)[0] + ".json"
        if os.path.exists(embedding_json):
            try:
                with open(embedding_json, encoding="utf-8") as f:
                    embedding_data = json.load(f)
                if isinstance(embedding_data, dict):
                    embedding_sidecar = Sidecar(embedding_json, embedding_data)
            except Exception:
                pass

        for head_type_dir in glob.glob(os.path.join(heads_dir, "*")):
            if not os.path.isdir(head_type_dir):
                continue

            head_type = os.path.basename(head_type_dir)

            for json_path in glob.glob(os.path.join(head_type_dir, "*.json")):
                try:
                    with open(json_path, encoding="utf-8") as f:
                        data = json.load(f)

                    if not isinstance(data, dict):
                        continue

                    sidecar = Sidecar(json_path, data)

                    head_info = HeadInfo(
                        sidecar=sidecar,
                        backbone=backbone,
                        head_type=head_type,
                        embedding_graph=embedding_graph,
                        embedding_sidecar=embedding_sidecar,
                        is_regression_head=sidecar.name in _REGRESSION_HEADS,
                    )
                    heads.append(head_info)

                except Exception:
                    continue

    heads.sort(key=lambda h: h.name)
    return heads


def compute_model_suite_hash(models_dir: str) -> str:
    """Compute a deterministic hash representing the installed ML model suite.

    This hash changes when:
    - Model files are added/removed
    - Model release dates change
    - Backbone or head configurations change

    The hash is computed from sorted (backbone, head_name, release_date) tuples
    to ensure determinism across runs.

    Args:
        models_dir: Directory containing model files

    Returns:
        Short hex hash (12 chars) representing the model suite version.
        Returns "unknown" if no models found or discovery fails.

    """
    try:
        heads = discover_heads(models_dir)
        if not heads:
            return "unknown"

        # Build sorted list of (backbone, head_name, head_release, embedder_release) tuples
        model_signatures: list[tuple[str, str, str, str]] = []

        for head in heads:
            backbone = head.backbone
            head_name = head.name
            head_release = head.sidecar.data.get("release_date", "unknown")

            embedder_release = "unknown"
            if head.embedding_sidecar:
                embedder_release = head.embedding_sidecar.data.get("release_date", "unknown")

            model_signatures.append((backbone, head_name, head_release, embedder_release))

        # Sort for determinism
        model_signatures.sort()

        # Create hash from sorted signatures
        sig_str = "|".join(f"{b}:{n}:{hr}:{er}" for b, n, hr, er in model_signatures)
        full_hash = hashlib.md5(sig_str.encode("utf-8")).hexdigest()

        # Return short hash (12 chars is plenty for version identification)
        return full_hash[:12]

    except Exception:
        return "unknown"



def discover_backbone_models(models_dir: str) -> list[Any]:
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
    from nomarr.components.ml.ml_onnx_backbone import ONNXBackboneModel

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
            ONNXBackboneModel(onnx_path)
            for onnx_path in sorted(glob.glob(os.path.join(embeddings_dir, "*.onnx")))
        )

    models.sort(key=lambda m: m.backbone_name)
    return models


def discover_head_models(models_dir: str) -> list[Any]:
    """Discover head ONNX models and return ready-to-use ONNXHeadModel instances.

    Walks ``models/<backbone>/heads/<type>/*.onnx`` and constructs one
    :class:`ONNXHeadModel` per ``.onnx`` file found.  Labels are read from
    co-located ``.json`` sidecars inside :class:`ONNXHeadModel.__init__`.

    Args:
        models_dir: Root directory containing backbone sub-directories.

    Returns:
        List of :class:`ONNXHeadModel` instances sorted by
        ``(backbone_name, head_type, model_name)``.
    """
    from nomarr.components.ml.ml_onnx_head import ONNXHeadModel

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

            models.extend(
                ONNXHeadModel(onnx_path)
                for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx")))
            )

    models.sort(key=lambda m: (m.backbone_name, m.head_type, m.model_name))
    return models
