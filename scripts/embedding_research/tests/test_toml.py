"""Strict current-configuration loader tests (Plan A P1-S3 / P1-S5).

The loader accepts ONLY the executable current schema: ``[pipeline]`` (EffNet
default backbone + explicit MusicNN opt-in, optional heads, ONNX device, corpus
limit, force) and ``[analysis]`` (k / workers / blas_threads).  Missing,
malformed, parser-unavailable and validation failures are DISTINCT named
errors — never a warn-and-return-``{}``.  Unknown top-level/nested keys, alias
keys, forbidden legacy families (archival CTP, std_scaled/calibration/p50,
optimizer/weighted, obsolete pooling/threshold, ``rep_a``/``rep_b``, zero-caller
keys) and invalid types are rejected.
"""

from __future__ import annotations

import textwrap

import pytest

from scripts.embedding_research.helpers import toml as research_toml

# A minimal valid current-schema document.
_VALID = textwrap.dedent(
    """\
    [pipeline]
    backbones = ["effnet"]
    device = "cpu"
    limit = 0
    force = false

    [analysis]
    k = 10
    workers = 4
    blas_threads = 1
    """
)


@pytest.fixture(autouse=True)
def clear_config_caches() -> None:
    research_toml.load_research_config.cache_clear()
    yield
    research_toml.load_research_config.cache_clear()


def _load(text: str, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Write ``text`` to a temp research_config.toml and load it (fresh, strict)."""
    cfg_path = tmp_path / "research_config.toml"
    cfg_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(research_toml, "_CONFIG_PATH", cfg_path)
    return research_toml.load_research_config()


# ── valid current-schema loading ─────────────────────────────────────────────


def test_shipped_config_is_valid_current_schema() -> None:
    """The in-tree research_config.toml parses + validates against the strict schema."""
    cfg = research_toml.load_research_config()
    assert cfg.pipeline.backbones == ("effnet",)
    assert cfg.pipeline.device == "cpu"
    assert cfg.pipeline.limit == 0
    assert cfg.pipeline.force is False
    assert cfg.pipeline.heads is None
    assert cfg.analysis.k == 10
    assert cfg.analysis.workers == 4
    assert cfg.analysis.blas_threads == 1


def test_musicnn_is_explicit_opt_in(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MusicNN appears only when explicitly listed alongside EffNet."""
    doc = '[pipeline]\nbackbones = ["effnet", "musicnn"]\n\n[analysis]\nk = 5\n'
    cfg = _load(doc, tmp_path, monkeypatch)
    assert cfg.pipeline.backbones == ("effnet", "musicnn")
    assert cfg.analysis.k == 5


def test_backbones_require_effnet_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backbone list that omits EffNet is rejected (EffNet is the default)."""
    doc = '[pipeline]\nbackbones = ["musicnn"]\n'
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


def test_unknown_backbone_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = '[pipeline]\nbackbones = ["effnet", "bogus"]\n'
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


def test_optional_heads_default_to_none(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = '[pipeline]\nbackbones = ["effnet"]\nheads = ["mtg_jamendo_genre"]\n[analysis]\n'
    cfg = _load(doc, tmp_path, monkeypatch)
    assert cfg.pipeline.heads == ("mtg_jamendo_genre",)


def test_analysis_defaults_apply_after_successful_parse(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional analysis fields default only after the document parses+validates."""
    doc = '[pipeline]\nbackbones = ["effnet"]\n'
    cfg = _load(doc, tmp_path, monkeypatch)
    assert cfg.analysis.k == 10
    assert cfg.analysis.workers == 4
    assert cfg.analysis.blas_threads == 1


# ── missing / malformed / parser-unavailable named errors ────────────────────


def test_missing_config_is_named_error_never_empty_dict(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing research_config.toml is a ResearchConfigMissingError, never {}."""
    missing = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr(research_toml, "_CONFIG_PATH", missing)
    with pytest.raises(research_toml.ResearchConfigMissingError):
        research_toml.load_research_config()


def test_missing_config_bytes_is_named_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr(research_toml, "_CONFIG_PATH", missing)
    with pytest.raises(research_toml.ResearchConfigMissingError):
        research_toml.load_research_config_bytes()


def test_malformed_toml_is_syntax_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(research_toml.ResearchConfigSyntaxError):
        _load("[pipeline\nbackbones = ", tmp_path, monkeypatch)


def test_parser_unavailable_is_named_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no TOML parser is importable the loader raises ParserUnavailableError."""
    monkeypatch.setattr(research_toml, "_toml_mod", None)
    with pytest.raises(research_toml.ResearchConfigParserUnavailableError):
        _load(_VALID, tmp_path, monkeypatch)


def test_errors_are_distinct_exceptions() -> None:
    """Each named error is a distinct class; all subclass the common base."""
    assert issubclass(research_toml.ResearchConfigMissingError, research_toml.ResearchConfigError)
    assert issubclass(research_toml.ResearchConfigSyntaxError, research_toml.ResearchConfigError)
    assert issubclass(research_toml.ResearchConfigParserUnavailableError, research_toml.ResearchConfigError)
    assert issubclass(research_toml.ResearchConfigValidationError, research_toml.ResearchConfigError)
    assert research_toml.ResearchConfigMissingError is not research_toml.ResearchConfigSyntaxError
    assert research_toml.ResearchConfigSyntaxError is not research_toml.ResearchConfigParserUnavailableError
    assert research_toml.ResearchConfigValidationError is not research_toml.ResearchConfigSyntaxError


# ── unknown / forbidden-family / alias keys rejected ─────────────────────────


@pytest.mark.parametrize(
    "section",
    [
        "archival_ctp",  # CTP switch family
        "optimization",  # optimizer family (incl. [optimization.strategy])
        "pooling",  # obsolete pooling (incl. flat_strategies / rep_types)
        "pooling.hypotheses",  # weighted-reduction vocabulary
        "similarity",  # similarity metrics (obsolete config)
        "stratify",  # stratify family
        "binning",  # obsolete threshold sweep / bin_modes
        "calibration",  # calibration family
        "p50",  # p50 family
        "rep_a",  # rep_a family
        "rep_b",  # rep_b family
        "std_scaled",  # scaled-threshold family
    ],
)
def test_forbidden_family_top_level_section_rejected(section, tmp_path, monkeypatch) -> None:
    doc = f'[{section}]\nenabled = true\n[pipeline]\nbackbones = ["effnet"]\n'
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "doc",
    [
        # unknown top-level key
        '[bogus]\nx = 1\n[pipeline]\nbackbones = ["effnet"]\n',
        # unknown nested key inside a current section
        '[pipeline]\nbackbones = ["effnet"]\nstd_scaled = true\n',
        # obsolete optimizer sub-table nested under analysis
        '[pipeline]\nbackbones = ["effnet"]\n[analysis.optimizer]\nagg_method = "x"\n',
        # calibration/p50 nested key
        '[pipeline]\nbackbones = ["effnet"]\n[analysis]\ncalibration = "p50"\n',
    ],
)
def test_unknown_and_forbidden_nested_keys_rejected(doc, tmp_path, monkeypatch) -> None:
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


def test_alias_legacy_key_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A formerly-permissive alias section is rejected, never silently honoured."""
    doc = '[pipeline]\nbackbones = ["effnet"]\n[pipeline.backbones_alias]\n'
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "doc",
    [
        '[pipeline]\nbackbones = ["effnet"]\nlimit = "many"\n',  # wrong type
        '[pipeline]\nbackbones = ["effnet"]\nforce = 1\n',  # bool expected
        '[pipeline]\nbackbones = "effnet"\n',  # list expected
        '[pipeline]\nbackbones = ["effnet"]\nheads = "mtg_jamendo_genre"\n',  # list expected
        '[pipeline]\nbackbones = ["effnet"]\nlimit = -1\n',  # non-negative int
        "[analysis]\nk = 0\n",  # positive int
        "[analysis]\nworkers = -2\n",  # positive int
    ],
)
def test_invalid_type_rejected(doc, tmp_path, monkeypatch) -> None:
    with pytest.raises(research_toml.ResearchConfigValidationError):
        _load(doc, tmp_path, monkeypatch)


# ── load_research_config_bytes ───────────────────────────────────────────────


def test_load_research_config_bytes_returns_file_bytes(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "research_config.toml"
    expected = b'[pipeline]\nbackbones = ["effnet"]\n'
    config_path.write_bytes(expected)
    monkeypatch.setattr(research_toml, "_CONFIG_PATH", config_path)
    assert research_toml.load_research_config_bytes() == expected
