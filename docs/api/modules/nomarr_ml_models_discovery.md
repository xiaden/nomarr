# nomarr.ml.models.discovery

API reference for `nomarr.ml.models.discovery`.

---

## Classes

### HeadInfo

Container for a head model with its associated embedding model info.

**Methods:**

- `__init__(self, sidecar: nomarr.ml.models.discovery.Sidecar, backbone: str, head_type: str, embedding_graph: str, embedding_sidecar: nomarr.ml.models.discovery.Sidecar | None = None, is_mood_source: bool = False, is_regression_mood_source: bool = False)`
- `build_versioned_tag_key(self, label: str, framework_version: str, calib_method: str = 'none', calib_version: int = 0) -> tuple[str, str]`

### HeadOutput

In-memory representation of a head's output with tier information.

**Methods:**

- `__init__(self, head: 'HeadInfo', model_key: str, label: str, value: float, tier: str | None = None, calibration_id: str | None = None) -> None`

### Sidecar

Represents a model sidecar JSON file (head or embedding extractor).

**Methods:**

- `__init__(self, path: str, data: dict[str, typing.Any])`
- `graph_abs(self, models_dir: str) -> str | None`
- `head_input_name(self) -> str | None`
- `head_output_name(self) -> str | None`
- `input_dim(self) -> int | None`

---

## Functions

### discover_heads(models_dir: str) -> list[nomarr.ml.models.discovery.HeadInfo]

Discover all classification/regression heads using folder structure.

### get_embedding_output_node(backbone: str) -> str

Return the documented output node name for embedding extractors.

### get_head_output_node(head_type: str, sidecar: nomarr.ml.models.discovery.Sidecar) -> str

Return the documented output node name for classification heads.

---
