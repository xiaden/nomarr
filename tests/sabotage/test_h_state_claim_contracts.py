"""H Phase 3 static contract gates.

These tests prevent broad integer-adapter approval and keep H's ownership
boundary explicit. Mood persistence is deliberately not implemented here: its
named tag owner must publish the schema/marker/batch contract first.

Clean-checkout boundary (Q2R-B): the formerly ignored-``artifacts`` reads now
resolve REQUIRED evidence from tracked, non-sensitive fixtures under
``tests/sabotage/fixtures/`` via a ``NOMARR_TEST_ROOT``-aware ``_root()`` helper.
The globally gitignored ``artifacts/`` tree is consulted only by one guarded
optional provenance check that is skipped when the ignored documents are absent,
so a clean checkout collects and runs this module without them.
"""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
from pathlib import Path
from typing import get_type_hints

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import ChromaprintValue
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.persistence.api.library_songs import LibrarySongsDb

_DEFAULT_ROOT = Path(__file__).parents[2]
REQUIRED_FIXTURES: tuple[str, ...] = (
    "state-claim-contracts.md",
    "state-claim-owner-gates.md",
)


def _root() -> Path:
    # NOMARR_TEST_ROOT lets the clean-checkout subprocess run this module against
    # a temporary tree that lacks the ignored artifacts/ directory.
    override = os.environ.get("NOMARR_TEST_ROOT")
    return Path(override) if override else _DEFAULT_ROOT


def _fixture(name: str) -> Path:
    return _root() / "tests/sabotage/fixtures" / name


def _assert_tracked_clean_checkout_fixture(path: Path) -> None:
    """Mirror the Q2R-A tracked-fixture containment proof for these fixtures."""
    assert path.is_file(), f"tracked evidence fixture missing: {path}"
    rel = path.relative_to(_root())
    assert rel.parts[0] == "tests", f"fixture must live under tests/: {rel}"
    assert "artifacts" not in rel.parts, f"fixture must not live under artifacts/: {rel}"
    if shutil.which("git") and (_root() / ".git").exists():
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, f"tracked fixture {rel} is gitignored (git check-ignore rc={proc.returncode})"


@pytest.mark.sabotage_check
class TestHChromaprintContract:
    def test_value_is_canonical_and_provenanced(self) -> None:
        value = ChromaprintValue("abc123", provenance="decoder:chromaprint")
        assert value.value == "abc123"
        assert value.provenance == "decoder:chromaprint"

    @pytest.mark.parametrize("value", ["", " abc", "abc ", "a b", "a\tb"])
    def test_value_rejects_empty_or_whitespace(self, value: str) -> None:
        with pytest.raises(ValueError):
            ChromaprintValue(value, provenance="decoder")

    def test_explicit_clear_is_not_hidden_in_value_command(self) -> None:
        with pytest.raises(ValueError):
            ChromaprintValue("new", provenance="decoder", expected_value="old")

    def test_set_chromaprint_is_typed_and_guarded(self) -> None:
        hints = get_type_hints(LibrarySongsDb.set_chromaprint)
        assert hints["value"] is ChromaprintValue


@pytest.mark.sabotage_check
class TestHExactHydrationAdapter:
    def test_hydration_dto_carries_no_storage_id(self) -> None:
        assert "song_id" not in inspect.signature(HydrateSongInput).parameters

    def test_hydration_adapter_is_not_a_public_result_or_wire_projection(self) -> None:
        source = Path("nomarr/helpers/dto/hydration_dto.py").read_text()
        assert "SongIdentity" not in source
        assert "to_dict" not in source

    def test_broad_resolver_requires_named_allowlist_evidence(self) -> None:
        contract = _fixture("state-claim-contracts.md")
        _assert_tracked_clean_checkout_fixture(contract)
        contract_text = contract.read_text(encoding="utf-8")
        assert "exact L/N/P allowlist" in contract_text
        assert "HydrateSongInput" in contract_text
        assert "resolve_song_identity`/`resolve_song_identities" in contract_text


@pytest.mark.sabotage_check
class TestHMoodOwnerCapabilityRefusal:
    def test_no_generic_hydration_path_claims_mood_owner(self) -> None:
        source = Path("nomarr/persistence/database/song_hydration_repo.py").read_text()
        assert "replace_mood_tags" not in source
        assert "CalibrationMoodMarker" not in source

    def test_handoff_evidence_records_missing_named_owner(self) -> None:
        evidence = _fixture("state-claim-owner-gates.md")
        _assert_tracked_clean_checkout_fixture(evidence)
        evidence_text = evidence.read_text(encoding="utf-8")
        assert "BLOCKED: no named owner contract" in evidence_text
        assert "No schema or marker semantics are invented" in evidence_text


@pytest.mark.sabotage_check
def test_h_real_evidence_guarded_when_ignored_docs_present() -> None:
    """Real ignored H/CONTRACTS provenance is asserted only when present.

    On a clean checkout this is SKIPPED, never a local PASS: the tracked fixtures
    above already carry the non-sensitive required vocabulary.
    """
    ignored_contracts = "artifacts/designs/parts/song-row-mirror-leaks-into-domain/CONTRACTS.md"
    ignored_evidence = "artifacts/designs/parts/song-row-mirror-leaks-into-domain/evidence-H-phase3-owner-gates.md"
    contracts = _root() / ignored_contracts
    evidence = _root() / ignored_evidence
    if not contracts.is_file() or not evidence.is_file():
        pytest.skip(
            "ignored H/CONTRACTS documents absent (clean checkout); "
            "non-sensitive tracked fixtures cover required vocabulary; no LOCAL_PASS claimed"
        )
    contract_text = contracts.read_text(encoding="utf-8")
    assert "exact L/N/P allowlist" in contract_text
    assert "HydrateSongInput(song_id: int, ...)" in contract_text
    assert "resolve_song_identity`/`resolve_song_identities" in contract_text
    evidence_text = evidence.read_text(encoding="utf-8")
    assert "BLOCKED: no named owner contract" in evidence_text
    assert "No schema or marker semantics are invented" in evidence_text
