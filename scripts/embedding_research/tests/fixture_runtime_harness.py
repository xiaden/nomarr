"""Deterministic runtime harness for driving the REAL eight-command CLI dispatch.

Part D (``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-
fixture-verification``) P1-S2.  This module runs the ACTUAL ``run.py`` phase runners
(:func:`run._run_single_phase` / the ``CLI_PHASE_RUNNERS`` dict — the same executor
``run.main`` drives after argparse + ``_build_run_config``) through every active phase
over a *fresh* deterministic corpus, driving every active phase — `ingest`, `embed`,
`infer-heads`, `catalog`, `catalog-report`, `analyze`, `head-analysis`, `report`.

Nothing here runs a real corpus/model/audio decode.  Deterministic injection is applied
ONLY to the three permitted audio/model phases (ingest / embed / infer-heads): the real
audio-discovery + audio-loading + model/ONNX/session seams are monkeypatched to replay the
synthetic corpus (``stream_matrix`` / per-song committed masks / deterministic head bytes)
that :mod:`fixture_cli_harness` defines.  The five derived phases run fully real (CPU) with
**call-counting sentinels active** over the audio / model-construction / ONNX-session /
CUDA / segmentation seams, and the run asserts those sentinels recorded ZERO calls.

Seam model
----------
The audio phases reach audio/model/ONNX/CUDA through a small set of runtime seams:

* audio discovery: ``config.discover_audio`` (aliased per-module as ``_discover_audio``);
* audio identity + metadata: ``config.song_id`` / ``config.path_to_meta``
  (aliased ``_song_id`` / ``_path_to_meta``);
* audio loading + preprocessing + ONNX session + batch runner: the ``nomarr.components.ml.*``
  leaf modules that the audio-phase bodies import *lazily at call time*
  (``ml_audio_comp.load_audio_mono``, ``ml_preprocess_comp.preprocess_for_backbone``,
  ``ml_session_comp.{create_session,_run_in_batches,_BACKBONE_BATCH_SIZE}``);
* mask derivation over the decoded waveform: ``common.embed._derive_audio_mask`` /
  ``common.embed._canonical_audio_fingerprint``;
* the configured head set: ``common.infer_heads._HEADS`` (head models are discovered from
  ``/app/models`` which does not exist under test).

Because ``nomarr`` is not importable in the research test env (psutil/onnxruntime absent),
the fake ``nomarr.components.ml.*`` leaf modules are installed in ``sys.modules`` as bare
:class:`types.ModuleType` carriers, exactly as the sibling ``test_embed.py`` stub pattern
does.  Their seam callables are *real, deterministic functions* that replay the synthetic
corpus — never ``Mock`` — and are what the derived-phase sentinels replace (a sentinel is a
function that records its invocation count AND raises).

Injection contract (kept faithful — no phase logic is bypassed):

* ``ingest`` discovers the 8 synthetic ``Path``s, derives each ``song_id`` from the path
  stem, and upserts ``SONG_METADATA`` (real ``strategy_meta.ingest`` body);
* ``embed`` runs the real ``_embed_song_raw`` publication core: decode(seam) ->
  preprocess(seam) -> ``session.run``(seam, identity over the fixture matrix) ->
  ``StreamStore.publish`` -> real ``publish_observation_group`` (committed stream + aligned
  committed uint8 mask + commit marker).  The committed mask is produced by the injected
  mask-derivation seam keyed on the song (so ``sil``'s silent RUN and ``z0``'s all-zero mask
  are committed exactly as :mod:`fixture_cli_harness` documents);
* ``infer-heads`` reads each committed backbone stream (real ``StreamStore.lookup`` /
  ``batch_gather``) and publishes the aligned deterministic head suite + the
  ``heads/current/<song>.<backbone>.json`` CURRENT marker (real
  ``HeadStreamStore.publish``);
* the five derived phases run with NO audio/model/ONNX/CUDA injection and with the sentinels
  installed; ``catalog`` still performs its legitimate CPU segmentation of the frozen
  committed streams (the segmentation sentinel is therefore scoped OFF for ``catalog`` and ON
  for ``catalog-report``/``analyze``/``head-analysis``/``report``).

All streams, masks, head suites, the compact catalog (``catalogs/<id>/`` + ``current.json``),
``catalog_report.txt`` and the report artifacts land under a caller-supplied ``output_root``
(tmp), and provenance / analyze-metrics / head-phase rows land on the caller-supplied
research DuckDB connection.  Everything is synthetic and deterministic; this run makes no
empirical retrieval claim.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np


# ─────────────────────────────────────────────────────────────────────────── #
# Call-counting sentinels                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
class ForbiddenRuntimeError(AssertionError):
    """Raised when a sentinel-guarded seam fires during a derived phase.

    A sentinel records its invocation count and THEN raises; catching this exception is
    never treated as success — the P1-S2 assertions inspect the recorded counts and require
    every one to be zero.
    """


class SentinelRegistry:
    """A tiny name -> call-count ledger for the derived-phase sentinel seams."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def sentinel(self, name: str, reason: str):
        """Return a callable that records one call and raises :class:`ForbiddenRuntimeError`."""

        def _guard(*_args: Any, **_kwargs: Any) -> Any:
            self.counts[name] = self.counts.get(name, 0) + 1
            raise ForbiddenRuntimeError(f"forbidden {reason} seam {name!r} called during a derived phase")

        return _guard

    def __getitem__(self, name: str) -> int:
        return self.counts.get(name, 0)

    def total(self) -> int:
        return sum(self.counts.values())

    def zero_for(self, names: list[str]) -> bool:
        return all(self[n] == 0 for n in names)


# ─────────────────────────────────────────────────────────────────────────── #
# Deterministic synthetic "audio + model" seams (used ONLY by audio phases)    #
# ─────────────────────────────────────────────────────────────────────────── #
class FakeSession:
    """Identity ONNX session: ``session.run([...], {feed: X})[0] == X``.

    Used for BOTH the backbone embed session and each classifier-head session: the model
    seam deterministically returns its input (the fixture matrix rows / gathered backbone
    rows) unchanged, so embed publishes exactly ``stream_matrix(song)`` and every head suite
    is the deterministic aligned ``[T, 2]`` activation array whose class-1 channel is the
    row's second coordinate.
    """

    def run(self, output_names: list[str], feed: dict[str, Any]) -> list[np.ndarray]:  # noqa: ARG002
        # The single input tensor is "melspectrogram" (embed) or "embeddings" (heads).
        arr = next(iter(feed.values()))
        return [np.ascontiguousarray(np.asarray(arr, dtype=np.float32))]


def _song_id_from_path(path: Any) -> str:
    """Deterministic identity seam: the fixture song id IS the audio path stem."""
    return str(path).rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _fixture_audio_paths(song_ids: tuple[str, ...]):
    """Audio-discovery seam: the 8 synthetic ``/fixture/audio/<song>.mp3`` paths."""
    from pathlib import Path

    return [Path(f"/fixture/audio/{song}.mp3") for song in song_ids]


def _load_audio_mono(path: str, target_sr: int) -> SimpleNamespace:  # noqa: ARG001
    """Audio-loading seam: return the song's synthetic stream matrix as its waveform.

    The waveform is never real audio; the deterministic preprocess seam below treats it as
    the patch matrix, so the "decode -> preprocess -> embed" chain replays the fixture.
    """
    import numpy as _np

    from scripts.embedding_research.tests.fixture_cli_harness import stream_matrix as _sm

    song = _song_id_from_path(path)
    return SimpleNamespace(waveform=_np.asarray(_sm(song), dtype=_np.float32))


def _preprocess_for_backbone(waveform: np.ndarray, _backbone_name: str) -> np.ndarray:
    """Preprocess seam: the synthetic waveform already IS the deterministic patch matrix."""
    return waveform


def _run_in_batches(predict_fn, patches: Any, batch_size: int) -> np.ndarray:
    """Deterministic batch runner matching the real ``_run_in_batches`` contract.

    Slices the patch sequence into ``batch_size``-wide chunks along axis 0, runs
    ``predict_fn`` per chunk and concatenates the outputs back into one ``[N, D]`` array.
    """
    rows = list(patches)
    out: list[np.ndarray] = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        arr = np.stack(chunk).astype(np.float32) if chunk else np.zeros((0, 2), dtype=np.float32)
        res = np.asarray(predict_fn(arr), dtype=np.float32)
        out.append(res)
    return np.concatenate(out, axis=0) if out else np.zeros((0, 2), dtype=np.float32)


def _create_session(*_args: Any, **_kwargs: Any) -> FakeSession:
    """Model-construction seam: return the deterministic identity session (never a real ONNX)."""
    return FakeSession()


def _fixture_mask_payload(
    _audio: np.ndarray,
    backbone_name: str,
    stream_record: Any,
    audio_fingerprint: str,  # noqa: ARG001
) -> Any:
    """Mask-derivation seam: commit the fixture's per-song silence mask for *song_id*.

    Mirrors the exact ``MaskPayload`` fields that the shared committed-group fixture contract
    (``tests/conftest.build_compact_catalog``) uses to publish an observation group, so the
    committed group on disk is structurally identical to the P1-S1 corpus contract.
    """
    import hashlib as _hashlib

    from scripts.embedding_research.streams.masks import MaskPayload
    from scripts.embedding_research.tests.fixture_cli_harness import song_mask as _song_mask

    song = stream_record.song_id
    mask = np.asarray(_song_mask(song), dtype=np.uint8)
    return MaskPayload(
        song_id=song,
        backbone=backbone_name,
        patch_count=int(stream_record.patch_count),
        mask=mask,
        params_id="0" * 64,
        audio_content_sha256=_hashlib.sha256(b"fixture-audio-content").hexdigest(),
        run_id=stream_record.run_id,
        created_at=1,
    )


# ─────────────────────────────────────────────────────────────────────────── #
# sys.modules carriers for the lazily-imported nomarr audio/ONNX leaf modules  #
# ─────────────────────────────────────────────────────────────────────────── #
def _install_nomarr_leaf_modules() -> dict[str, Any]:
    """Install bare ``nomarr.components.ml.*`` module carriers with deterministic seams.

    Idempotent: returns the carrier modules.  ``load_audio_mono`` / ``preprocess_for_backbone``
    / ``create_session`` / ``_run_in_batches`` live here so the audio-phase bodies resolve them
    through their lazy local imports; derived phases never reach them (their own imports are
    CPU-only and the sentinels below swap these attributes to guards anyway).
    """

    def _ensure(package: str, name: str) -> Any:
        full = f"{package}.{name}" if package else name
        if full in sys.modules and isinstance(sys.modules[full], ModuleType):
            return sys.modules[full]
        mod = ModuleType(full)
        if package:
            parent = _ensure("", package)
            parent.__dict__[name] = mod
        sys.modules[full] = mod
        return mod

    # Build the package tree as needed (bare ModuleType parents, leaf modules real carriers).
    for leaf, _seed in (
        ("nomarr.components.ml.onnx.ml_session_comp", None),
        ("nomarr.components.ml.audio.ml_audio_comp", None),
        ("nomarr.components.ml.audio.ml_preprocess_comp", None),
    ):
        _ensure("", leaf)

    sess = sys.modules["nomarr.components.ml.onnx.ml_session_comp"]
    sess.create_session = _create_session
    sess._run_in_batches = _run_in_batches
    sess._BACKBONE_BATCH_SIZE = 4096

    audio = sys.modules["nomarr.components.ml.audio.ml_audio_comp"]
    audio.load_audio_mono = _load_audio_mono

    pre = sys.modules["nomarr.components.ml.audio.ml_preprocess_comp"]
    pre.preprocess_for_backbone = _preprocess_for_backbone

    # Optional CUDA/ONNX surfaces that real audio code touches; the audio phases never call
    # them (device="cpu"), but derived-phase sentinels guard them in case a regression reaches
    # the GPU/onnx layer.  Install bare carriers only if not already present.
    for full in ("onnxruntime", "torch"):
        if full not in sys.modules:
            sys.modules[full] = ModuleType(full)

    return {
        "ml_session_comp": sess,
        "ml_audio_comp": audio,
        "ml_preprocess_comp": pre,
    }


# ─────────────────────────────────────────────────────────────────────────── #
# Phase-call evidence                                                          #
# ─────────────────────────────────────────────────────────────────────────── #
@dataclass
class FixtureRunEvidence:
    """Structured result of driving all eight phases through the real CLI dispatch.

    ``run_ids`` maps phase name -> the deterministic run_id recorded for that phase.
    ``phase_meta`` maps phase name -> the runner's returned meta dict (when the runner
    returned one).  ``run_provenance_rows`` are the auditable rows written per phase.
    ``sentinel_counts`` are the derived-phase sentinel call counts (all must be zero).
    ``output_root`` is where the durable streams/masks/heads/catalog/report artifacts live.
    """

    output_root: Any = field(repr=False)
    run_ids: dict[str, str] = field(default_factory=dict)
    phase_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_provenance_rows: list[dict[str, Any]] = field(default_factory=list)
    sentinel_counts: dict[str, int] = field(default_factory=dict)

    def phase_run_id(self, phase: str) -> str:
        return self.run_ids[phase]

    def status_of(self, phase: str) -> str:
        for row in self.run_provenance_rows:
            if row["phase"] == phase and row["run_id"] == self.run_ids[phase]:
                return str(row["status"])
        return "<no provenance row>"


# ─────────────────────────────────────────────────────────────────────────── #
# A small save/restore patch context (monkeypatch-independent)                 #
# ─────────────────────────────────────────────────────────────────────────── #
class _Patch:
    """Record setattr calls and restore them on ``exit`` (LIFO).

    Each restore is a closure, so attributes that did not previously exist are simply
    removed again on exit (safe for real carrier modules like ``onnxruntime`` whose top-level
    ``InferenceSession`` may not exist until the C extension is touched).
    """

    def __init__(self) -> None:
        self._restore: list[object] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        had = hasattr(obj, name)
        prev = getattr(obj, name) if had else None
        setattr(obj, name, value)
        if had:
            self._restore.append(lambda: setattr(obj, name, prev))
        else:
            self._restore.append(lambda: delattr(obj, name))

    def setitem(self, mapping: dict[Any, Any], key: Any, value: Any) -> None:
        had = key in mapping
        prev = mapping.get(key)
        mapping[key] = value
        if had:
            self._restore.append(lambda: mapping.__setitem__(key, prev))
        else:
            self._restore.append(lambda: mapping.pop(key, None))

    def __enter__(self) -> _Patch:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        for restore in reversed(self._restore):
            restore()
        return False


# ─────────────────────────────────────────────────────────────────────────── #
# Audio-phase patch installers + the eight-phase CLI run                       #
# ─────────────────────────────────────────────────────────────────────────── #
_CLI_PHASE_ORDER = ("ingest", "embed", "infer-heads", "catalog", "catalog-report", "analyze", "head-analysis", "report")
_AUDIO_PHASES = frozenset({"ingest", "embed", "infer-heads"})
_DERIVED_PHASES = frozenset(_CLI_PHASE_ORDER) - _AUDIO_PHASES
# Consumer derived phases must not even re-segment the frozen committed streams.  catalog is
# the one derived phase that legitimately performs CPU segmentation of the committed streams,
# so the segmentation sentinel is scoped to the consumers only.
_SEGMENT_FREE_DERIVED = frozenset({"catalog-report", "analyze", "head-analysis", "report"})


def _alive_stub():
    """Return an ``alive_it``-compatible iterable wrapper with a no-op ``.text()``."""

    class _Bar(list):
        def text(self, _msg: str) -> None:
            return None

    class _Stub:
        def __call__(self, iterable=None, **_kwargs: Any):
            return _Bar([] if iterable is None else iterable)

    return _Stub()


class FixtureCliRunner:
    """Drives the real ``run.py`` dispatch over a fresh deterministic corpus.

    ``con`` is the caller-owned research DuckDB connection (schema already ensured); all
    durable artifacts land under ``output_root``.  Audio phases run with the deterministic
    synthetic seams injected; derived phases run with the sentinel guards installed.
    """

    def __init__(
        self,
        con: Any,
        output_root: Any,
        *,
        backbones: tuple[str, ...] = ("effnet",),
        thresholds: tuple[float, ...] = (0.9, 1.0, 0.2),
        heads: tuple[str, ...] = ("timbre",),
        k: int = 10,
    ) -> None:
        from pathlib import Path

        from scripts.embedding_research.db._schema import ensure_schema

        ensure_schema(con)
        self.con = con
        self.output_root = Path(output_root)
        self.backbones = list(backbones)
        self.heads = list(heads)
        self.thresholds = [float(t) for t in thresholds]
        self.k = int(k)
        self._song_ids: tuple[str, ...] = self._load_song_ids()
        _install_nomarr_leaf_modules()
        self.evidence = FixtureRunEvidence(output_root=self.output_root)

    # -- corpus / song ids ------------------------------------------------- #
    def _load_song_ids(self) -> tuple[str, ...]:
        # The corpus song ids are exactly the deterministic fixture corpus in the P1-S1
        # harness (s1..s4, sil, abs, hard, z0), never a path hash.
        from scripts.embedding_research.tests.fixture_cli_harness import SONGS as _SONGS

        return tuple(_SONGS)

    def _audio_paths(self):
        from pathlib import Path

        return [Path(f"/fixture/audio/{song}.mp3") for song in self._song_ids]

    # -- per-phase config --------------------------------------------------- #
    def _cfg(self, _phase: str, run_id: str, *, verify: bool = False, strict: bool = False) -> dict[str, Any]:
        """Build the per-phase config through the REAL CLI/config seam.

        Phase config is produced by :func:`run._build_run_config` over an argparse
        ``Namespace`` mirroring the exact defaults ``run.main`` registers (device/force/
        regenerate_masks/retained/verify/strict); that is the SAME seam ``run.main`` drives
        after ``argparse`` for a real ``python run.py <phase>`` invocation, so every
        seam-derived field (backbones/device/limit/k/workers/blas_threads/retained/
        ``config_hash`` from the strict ``research_config.toml`` loader, the frozen
        ``helpers.binning`` sweep defaults) genuinely comes from the real config/CLI seam —
        never a hand-built dict that could silently diverge from what a production run reads.

        Only the deterministic fixture's *controlled input surface* is overlaid afterward, and
        each override is seam-honest:

        * ``output_root`` / ``report_dir`` — output isolation so fixture artifacts land under a
          caller-supplied tmp root instead of the repository-external ``OUTPUT_ROOT`` (unit tests
          must never leak into ``/workspace/scripts/outputs/embedding_research``).  This is the
          same isolation ``run.main``'s ``_RunLock``/DB resolution applies via ``RESEARCH_DB_PATH``.
        * ``run_id`` — the deterministic per-phase run id recorded by the harness.
        * ``backbones`` / ``heads`` — the runner's constructed corpus/head surface (the synthetic
          audio/model seams replay exactly these; ``infer-heads`` uses ``self.heads`` to build the
          injected ``_HEADS`` registry).
        * ``catalog_bin_modes`` / ``catalog_thresholds`` — the fixture's COMPACT catalog sweep
          (single ``temporal_global`` mode over ``{0.9, 1.0, 0.2}``).  This is the documented
          test-only override seam on ``_catalog_seg_configs`` (the catalog input sweep the real
          seam seeds from the frozen ``helpers.binning`` literals); it keeps the deterministic
          corpus's alias/distinct search-class structure intact.

        The analyze phase has NO baseline option anywhere — the mandatory observed
        ``global_pool:{backbone}:medoid`` baseline is unconditional in ``run.py::_run_analyze``
        (execution-reporting Plan A P2), so routing config through the real seam can never hide or
        re-add an ``emit_medoid_baseline`` key/flag.
        """
        import argparse

        import scripts.embedding_research.run as _run

        args = argparse.Namespace(
            device=None,
            force=False,
            regenerate_masks=False,
            retained=False,
            verify=bool(verify),
            strict=bool(strict),
        )
        cfg: dict[str, Any] = _run._build_run_config(args)
        cfg["output_root"] = self.output_root
        cfg["report_dir"] = self.output_root / "report"
        cfg["run_id"] = run_id
        cfg["backbones"] = list(self.backbones)
        cfg["heads"] = list(self.heads)
        cfg["catalog_bin_modes"] = ["temporal_global"]
        cfg["catalog_thresholds"] = list(self.thresholds)
        return cfg

    # -- audio-phase injection --------------------------------------------- #
    def _inject_audio(self, p: _Patch) -> None:
        """Install the deterministic synthetic audio/model seams for ingest/embed/infer-heads."""
        import scripts.embedding_research.common.embed as _emb
        import scripts.embedding_research.common.infer_heads as _ih
        import scripts.embedding_research.strategy_meta as _sm
        from scripts.embedding_research.streams import HeadStreamStore as _RealHeadStore
        from scripts.embedding_research.streams import StreamStore as _RealStreamStore
        from scripts.embedding_research.tests.fixture_cli_harness import SONG_METADATA as _META

        def discover(*_a, **_k):
            return list(self._audio_paths())

        sid_of = _song_id_from_path

        def meta_of(path: Any) -> dict[str, str]:
            return dict(_META[_song_id_from_path(path)])

        # ingest (strategy_meta.ingest body)
        p.setattr(_sm, "_discover_audio", discover)
        p.setattr(_sm, "_path_to_meta", meta_of)
        p.setattr(_sm, "_song_id", sid_of)
        p.setattr(_sm, "_bootstrap_nomarr", lambda: None)
        p.setattr(_sm, "_alive_it", _alive_stub())

        # embed (common.embed.embed body)
        p.setattr(_emb, "_discover_audio", discover)
        p.setattr(_emb, "_song_id", sid_of)
        p.setattr(_emb, "_bootstrap_nomarr", lambda: None)
        p.setattr(_emb, "_alive_it", _alive_stub())
        p.setattr(_emb, "StreamStore", lambda con: _RealStreamStore(con, output_root=str(self.output_root)))
        p.setattr(_emb, "_derive_audio_mask", _fixture_mask_payload)
        p.setattr(_emb, "_canonical_audio_fingerprint", lambda _w: "f" * 64)
        p.setattr(_emb, "_song_exists", lambda con, sid: self._registry_has(con, sid))
        p.setattr(_emb, "_path_to_meta", meta_of)
        p.setattr(_emb, "_upsert_song", lambda *_a, **_k: None)

        # infer-heads — the CLI wrapper (run._run_infer_heads) calls the real
        # common.infer_heads.infer_heads body directly (no ``heads`` parameter exists in its
        # signature; a reintroduced ``heads=cfg.get("heads")`` must raise TypeError against the
        # real signature rather than pass silently).  All seams below are what that body needs:
        # a small configured head set (the real discovery would read /app/models which does not
        # exist under test), the corpus lookup seams, and the real stream/head stores.
        p.setattr(_ih, "_discover_audio", discover)
        p.setattr(_ih, "_song_id", sid_of)
        p.setattr(_ih, "_bootstrap_nomarr", lambda: None)
        p.setattr(_ih, "_HEADS", {b: {h: f"/fixture/models/{h}.onnx" for h in self.heads} for b in self.backbones})
        p.setattr(_ih, "StreamStore", lambda con: _RealStreamStore(con, output_root=str(self.output_root)))
        p.setattr(_ih, "HeadStreamStore", lambda con: _RealHeadStore(con, output_root=str(self.output_root)))

    @staticmethod
    def _registry_has(con: Any, sid: str) -> bool:
        # embed() only upserts a song when it is not already registered.  ingest runs first and
        # registers every corpus song, so embed must not re-upsert.  Probe the songs table.
        try:
            row = con.execute("SELECT 1 FROM songs WHERE song_id=?", (sid,)).fetchone()
            return row is not None
        except Exception:
            return False

    # -- sentinel installers ------------------------------------------------ #
    def _install_forbidden_sentinels(self, p: _Patch, reg: SentinelRegistry) -> None:
        """Audio/model/ONNX/CUDA/inference sentinels — active for every derived phase."""
        import scripts.embedding_research.common.embed as _emb
        from scripts.embedding_research import config as _cfg

        p.setattr(_cfg, "discover_audio", reg.sentinel("audio.discover_audio", "audio-discovery"))
        ml_audio = sys.modules["nomarr.components.ml.audio.ml_audio_comp"]
        p.setattr(ml_audio, "load_audio_mono", reg.sentinel("audio.load_audio_mono", "audio-loading"))
        ml_sess = sys.modules["nomarr.components.ml.onnx.ml_session_comp"]
        p.setattr(ml_sess, "create_session", reg.sentinel("model.create_session", "model-construction"))
        # ONNX / CUDA runtime surfaces (onnxruntime + torch carriers installed above).
        onnx = sys.modules.setdefault("onnxruntime", ModuleType("onnxruntime"))
        p.setattr(onnx, "InferenceSession", reg.sentinel("onnx.inference_session", "onnx-session-execution"))
        sys.modules.setdefault("torch", ModuleType("torch"))
        torch_cuda = sys.modules.setdefault("torch.cuda", ModuleType("torch.cuda"))
        torch_cuda.is_available = reg.sentinel("cuda.is_available", "cuda")
        # The whole-phase inference entry points a derived regression would have to reach.
        p.setattr(_emb, "embed", reg.sentinel("infer.embed", "inference"))
        p.setattr(_emb, "regenerate_masks", reg.sentinel("infer.regenerate_masks", "inference"))
        p.setattr(_emb, "_derive_audio_mask", reg.sentinel("mask.derive_audio_mask", "audio-mask-derivation"))

    def _install_segmentation_sentinel(self, p: _Patch, reg: SentinelRegistry) -> None:
        from scripts.embedding_research.helpers import segmentation as _seg_mod

        p.setattr(
            _seg_mod,
            "run_spherical_segmentation",
            reg.sentinel("segmentation.run_spherical_segmentation", "segmentation"),
        )

    # -- phase execution ----------------------------------------------------- #
    def _run_phase(self, phase: str, run_index: int) -> dict[str, Any]:
        """Run ONE phase via the real CLI executor (``run._run_single_phase``)."""
        import scripts.embedding_research.run as _run

        run_id = f"{phase}-{run_index:06d}"
        cfg = self._cfg(phase, run_id)
        meta = _run._run_single_phase(self.con, phase, cfg, db_path=None)
        return {"run_id": run_id, "meta": meta or {}}

    def _run_audio_phase(self, phase: str, run_index: int) -> dict[str, Any]:
        with _Patch() as p:
            self._inject_audio(p)
            return self._run_phase(phase, run_index)

    def _run_derived_phase(self, phase: str, run_index: int, reg: SentinelRegistry) -> dict[str, Any]:
        with _Patch() as p:
            self._install_forbidden_sentinels(p, reg)
            if phase in _SEGMENT_FREE_DERIVED:
                self._install_segmentation_sentinel(p, reg)
            return self._run_phase(phase, run_index)

    def run_all(self) -> FixtureRunEvidence:
        """Execute the eight phases in CLI order and assemble :class:`FixtureRunEvidence`.

        All derived phases run with the forbidden sentinels active; the segmentation sentinel
        is additionally active for the four consumers (never for ``catalog``, which performs
        its legitimate CPU segmentation of the frozen committed streams).
        """

        reg = SentinelRegistry()
        # Record the pre-existing run_provenance rows (there are none on a fresh DB, but keep
        # this read the source of truth for the evidence anyway).
        try:
            from scripts.embedding_research.db.provenance import read_run_provenance as _read

            before = {r["run_id"] for r in _read(self.con)}
        except Exception:
            before = set()

        for idx, phase in enumerate(_CLI_PHASE_ORDER, start=1):
            if phase in _AUDIO_PHASES:
                outcome = self._run_audio_phase(phase, idx)
            else:
                outcome = self._run_derived_phase(phase, idx, reg)
            self.evidence.run_ids[phase] = outcome["run_id"]
            self.evidence.phase_meta[phase] = outcome["meta"]

        # Collect the run_provenance rows written by this sequence.
        try:
            from scripts.embedding_research.db.provenance import read_run_provenance as _read

            self.evidence.run_provenance_rows = [r for r in _read(self.con) if r["run_id"] not in before]
        except Exception:
            self.evidence.run_provenance_rows = []
        # Sentinel counts are captured AFTER every derived phase completed.
        self.evidence.sentinel_counts = dict(sorted(reg.counts.items()))
        return self.evidence
