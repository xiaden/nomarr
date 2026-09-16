"""RED tests for the corroborated-absence witness component.

``nomarr.components.library.scan_absence_comp`` (Part C) is the single owner that
can turn a same-pass directory enumeration into an authorized ``absent`` fact
(ADR-050 item 2). These tests pin, before the production exists:

* the four authorization outcomes (present / absent+resource_missing / unknown
  because the immediate parent is unreconciled or an uninspected ancestor shadows
  it / unknown fail-closed when the chain reaches the library root with no
  enumerated ancestor),
* the folder-level witness that authorizes the scanner's own vanished-folder and
  untracked-orphan sweeps (DD §8.3 defect A), and
* the zero-syscall property: the witness is set membership, never a probe.

The production module does not exist yet — this is the RED half of the plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from nomarr.components.library.scan_absence_comp import authorize_absent, scope_uninspected

if TYPE_CHECKING:
    from nomarr.helpers.fs_contract import FsFact

_MODULE = "nomarr.components.library.scan_absence_comp"


def _authorize(
    rel_path: str,
    *,
    reconciled: dict[str, frozenset[str]] | None = None,
    unreconciled: set[str] | None = None,
    vanished: set[str] | None = None,
    uninspected: set[str] | None = None,
) -> FsFact:
    """Call ``authorize_absent`` with the minimal keyword-only witness shape."""
    return authorize_absent(
        rel_path=rel_path,
        absolute_path=f"/music/{rel_path}",
        reconciled_folders=reconciled if reconciled is not None else {},
        unreconciled_folders=unreconciled if unreconciled is not None else set(),
        vanished_folders=vanished if vanished is not None else set(),
        uninspected_scope=uninspected if uninspected is not None else set(),
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestAuthorizeAbsentOutcomes:
    """The immediate-parent rule: present iff enumerated, absent iff corroborated."""

    def test_present_when_basename_is_enumerated_in_immediate_parent(self) -> None:
        fact = _authorize("f1/a.flac", reconciled={"f1": frozenset({"a.flac", "b.flac"})})

        assert fact.presence == "present"
        assert fact.kind is None
        assert fact.errno is None

    def test_absent_with_resource_missing_when_basename_missing_from_enumerated_parent(self) -> None:
        fact = _authorize("f1/a.flac", reconciled={"f1": frozenset({"b.flac"})})

        assert fact.presence == "absent"
        assert fact.kind == "resource_missing"
        assert fact.errno is None

    def test_unknown_when_immediate_parent_is_unreconciled(self) -> None:
        fact = _authorize(
            "f1/a.flac",
            reconciled={"f1": frozenset({"b.flac"})},
            unreconciled={"f1"},
        )

        assert fact.presence == "unknown"
        assert fact.kind is not None
        assert fact.kind != "resource_missing"

    def test_unknown_when_uninspected_ancestor_shadows_the_parent(self) -> None:
        fact = _authorize(
            "bad/sub/a.flac",
            reconciled={"bad/sub": frozenset(), "bad": frozenset({"sub"}), "": frozenset({"bad"})},
            uninspected={"bad"},
        )

        assert fact.presence == "unknown"
        assert fact.kind is not None
        assert fact.kind != "resource_missing"

    def test_unknown_when_chain_reaches_root_with_no_enumerated_ancestor(self) -> None:
        # Fail-closed: no ancestor (not even the root "") was enumerated this pass.
        fact = _authorize("f1/a.flac", reconciled={})

        assert fact.presence == "unknown"
        assert fact.kind is not None
        assert fact.kind != "resource_missing"

    def test_root_level_file_is_authorized_only_by_the_root_listing(self) -> None:
        assert _authorize("track.flac", reconciled={"": frozenset({"track.flac"})}).presence == "present"
        assert _authorize("track.flac", reconciled={"": frozenset({"other.flac"})}).presence == "absent"
        assert _authorize("track.flac", reconciled={}).presence == "unknown"


@pytest.mark.unit
@pytest.mark.mocked
class TestFolderLevelWitness:
    """A vanished folder is authorized via the enumeration of an enumerated ancestor."""

    def test_vanished_top_level_folder_is_absent_via_enumerated_root(self) -> None:
        fact = _authorize(
            "gone/x.flac",
            reconciled={"": frozenset({"other"})},
            vanished={"gone"},
        )

        assert fact.presence == "absent"
        assert fact.kind == "resource_missing"

    def test_vanished_nested_folder_is_absent_via_enumerated_parent(self) -> None:
        fact = _authorize(
            "a/gone/x.flac",
            reconciled={"": frozenset({"a"}), "a": frozenset({"b"})},
            vanished={"a/gone"},
        )

        assert fact.presence == "absent"
        assert fact.kind == "resource_missing"

    def test_present_but_unenumerated_ancestor_folder_fails_closed(self) -> None:
        # The ancestor "a" is enumerated in the root, but "a" itself was not
        # enumerated this pass, so nothing below it can be authorized.
        fact = _authorize("a/gone/x.flac", reconciled={"": frozenset({"a"})})

        assert fact.presence == "unknown"
        assert fact.kind is not None

    def test_untracked_orphan_parent_fails_closed_without_enumerated_ancestor(self) -> None:
        fact = _authorize("untracked/x.flac", reconciled={})

        assert fact.presence == "unknown"
        assert fact.kind is not None


@pytest.mark.unit
@pytest.mark.mocked
class TestScopeUninspected:
    """Ancestry-aware un-inspected scope, including the root."""

    def test_matches_self_ancestors_and_root(self) -> None:
        scope = {"bad", ""}

        assert scope_uninspected("bad", scope) is True
        assert scope_uninspected("bad/sub/deep", scope) is True
        assert scope_uninspected("other", scope) is True  # guarded by root ""
        assert scope_uninspected("bad", set()) is False
        assert scope_uninspected("other/x", {"bad"}) is False


@pytest.mark.unit
@pytest.mark.mocked
class TestZeroSyscallWitness:
    """The witness is set membership: no filesystem probe may be issued."""

    def test_every_outcome_resolves_with_all_fs_probes_disabled(self) -> None:
        def _boom(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("the witness must not touch the filesystem")

        cases: list[tuple[str, dict[str, object], str]] = [
            ("f1/a.flac", {"reconciled": {"f1": frozenset({"a.flac"})}}, "present"),
            ("f1/a.flac", {"reconciled": {"f1": frozenset({"b.flac"})}}, "absent"),
            ("f1/a.flac", {"reconciled": {"f1": frozenset({"b.flac"})}, "unreconciled": {"f1"}}, "unknown"),
            ("f1/a.flac", {"reconciled": {}}, "unknown"),
            ("gone/x.flac", {"reconciled": {"": frozenset({"other"})}, "vanished": {"gone"}}, "absent"),
        ]

        with (
            patch("os.stat", _boom),
            patch("os.listdir", _boom),
            patch("os.path.isfile", _boom),
            patch("os.path.exists", _boom),
            patch.object(Path, "exists", _boom),
        ):
            for rel_path, kwargs, expected in cases:
                fact = _authorize(rel_path, **kwargs)  # type: ignore[arg-type]
                assert fact.presence == expected
