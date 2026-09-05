"""Strict research-configuration loader (Plan A P1-S3).

``load_research_config`` validates the *current executable* research
configuration against an exact schema and returns a typed
:class:`CurrentResearchConfig`.  There is no permissive warn-and-default path:
a missing file, unparsable TOML, unavailable parser, unknown key, alias,
forbidden key family, or invalid type is a distinct named error surfaced as a
nonzero exit — never silently ``{}``.

Current executable configuration
--------------------------------
The schema accepts ONLY the sections the current eight-phase and maintenance
code actually executes:

* ``[pipeline]`` — EffNet default backbone with an explicit MusicNN opt-in
  (``backbones``), optional head subset, ONNX ``device``, corpus ``limit`` and
  ``force``.
* ``[analysis]`` — ``k`` / ``workers`` / ``blas_threads`` run controls for the
  ``analyze`` phase.

Everything else is rejected as unknown: ``archival_ctp``, ``std_scaled``,
calibration/p50, ``rep_a``/``rep_b``, obsolete pooling / threshold / optimizer
sections, weighted-reduction / optimizer vocabulary, and any zero-caller key.
Defaults are applied only after a successful parse+validation, never for a
missing or invalid configuration file.

All exceptions derive from :class:`ResearchConfigError`:
:class:`ResearchConfigMissingError`, :class:`ResearchConfigSyntaxError`,
:class:`ResearchConfigParserUnavailableError`, :class:`ResearchConfigValidationError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

try:  # Python >= 3.11
    import tomllib as _toml_mod  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - py<3.11 fallback
    try:
        import tomli as _toml_mod  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover - both parsers absent
        _toml_mod = None  # type: ignore[assignment]

#: Default config path (fixed in-tree under ``scripts/embedding_research/``).
_CONFIG_PATH: Final[Path] = Path(__file__).parent.parent / "research_config.toml"

#: The only valid backbone names.  ``effnet`` is the default; ``musicnn`` is an
#: explicit opt-in (never cross-averaged with effnet).
_BACKBONES: Final[frozenset[str]] = frozenset({"effnet", "musicnn"})
_DEFAULT_BACKBONE: Final[str] = "effnet"

_ALLOWED_TOP_LEVEL: Final[frozenset[str]] = frozenset({"pipeline", "analysis"})
_ALLOWED_PIPELINE: Final[frozenset[str]] = frozenset({"backbones", "heads", "device", "limit", "force"})
_ALLOWED_ANALYSIS: Final[frozenset[str]] = frozenset({"k", "workers", "blas_threads"})

_DEFAULT_PIPELINE_DEVICE: Final[str] = "cpu"
_DEFAULT_PIPELINE_LIMIT: Final[int] = 0
_DEFAULT_PIPELINE_FORCE: Final[bool] = False
_DEFAULT_ANALYSIS_K: Final[int] = 10
_DEFAULT_ANALYSIS_WORKERS: Final[int] = 4
_DEFAULT_ANALYSIS_BLAS_THREADS: Final[int] = 1


class ResearchConfigError(Exception):
    """Base for all strict research-configuration failures."""


class ResearchConfigMissingError(ResearchConfigError):
    """The research configuration file does not exist.

    Remediation: provide ``scripts/embedding_research/research_config.toml``.
    A missing configuration is never treated as an empty run configuration.
    """


class ResearchConfigSyntaxError(ResearchConfigError):
    """The research configuration file is not parseable TOML."""


class ResearchConfigParserUnavailableError(ResearchConfigError):
    """No TOML parser (``tomllib``/``tomli``) is importable in this environment."""


class ResearchConfigValidationError(ResearchConfigError):
    """The research configuration violates the strict current schema (unknown
    key, forbidden key family, alias, or invalid type)."""


@dataclass(frozen=True)
class PipelineConfig:
    """Current ``[pipeline]`` executable settings."""

    backbones: tuple[str, ...]
    heads: tuple[str, ...] | None
    device: str
    limit: int
    force: bool


@dataclass(frozen=True)
class AnalysisConfig:
    """Current ``[analysis]`` executable settings."""

    k: int
    workers: int
    blas_threads: int | None


@dataclass(frozen=True)
class CurrentResearchConfig:
    """Typed current executable research configuration (Plan A P1-S3).

    Only executable eight-phase / maintenance vocabulary is represented.  EffNet
    is the default backbone; MusicNN appears only as an explicit opt-in.
    """

    pipeline: PipelineConfig
    analysis: AnalysisConfig


# ---------------------------------------------------------------------------
# strict schema validation helpers
# ---------------------------------------------------------------------------


def _expect_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchConfigValidationError(f"{where} must be non-empty text; got {value!r}")
    return value


def _expect_bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ResearchConfigValidationError(f"{where} must be a bool; got {type(value).__name__}")
    return value


def _expect_nonneg_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchConfigValidationError(f"{where} must be a non-negative int; got {value!r}")
    return value


def _expect_pos_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchConfigValidationError(f"{where} must be a positive int; got {value!r}")
    return value


def _expect_string_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise ResearchConfigValidationError(f"{where} must be a non-empty list of non-empty strings; got {value!r}")
    return tuple(value)


def _validate_pipeline(pipe: object) -> PipelineConfig:
    if not isinstance(pipe, dict):
        raise ResearchConfigValidationError(f"[pipeline] must be a table; got {type(pipe).__name__!r}")
    unknown = sorted(set(pipe) - _ALLOWED_PIPELINE)
    if unknown:
        raise ResearchConfigValidationError(f"unknown [pipeline] key(s): {unknown}")

    backbones = _expect_string_list(pipe.get("backbones", [_DEFAULT_BACKBONE]), "[pipeline] backbones")
    bad = sorted(set(backbones) - _BACKBONES)
    if bad:
        raise ResearchConfigValidationError(
            f"[pipeline] backbones contains unsupported value(s) {bad}; supported: {sorted(_BACKBONES)}"
        )
    if _DEFAULT_BACKBONE not in backbones:
        # EffNet is the default backbone; MusicNN (or any other) is an explicit
        # opt-in that must not replace the EffNet default silently.
        raise ResearchConfigValidationError(
            f"[pipeline] backbones must include the default backbone {_DEFAULT_BACKBONE!r}; got {backbones}"
        )

    heads_raw = pipe.get("heads")
    if heads_raw is None:
        heads: tuple[str, ...] | None = None
    else:
        heads = _expect_string_list(heads_raw, "[pipeline] heads")

    device = _expect_str(pipe.get("device", _DEFAULT_PIPELINE_DEVICE), "[pipeline] device").lower()
    if device not in {"cpu", "gpu", "cuda"}:
        raise ResearchConfigValidationError(f"[pipeline] device must be cpu/gpu/cuda; got {device!r}")
    device = "gpu" if device in {"gpu", "cuda"} else "cpu"

    limit = _expect_nonneg_int(pipe.get("limit", _DEFAULT_PIPELINE_LIMIT), "[pipeline] limit")
    force = _expect_bool(pipe.get("force", _DEFAULT_PIPELINE_FORCE), "[pipeline] force")
    return PipelineConfig(backbones=backbones, heads=heads, device=device, limit=limit, force=force)


def _validate_analysis(analysis: object) -> AnalysisConfig:
    if not isinstance(analysis, dict):
        raise ResearchConfigValidationError(f"[analysis] must be a table; got {type(analysis).__name__!r}")
    unknown = sorted(set(analysis) - _ALLOWED_ANALYSIS)
    if unknown:
        raise ResearchConfigValidationError(f"unknown [analysis] key(s): {unknown}")

    k = _expect_pos_int(analysis.get("k", _DEFAULT_ANALYSIS_K), "[analysis] k")
    workers = _expect_pos_int(analysis.get("workers", _DEFAULT_ANALYSIS_WORKERS), "[analysis] workers")
    blas_raw = analysis.get("blas_threads", _DEFAULT_ANALYSIS_BLAS_THREADS)
    blas_threads: int | None
    if blas_raw is None:
        blas_threads = None
    else:
        blas_threads = _expect_pos_int(blas_raw, "[analysis] blas_threads")
    return AnalysisConfig(k=k, workers=workers, blas_threads=blas_threads)


def _validate_doc(doc: dict[str, Any]) -> CurrentResearchConfig:
    unknown_top = sorted(set(doc) - _ALLOWED_TOP_LEVEL)
    if unknown_top:
        raise ResearchConfigValidationError(
            f"unknown research config section(s): {unknown_top}; the current schema allows only "
            f"{sorted(_ALLOWED_TOP_LEVEL)} (executable eight-phase/maintenance settings)"
        )
    pipeline = _validate_pipeline(doc.get("pipeline", {}))
    analysis = _validate_analysis(doc.get("analysis", {}))
    return CurrentResearchConfig(pipeline=pipeline, analysis=analysis)


def _parse(text: str) -> dict[str, Any]:
    if _toml_mod is None:
        raise ResearchConfigParserUnavailableError(
            "no TOML parser available (tomllib/tomli not importable); cannot load research_config.toml"
        )
    try:
        parsed = _toml_mod.loads(text)
    except Exception as exc:  # tomllib.TOMLDecodeError or tomli equivalent
        raise ResearchConfigSyntaxError(f"research_config.toml is not parseable TOML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ResearchConfigValidationError("research_config.toml must decode to a top-level table")
    return parsed


@cache
def load_research_config(path: Path | None = None) -> CurrentResearchConfig:
    """Load and validate the strict current research configuration.

    Parameters
    ----------
    path:
        Explicit config path; defaults to the in-tree ``research_config.toml``.

    Returns
    -------
    CurrentResearchConfig
        The typed current executable configuration.

    Raises
    ------
    ResearchConfigMissingError
        The configuration file does not exist.
    ResearchConfigSyntaxError
        The file is not parseable TOML.
    ResearchConfigParserUnavailableError
        No TOML parser is importable.
    ResearchConfigValidationError
        The parsed document violates the strict current schema (unknown key,
        forbidden key family, alias, or invalid type).
    """
    config_path = Path(path) if path is not None else _CONFIG_PATH
    if not config_path.exists():
        raise ResearchConfigMissingError(
            f"research configuration not found at {config_path}; the current schema loader never "
            "falls back to an empty run configuration — provide a valid research_config.toml"
        )
    raw = config_path.read_text(encoding="utf-8")
    doc = _parse(raw)
    return _validate_doc(doc)


def load_research_config_bytes(path: Path | None = None) -> bytes:
    """Return the raw bytes of the research configuration file.

    Used only where a caller needs the exact on-disk bytes (e.g. a legacy
    run-config digest).  A missing file raises :class:`ResearchConfigMissingError`
    rather than returning empty bytes.
    """
    config_path = Path(path) if path is not None else _CONFIG_PATH
    if not config_path.exists():
        raise ResearchConfigMissingError(f"research configuration not found at {config_path}; cannot return raw bytes")
    return config_path.read_bytes()
