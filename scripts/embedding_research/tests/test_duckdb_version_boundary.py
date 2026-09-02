"""DuckDB library-version boundary and storage-version-label policy (Part A).

Spec-first tests for the DuckDB version contract:

* The pinned range is ``duckdb>=1.5,<2.0`` (requirements.txt). ``require_supported_duckdb``
  is called at every research CLI phase startup and rejects any installed duckdb
  outside ``1.5 <= v < 2.0`` (including the stale ``>=0.10.0`` era and a
  hypothetical future 2.x) loudly.
* DuckDB *storage-format* version metadata is treated as an opaque LABEL
  (``storage_version_label``) — it is never parsed or numerically compared. A
  hypothetical 2.x storage value therefore passes through unchanged as a label;
  only the *library* version is gated. Deciding whether a 2.x storage file is
  compatible is a separately approved follow-up, never assumed off a numeric
  comparison here.
"""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.db import _schema as schema_mod


def _monkeypatch_duckdb_version(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(duckdb, "__version__", version)


# ---------------------------------------------------------------------------
# Library version gate: duckdb >=1.5,<2.0
# ---------------------------------------------------------------------------


def test_version_gate_accepts_supported_1_5(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "1.5.0")
    schema_mod.require_supported_duckdb()  # must not raise


def test_version_gate_accepts_supported_1_9(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "1.9.99")
    schema_mod.require_supported_duckdb()  # must not raise


def test_version_gate_rejects_stale_0_10(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "0.10.0")
    with pytest.raises(RuntimeError, match="duckdb"):
        schema_mod.require_supported_duckdb()


def test_version_gate_rejects_below_min_1_4(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "1.4.9")
    with pytest.raises(RuntimeError, match="duckdb"):
        schema_mod.require_supported_duckdb()


def test_version_gate_rejects_future_2_x(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hypothetical future 2.x duckdb library is rejected loudly (separately approved follow-up)."""
    _monkeypatch_duckdb_version(monkeypatch, "2.0.0")
    with pytest.raises(RuntimeError, match="duckdb"):
        schema_mod.require_supported_duckdb()


def test_version_gate_rejects_future_3_x(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "3.1.0")
    with pytest.raises(RuntimeError, match="duckdb"):
        schema_mod.require_supported_duckdb()


def test_version_tuple_parses_dev_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    _monkeypatch_duckdb_version(monkeypatch, "1.5.1-dev0")
    assert schema_mod._duckdb_version_tuple() == (1, 5)


# ---------------------------------------------------------------------------
# Storage-format version: treated as a LABEL, never compared numerically
# ---------------------------------------------------------------------------


def test_hypothetical_2x_storage_version_is_treated_as_label() -> None:
    """A hypothetical future 2.x storage-format version passes through as a label.

    Negative assertion: we do NOT parse or numerically compare a storage-version
    value against a supported range. ``storage_version_label`` returns it
    unchanged (opaque), so a 2.x storage value is recorded/audited as a label and
    compatibility is left to an explicit approved follow-up — never silently
    rejected or accepted off a numeric comparison here.
    """
    assert schema_mod.storage_version_label("2.1.0") == "2.1.0"
    assert schema_mod.storage_version_label(2) == "2"
    assert schema_mod.storage_version_label("1.5.0") == "1.5.0"


def test_storage_version_label_does_not_raise_for_unknown_shape() -> None:
    """Non-numeric / opaque storage-version values are still just labelled."""
    assert schema_mod.storage_version_label(None) == "None"
    assert schema_mod.storage_version_label("legacy-era") == "legacy-era"


def test_storage_label_is_distinct_from_library_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the *library* version is gated; a 2.x *storage* value is still just a label.

    This pins the intended asymmetry: duckdb 2.x as a library is rejected at
    startup, whereas a recorded 2.x storage-format label passes through untouched.
    """
    _monkeypatch_duckdb_version(monkeypatch, "2.0.0")
    with pytest.raises(RuntimeError):
        schema_mod.require_supported_duckdb()
    assert schema_mod.storage_version_label("2.0.0") == "2.0.0"
