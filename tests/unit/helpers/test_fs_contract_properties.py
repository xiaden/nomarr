"""Additive property tests for the canonical filesystem-access contract (Part A).

Companion to the frozen spec-first file ``test_fs_contract.py``. These tests add
coverage for contract properties that the frozen suite does not assert:

- ``probe_fact`` performs exactly one ``os.stat`` per call, on both the success
  and the ``OSError`` path (TOCTOU-avoidance contract).
- ``probe_fact`` lets a non-``OSError`` exception propagate unchanged.
- ``FsFact`` is a frozen + slotted value object (immutable, dict-less, hashable).
- ``canonicalize`` normalises a ``RuntimeError`` from ``Path.resolve`` to
  ``OSError(errno.ELOOP)`` and chains the original as ``__cause__``.

Every test here is purely additive: the frozen spec file is never modified.
"""

from __future__ import annotations

import dataclasses
import errno
import os
from pathlib import Path

import pytest

from nomarr.helpers.fs_contract import FsFact, canonicalize, probe_fact

pytestmark = [pytest.mark.unit]


class TestProbeFactSingleStat:
    """``probe_fact`` performs exactly one ``os.stat`` per call (TOCTOU avoidance)."""

    def test_success_path_stats_exactly_once(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A successful probe issues exactly one stat, no more."""
        target = tmp_path / "song.mp3"
        target.touch()
        original = os.stat
        calls = 0

        def _spy(*args: object, **kwargs: object) -> os.stat_result:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _spy)
        fact = probe_fact(target)

        assert fact.presence == "present"
        assert calls == 1

    def test_error_path_stats_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed probe issues exactly one stat, not a retry/second stat."""
        calls = 0

        def _spy(*_args: object, **_kwargs: object) -> os.stat_result:
            nonlocal calls
            calls += 1
            raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _spy)
        fact = probe_fact("/whatever")

        assert fact.presence == "unknown"
        assert calls == 1


class TestProbeFactNonOSErrorPropagation:
    """``probe_fact`` never swallows a non-``OSError`` exception."""

    def test_non_oserror_propagates_unchanged_by_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-OSError raised by stat propagates unchanged (identity preserved)."""
        boom = TypeError("boom")

        def _raise(*_args: object, **_kwargs: object) -> os.stat_result:
            raise boom

        monkeypatch.setattr("nomarr.helpers.fs_contract.os.stat", _raise)

        with pytest.raises(TypeError) as exc_info:
            probe_fact("/whatever")

        assert exc_info.value is boom


class TestFsFactValueObject:
    """``FsFact`` is a frozen, slotted, hashable value object."""

    def test_field_assignment_raises_frozen_instance_error(self) -> None:
        """Any field assignment raises FrozenInstanceError, an AttributeError subclass."""
        fact = FsFact(presence="present", kind=None, errno=None)

        with pytest.raises(dataclasses.FrozenInstanceError) as exc_info:
            fact.detail = "mutated"

        assert isinstance(exc_info.value, AttributeError)

    def test_instance_has_no_dict(self) -> None:
        """slots=True means instances carry no __dict__."""
        fact = FsFact(presence="present", kind=None, errno=None)

        assert not hasattr(fact, "__dict__")

    def test_equal_facts_are_hashable_and_hash_equal(self) -> None:
        """frozen=True makes facts hashable; equal facts hash equal."""
        first = FsFact(presence="unknown", kind="permission_denied", errno=errno.EACCES)
        second = FsFact(presence="unknown", kind="permission_denied", errno=errno.EACCES)

        assert first == second
        assert hash(first) == hash(second)


class TestCanonicalizeRuntimeErrorNormalisation:
    """``canonicalize`` turns a resolve ``RuntimeError`` into a chained ``OSError(ELOOP)``."""

    def test_runtime_error_becomes_eloop_oserror_chaining_cause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The original RuntimeError is preserved as __cause__ on the OSError(ELOOP)."""
        boom = RuntimeError("symlink loop")

        def _raise(self: Path, strict: bool = False) -> Path:
            raise boom

        monkeypatch.setattr(Path, "resolve", _raise)

        with pytest.raises(OSError) as exc_info:
            canonicalize("/whatever", strict=True)

        assert exc_info.value.errno == errno.ELOOP
        assert exc_info.value.__cause__ is boom
