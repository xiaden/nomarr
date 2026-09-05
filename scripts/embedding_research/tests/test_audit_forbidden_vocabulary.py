"""Plan A whole-tree forbidden-vocabulary audit (P1-S1).

Posture
-------
Git is the source archive and the corrective pass is a hard cut: the retained
(current) runtime and configuration foundation must contain ZERO executable
scaled / calibration / p50 / CTP-config / alias / compatibility vocabulary.
Legacy surfaces that a LATER plan (B-E) will delete are inventoried in
``scripts/embedding_research/CONTRACTS.md`` § "Plan A deletion inventory" and may
retain their historical vocabulary until they are deleted.  Historical prose
(docstrings / comments) may mention superseded terms for traceability but must
never be executable.

The audit has two layers:

1. Foundation check (hard, no allowlist): the three threshold/configuration
   files — ``helpers/thresholds.py``, ``helpers/toml.py`` and
   ``research_config.toml`` — must contain ZERO executable forbidden vocabulary
   (identifiers and configuration keys; docstring/comment prose excluded).

2. Whole-tree regression guard: every executable occurrence of a forbidden token
   in any *non-test* source/config file must be recorded in the per-token
   allowlist below (mirroring the CONTRACTS.md deletion inventory).  A new
   executable occurrence in a file that is NOT allowlisted fails the audit.

Tightening for Plans E/F: as a later plan deletes an inventory surface, it also
removes that surface's allowlist entries (in the CONTRACTS.md inventory and here);
any residual executable occurrence in a still-retained file then fails — so the
audit stays meaningful as the tree shrinks.  Test files are governed by
import/collection (a test importing a removed foundation symbol fails immediately)
and by their inventoried legacy module; they are intentionally outside this
runtime/config scan.

Interpretation recorded for QA (see step annotation): for the end of Plan A the
audit scopes its *strict executable* requirement to the threshold/config
foundation (layer 1) plus the whole-tree regression guard over non-test
runtime/config (layer 2).  Whole-tree surfaces owned by later plans
(``search_view_hash``, ANN/FAISS, per-patch membership, legacy run.py
orchestration, binned/CTP/weighted modules) are CONTRACTS.md inventory entries,
not failures, in Plan A.
"""

from __future__ import annotations

import io
import pathlib
import tokenize

_ROOT = pathlib.Path(__file__).parents[1]  # scripts/embedding_research

#: Threshold/config/alias/compatibility tokens that the retained runtime must not
#: use executably.  ``search_view_hash`` (removed Plan D P1-S2) and the ANN/FAISS
#: backends (``ANNIndex``/``ann_recall_sweep``/``faiss`` — removed under Plan D P1-S6;
#: their allowlist entries are gone, so ANY residual executable reference now fails)
#: are deleted.  Per-patch membership and binned/CTP strategy identifiers are owned by
#: Plans C/E and live in the CONTRACTS.md inventory — any retained executable reference
#: must be inventoried (allowlisted) or removed.
_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "search_view_hash",
    "std_scaled",
    "thresholdsemantics",  # ThresholdSemantics
    "validatesemantics",  # validate_semantics
    "canonical_semantics",
    "canonical_calibration_record",
    "canonical_alias",
    "canonical_threshold",
    "canonical_threshold_of",
    "archival_ctp",
    "rep_a",
    "rep_b",
    "register_legacy",
    "_classify_rowless",
    "_family_versions",
    "_next_artifact_ref",
    "annindex",  # ANNIndex
    "ann_recall_sweep",
    "faiss",  # optional ANN backend / dependency (removed under Plan D P1-S6)
    "hnsw",  # faiss HNSW ANN index flavour (removed with the FAISS backend)
    "_faiss",  # lazy FAISS-availability flag removed with the backend
    # C-owned membership surfaces retired at P1-S12 (research seg_membership relation and
    # its read helpers / column names; compact alias_of_config_id + calibration_record).
    # ``is_absorbed_outlier`` is intentionally NOT here: it is a legitimate E-owned
    # head-analysis field name for the compact reconstructed-membership flags, not the
    # retired research ``seg_membership`` column.
    "seg_membership",
    "membership_by_config_song_seg",
    "alias_of_config_id",
    "calibration_record",
    "SegMembershipRecord",
    "member_patch_idx",
    "membership_version",
)

#: Per-token allowlist of non-test files (relative to scripts/embedding_research)
#: that are inventoried deletion surfaces (CONTRACTS.md § Plan A deletion
#: inventory) and therefore may still contain the token executably until their
#: owning plan deletes them.  Tokens lower-cased.
_ALLOWLIST: dict[str, frozenset[str]] = {
    # Plan E P1-S5 audit census (2026-09-05): entries whose referenced module was
    # deleted (classify.py, strategy_ptc/segment_fn.py, strategy_binned/_optimize.py,
    # strategy_binned/_process.py, bounded_scoring.py, cache/binned_ptc.py,
    # cache_identity.py, common/analyze.py, db/binned.py, report/_binned.py) were
    # REMOVED (a deleted file can never produce a scanner hit). Entries whose retained
    # file no longer contains the token (db/_schema.py, db/head_phase.py no longer
    # carry std_scaled; db/canary.py / report/_heads.py / report/_winners.py no longer
    # carry archival_ctp; helpers/binning.py no longer carries canonical_threshold)
    # were REMOVED. Only surviving references are kept (below).
    "std_scaled": frozenset(
        {
            "common/head_analysis.py",  # prose-comment mention only (PTC_SEMANTICS note)
        }
    ),
    "rep_a": frozenset(
        {
            # retained validator names rep_a in its emitted forbidden-vocabulary
            # string list (non-executable token, intentional retention).
            "validate_fixture_report.py",
        }
    ),
    "rep_b": frozenset(
        {
            # retained validator names rep_b in its emitted forbidden-vocabulary
            # string list (non-executable token, intentional retention).
            "validate_fixture_report.py",
        }
    ),
}

#: The threshold/config foundation that must be completely executable-clean.
_FOUNDATION: tuple[str, ...] = (
    "helpers/thresholds.py",
    "helpers/toml.py",
    "research_config.toml",
)

_EMPTY_ALLOWLISTED: frozenset[str] = frozenset(
    {
        "canonical_semantics",
        "canonical_calibration_record",
        "canonical_alias",
        "canonical_threshold_of",
        "thresholdsemantics",
        "validatesemantics",
    }
)


def _executable_names(path: pathlib.Path) -> list[str]:
    """Return the lower-cased identifiers / names in Python source, excluding
    strings and comments (so docstring/comment historical prose is not counted as
    executable)."""
    text = path.read_text(encoding="utf-8")
    names: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        names = [tok.string.lower() for tok in tokens if tok.type == tokenize.NAME]
    except tokenize.TokenError:  # pragma: no cover - malformed source must fail loudly
        # A file that cannot be tokenized must never scan clean: that would silently
        # downgrade the audit's guarantee that executable hits fail.
        raise
    return names


def _config_keys(path: pathlib.Path) -> list[str]:
    """Return lower-cased non-comment content of a TOML config (keys/values)."""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(line.lower())
    return " ".join(lines).split()


def _scan_file(rel: str) -> dict[str, list[str]]:
    """Map forbidden token (lower) -> list of executable names found in `rel`."""
    path = _ROOT / rel
    if rel.endswith(".toml"):
        names = _config_keys(path)
    else:
        names = _executable_names(path)
    hits: dict[str, list[str]] = {}
    for token in _FORBIDDEN_TOKENS:
        if token in names:
            hits[token] = [n for n in names if n == token]
    return hits


def _iter_source_files() -> list[str]:
    rels: list[str] = []
    for p in _ROOT.rglob("*"):
        if "__pycache__" in p.parts:
            continue
        if p.suffix in (".py", ".toml"):
            rel = p.relative_to(_ROOT).as_posix()
            if rel.startswith("tests/"):
                continue
            # NOTE: no separate self-exclusion is needed here — this audit file lives
            # at tests/test_audit_forbidden_vocabulary.py and is therefore already
            # excluded by the tests/ prefix guard above.
            rels.append(rel)
    return rels


def test_foundation_has_no_executable_forbidden_vocabulary() -> None:
    """Layer 1: the threshold/config foundation is executable-clean (no allowlist)."""
    for rel in _FOUNDATION:
        hits = _scan_file(rel)
        assert not hits, f"{rel} contains executable forbidden vocabulary: {hits}"


def test_every_executable_forbidden_hit_is_inventoried() -> None:
    """Layer 2: any executable forbidden token in the whole non-test tree must be
    recorded in the per-token allowlist (deletion inventory)."""
    uncovered = [
        (rel, token)
        for rel in sorted(_iter_source_files())
        for token in _scan_file(rel)
        if rel not in _ALLOWLIST.get(token, frozenset())
    ]
    assert not uncovered, "executable forbidden vocabulary outside the recorded deletion inventory:\n" + "\n".join(
        f"  {rel}: {tok}" for rel, tok in uncovered
    )


def test_allowlist_matches_inventory_doc_markers() -> None:
    """Every allowlist key is a real audited token and none is orphaned."""
    for token in _ALLOWLIST:
        assert token in _FORBIDDEN_TOKENS, f"allowlist key {token!r} is not audited"
    for token in _EMPTY_ALLOWLISTED:
        assert token in _FORBIDDEN_TOKENS


def test_research_config_toml_declares_only_current_schema() -> None:
    """The shipped config parses under the strict loader (smoke; full schema tests
    live in test_toml.py)."""
    from scripts.embedding_research.helpers import toml as toml_mod

    cfg = toml_mod.load_research_config()
    assert cfg.pipeline.backbones == ("effnet",)
    # No forbidden/obsolete section is represented on the typed config.
    for forbidden in (
        "archival_ctp",
        "std_scaled",
        "calibration",
        "pooling",
        "optimization",
        "similarity",
        "stratify",
        "binning",
    ):
        assert not hasattr(cfg, forbidden)


def test_audit_itself_does_not_consume_inventory_tokens_in_foundation() -> None:
    """Sanity: the scanner treats the foundation trio as code-clean even though
    their docstrings/comments (historical prose) name the removed vocabulary."""
    for rel in _FOUNDATION:
        # docstring/comment prose is allowed; ensure the scanner reports no hits
        # (_scan_file does its own read).
        assert _scan_file(rel) == {}, rel


def test_forbidden_token_set_is_nonempty_and_stable() -> None:
    """Guard the audit token set so it is not accidentally emptied."""
    assert len(_FORBIDDEN_TOKENS) >= 10
    assert _ALLOWLIST, "allowlist must not be empty"


# ---------------------------------------------------------------------------
# P1-S5: production-boundary + no-real-corpus fixtures (foundation isolation)
# ---------------------------------------------------------------------------


def test_foundation_imports_no_production_and_no_inference_runtime() -> None:
    """The threshold/config foundation imports only the standard library: no
    ``nomarr`` production component and no onnxruntime/torch/CUDA inference
    runtime may be pulled in by ``helpers.thresholds`` or ``helpers.toml``.

    This is the production-boundary + no-real-corpus fixture: synthetic-only,
    CPU-only, and isolated in a fresh subprocess so prior test imports cannot
    mask a hidden dependency.
    """
    import subprocess
    import sys

    code = (
        "import sys; "
        "from scripts.embedding_research.helpers import thresholds, toml; "
        "names=[m for m in sys.modules if m=='onnxruntime' or m=='torch' "
        "or m.startswith('nomarr') or m.startswith('torch.') "
        "or m.startswith('onnxruntime.')]; "
        "print('BAD='+','.join(sorted(names)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT.parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert "BAD=" not in result.stdout or result.stdout.strip().endswith("BAD="), (
        f"threshold/config foundation imported production/inference runtime: {result.stdout.strip()}"
    )
