"""ONNXModelCache: grouped, warmable container for all discovered ONNX models.

The cache owns all backbone and head models for a given models directory.  It
discoveries models at construction time and provides two high-level controls:

- ``cache.warm = True/False`` — load or unload all ONNX sessions atomically.
- ``cache.device = "cpu"/"gpu"`` — transition all sessions to a new device;
  if the cache is warm, unloads and reloads them; otherwise just stores the
  device for the next warm cycle.

Workers own :class:`ONNXModelCache` instances, not the service layer.  Idle
eviction is implemented by the worker setting ``cache.warm = False``.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from nomarr.components.ml.ml_discovery_comp import (
    discover_backbone_models,
    discover_head_models,
)
from nomarr.components.ml.ml_onnx_backbone import ONNXBackboneModel
from nomarr.components.ml.ml_onnx_base import BaseONNXModel, DevicePlacement
from nomarr.components.ml.ml_onnx_head import ONNXHeadModel

logger = logging.getLogger(__name__)


class ONNXModelCache:
    """Grouped, warmable container for all ONNX backbone and head models.

    Constructed from a *models_dir* root and a *device* target.  Immediately
    discovers all ``.onnx`` files and wraps each in the appropriate class;
    no sessions are loaded until :attr:`warm` is set to ``True``.

    Attributes:
        backbones: Backbone models keyed by backbone name (e.g. ``"effnet"``).
        heads: Head models keyed by backbone name; each value is a list of all
            head types for that backbone.

    Example usage::

        cache = ONNXModelCache("/models", device="gpu")
        cache.warm = True          # load all sessions
        emb = cache.backbones["effnet"].run(waveform)
        # ... run heads ...
        cache.warm = False         # unload all sessions (idle eviction)
    """

    backbones: dict[str, ONNXBackboneModel]
    """Backbone models keyed by :attr:`ONNXBackboneModel.backbone_name`."""

    heads: dict[str, list[ONNXHeadModel]]
    """Head models keyed by backbone name; each list is sorted by model name."""

    def __init__(self, models_dir: str, device: DevicePlacement) -> None:
        """Discover all ONNX models under *models_dir* and prepare them for warming.

        No sessions are loaded during construction.  Call ``cache.warm = True``
        to load all sessions.

        Args:
            models_dir: Root directory containing backbone sub-directories.
            device: Default execution device (``"cpu"`` or ``"gpu"``).  Used
                whenever sessions are loaded.
        """
        self._models_dir = models_dir
        self._device: DevicePlacement = device

        backbone_list: list[ONNXBackboneModel] = discover_backbone_models(models_dir)  # type: ignore[assignment]
        head_list: list[ONNXHeadModel] = discover_head_models(models_dir)  # type: ignore[assignment]

        self.backbones = {m.backbone_name: m for m in backbone_list}

        self.heads = {}
        for head in head_list:
            self.heads.setdefault(head.backbone_name, []).append(head)

        logger.info(
            "[cache] Discovered %d backbone(s), %d head(s) in %s (device=%s)",
            len(self.backbones),
            len(head_list),
            models_dir,
            device,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_models(self) -> Generator[BaseONNXModel, None, None]:
        """Yield all backbone and head models in a consistent order."""
        yield from self.backbones.values()
        for head_list in self.heads.values():
            yield from head_list

    # ------------------------------------------------------------------
    # warm
    # ------------------------------------------------------------------

    @property
    def warm(self) -> bool:
        """``True`` when every model in the cache has a loaded ONNX session.

        Setting to ``True`` loads any unloaded models on :attr:`device`.
        Setting to ``False`` unloads all sessions immediately.

        A cache with no models is trivially warm (vacuous truth).
        """
        return all(m._session is not None for m in self._all_models())

    @warm.setter
    def warm(self, value: bool) -> None:
        if value:
            for m in self._all_models():
                if m._session is None:
                    m.load(self._device)
            logger.info(
                "[cache] Warmed %d models on device=%s", self.model_count, self._device
            )
        else:
            for m in self._all_models():
                m.unload()
            logger.info("[cache] Unloaded all %d models", self.model_count)

    # ------------------------------------------------------------------
    # device
    # ------------------------------------------------------------------

    @property
    def device(self) -> DevicePlacement:
        """Execution device for all sessions (``"cpu"`` or ``"gpu"``).

        Setting a new device:

        - If the cache is **warm**: transitions every model (unload + reload on
          new device) via :attr:`BaseONNXModel.device` setter.
        - If the cache is **cold**: stores the device; it will be used on the
          next ``cache.warm = True`` call.
        """
        return self._device

    @device.setter
    def device(self, value: DevicePlacement) -> None:
        if value == self._device:
            return
        old = self._device
        self._device = value
        if self.warm:
            logger.info(
                "[cache] Transitioning %d models: %s → %s",
                self.model_count,
                old,
                value,
            )
            for m in self._all_models():
                m.device = value

    # ------------------------------------------------------------------
    # Informational
    # ------------------------------------------------------------------

    @property
    def model_count(self) -> int:
        """Total number of backbone + head models in this cache."""
        return len(self.backbones) + sum(len(h) for h in self.heads.values())
