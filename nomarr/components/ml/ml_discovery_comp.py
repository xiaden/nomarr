#!/usr/bin/env python3
"""
Discovery module - finds and organizes model files using folder structure.
Structure: models/<backbone>/embeddings/*.pb and models/<backbone>/heads/<type>/*.pb
"""

import glob
import json
import os
from dataclasses import dataclass
from typing import Any


class Sidecar:
    """Represents a model sidecar JSON file (head or embedding extractor)."""

    def __init__(self, path: str, data: dict[str, Any]):
        self.path = path
        self.data = data
        self.infer = data.get("inference", {})
        self.schema = data.get("schema", {})
        self.inputs = self.schema.get("inputs", [])
        self.outputs = self.schema.get("outputs", [])

    @property
    def name(self) -> str:
        """Model name from sidecar."""
        return self.data.get("name") or self.data.get("head_name") or os.path.basename(self.path).rsplit(".", 1)[0]

    @property
    def labels(self) -> list[str]:
        """Class labels for classification heads."""
        return list(self.data.get("classes") or self.data.get("labels") or [])

    @property
    def sr(self) -> int:
        """Expected sample rate."""
        explicit = self.data.get("audio", {}).get("sample_rate") or self.infer.get("sample_rate")
        if explicit:
            return int(explicit)
        return 16000

    @property
    def segment_hop(self) -> tuple[float, float]:
        """Segment length and hop for windowed processing."""
        seg = self.data.get("segment", {})
        segment_s = float(seg.get("length_s", seg.get("length", 10.0)))
        hop_s = float(seg.get("hop_s", seg.get("hop", 5.0)))
        return (segment_s, hop_s)

    def graph_abs(self, models_dir: str) -> str | None:
        """Resolve absolute path to the .pb graph file (same dir as JSON)."""
        pb_path = self.path.rsplit(".", 1)[0] + ".pb"
        return pb_path if os.path.exists(pb_path) else None

    def input_dim(self) -> int | None:
        """Expected embedding dimension for heads (from schema.inputs)."""
        try:
            if not self.inputs:
                return None
            shp = self.inputs[0].get("shape")
            if isinstance(shp, list):
                if len(shp) == 1 and isinstance(shp[0], int):
                    return shp[0]
                if len(shp) == 2 and isinstance(shp[1], int):
                    return shp[1]
        except Exception:
            pass
        return None

    def head_output_name(self) -> str | None:
        """Output node name for head predictions (from schema.outputs)."""
        try:
            if not self.outputs:
                return None
            for out in self.outputs:
                purpose = str(out.get("output_purpose") or "").lower()
                if purpose in ("predictions", "logits", "probabilities", "probs"):
                    return str(out.get("name"))
            return str(self.outputs[0].get("name"))
        except Exception:
            return None

    def head_input_name(self) -> str | None:
        """Input node name for head (from schema.inputs)."""
        try:
            if not self.inputs:
                return None
            return str(self.inputs[0].get("name"))
        except Exception:
            return None


@dataclass
class HeadOutput:
    """
    In-memory representation of a head's output with tier information.

    Tier is computed using calibration (if available) but never persisted
    as a *_tier tag. It's only used for mood aggregation and conflict resolution.

    Attributes:
        head: The HeadInfo that produced this output
        model_key: Versioned tag key (no calibration suffix)
        label: Label name (e.g., "happy", "mainstream")
        value: Numeric score (post-calibration if applied)
        tier: Tier level ("low", "medium", "high", etc.) - internal only
        calibration_id: Which calibration was applied (e.g., "none_0", "platt_1")
    """

    head: "HeadInfo"
    model_key: str
    label: str
    value: float
    tier: str | None = None
    calibration_id: str | None = None


class HeadInfo:
    """
    Container for a head model with its associated embedding model info.
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
        is_mood_source: bool = False,
        is_regression_mood_source: bool = False,
    ):
        self.sidecar = sidecar
        self.backbone = backbone
        self.head_type = head_type
        self.embedding_graph = embedding_graph
        self.embedding_sidecar = embedding_sidecar
        # Structured metadata for tagging/aggregation logic
        self.is_mood_source = is_mood_source  # Contributes to mood-* tags
        self.is_regression_mood_source = is_regression_mood_source  # Regression head for mood tiers

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
        self,
        label: str,
        framework_version: str,
        calib_method: str = "none",
        calib_version: int = 0,
    ) -> tuple[str, str]:
        """
        Build versioned tag key from model metadata and runtime framework version.

        NEW FORMAT (calibration separate):
        - model_key: {label}_{framework}{version}_{embedder}{date}_{head}{date}
        - calibration_id: {calib_method}_{calib_version}

        Example:
        - model_key: "happy_essentia21b6dev1389_yamnet20210604_happy20220825"
        - calibration_id: "platt_1"

        Args:
            label: Friendly label (e.g., "happy", "approachable")
            framework_version: Runtime Essentia-TensorFlow version (e.g., "2.1b6.dev1389")
            calib_method: Calibration method ("platt", "isotonic", "none")
            calib_version: Calibration version number

        Returns:
            Tuple of (model_tag_key, calibration_id)
        """
        # Convert framework version to compact form: "2.1b6.dev1389" -> "21b6dev1389"
        # Keep full version including dev/patch suffixes (TF version changes matter)
        fw_short = framework_version.replace(".", "")
        framework_part = f"essentia{fw_short}"

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
    """
    Return the documented output node name for embedding extractors.
    Based on modelsinfo.md examples.
    """
    if backbone == "yamnet":
        return "embeddings"
    if backbone == "vggish":
        return "model/vggish/embeddings"
    if backbone == "effnet":
        return "PartitionedCall:1"
    if backbone == "musicnn":
        return "model/dense/BiasAdd"
    return "embeddings"


def get_head_output_node(head_type: str, sidecar: Sidecar) -> str:
    """
    Return the documented output node name for classification heads.
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


def discover_heads(models_dir: str) -> list[HeadInfo]:
    """
    Discover all classification/regression heads using folder structure.

    Structure expected:
        models/<backbone>/embeddings/*.pb  (or embedding/*.pb for musicnn)
        models/<backbone>/heads/<type>/*.json

    Returns HeadInfo objects with backbone, head_type, and embedding graph resolved.
    Sets is_mood_source and is_regression_mood_source flags based on sidecar metadata.
    """
    heads: list[HeadInfo] = []

    # Known regression heads that feed mood tiers
    REGRESSION_MOOD_HEADS = {"approachability_regression", "engagement_regression"}

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

        embedding_pb_files = glob.glob(os.path.join(embeddings_dir, "*.pb"))
        if not embedding_pb_files:
            continue

        embedding_graph = embedding_pb_files[0]

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
                    head_name = sidecar.name

                    # Determine if this head contributes to mood-* tags
                    # Centralized logic: check for "mood_" in name (case-insensitive)
                    name_normalized = head_name.replace(" ", "_").lower()
                    is_mood_source = "mood_" in name_normalized

                    # Check if this is a regression head that feeds mood tiers
                    is_regression_mood_source = head_name in REGRESSION_MOOD_HEADS

                    head_info = HeadInfo(
                        sidecar=sidecar,
                        backbone=backbone,
                        head_type=head_type,
                        embedding_graph=embedding_graph,
                        embedding_sidecar=embedding_sidecar,
                        is_mood_source=is_mood_source,
                        is_regression_mood_source=is_regression_mood_source,
                    )
                    heads.append(head_info)

                except Exception:
                    continue

    heads.sort(key=lambda h: h.name)
    return heads
