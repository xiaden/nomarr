from __future__ import annotations

import pytest

from scripts.embedding_research.helpers import toml as research_toml


@pytest.fixture(autouse=True)
def clear_load_research_config_bytes_cache() -> None:
    research_toml.load_research_config_bytes.cache_clear()
    yield
    research_toml.load_research_config_bytes.cache_clear()


def test_load_research_config_bytes_returns_empty_bytes_when_file_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "missing_research_config.toml"

    monkeypatch.setattr(research_toml, "_CONFIG_PATH", missing_path)

    result = research_toml.load_research_config_bytes()

    assert result == b""


def test_load_research_config_bytes_returns_file_bytes_when_file_exists(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "research_config.toml"
    expected = b"[research]\nlimit = 42\n"
    config_path.write_bytes(expected)

    monkeypatch.setattr(research_toml, "_CONFIG_PATH", config_path)

    result = research_toml.load_research_config_bytes()

    assert result == expected
