"""analyze_scope_v2 identity encode/decode round-trip contract (execution-reporting-repair Plan B).

Spec-first tests for the versioned ``analyze_scope_v2`` scope record after the corrective hard cut
(Plan B corrective P5), which removed the v1 parser/encoder/decoder and every identity-less
exemption, leaving ``analyze_scope_v2`` as the SOLE runtime analyze-scope schema:

(a) every v2 field round-trips identically encode -> decode (``encode_analyze_scope_v2`` /
    ``decode_analyze_scope_v2``);
(b) ordered member / alias determinism — ``config_ids`` canonicalizes to ascending order so
    ``canonical_config_id`` is always the lowest member and ``alias_ids`` the ordered rest;
(c) semantic-versus-disposable separation at the payload level — the semantic
    ``search_representation_hash`` never equals ``view_keyset_hash``, and ``view_keyset_hash`` and
    ``view_content_hash`` are distinct fields (the end-to-end "semantic == the REAL
    ``catalog_identity.search_representation_hash`` value" sourcing seam is asserted against a real
    compact catalog in ``test_mandatory_medoid_baseline``, which owns the compact harness);
(d) ``catalog_id`` / ``catalog_fingerprint`` retention through the round trip;
(e) the ``scope_kind`` discriminator round-trips and is COMPLETE-ness-enforcing: a ``catalog_class``
    scope missing mandatory fields refuses to encode (never round-trips as complete), an
    ``observed_baseline`` refuses to carry class fields, and a ``structural_fixture`` refuses to
    claim a catalog anchor — no identity-less exemption lets a partial scope encode as complete;
(f) the v1 machine is REMOVED from the runtime — no ``analyze_scope_v1`` encoder/prefix exists, a
    v1-style line parses to ``None`` and is never decodable as v2, and the module exposes no v1
    encoder symbol.

Research-only: no audio/model/ONNX/CUDA, no real corpus.
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.db import analyze_scope as _analyze_scope_mod
from scripts.embedding_research.db.analyze_scope import (
    SCOPE_KIND_OBSERVED_BASELINE,
    SCOPE_KIND_STRUCTURAL_FIXTURE,
    AnalyzeScopeIdentity,
    ScopeMemberIdentity,
    decode_analyze_scope_v2,
    encode_analyze_scope_v2,
    parse_analyze_scope,
)

pytestmark = pytest.mark.unit

_SEMANTIC = "a" * 64  # placeholder; real value == catalog_identity.search_representation_hash (see sourcing test)


def _member(cid: int, *, exact: str = "e" * 40) -> ScopeMemberIdentity:
    return ScopeMemberIdentity(
        config_id=cid,
        threshold_configured=0.5 if cid % 2 else 0.9,
        threshold_effective=0.5 if cid % 2 else 0.9,
        bin_mode="temporal_global",
        exact_segmentation_hash=exact,
    )


def _full_identity(**overrides) -> AnalyzeScopeIdentity:
    base = {
        "strategy_key": "catalog:effnet:max_per_candidate_segment:v1:keysetabc",
        "sim_metric": "cosine",
        "k": 10,
        "backbone": "effnet",
        "catalog_id": "catalog-0123",
        "catalog_fingerprint": "f" * 64,
        "search_representation_hash": _SEMANTIC,
        "config_ids": (3, 7),
        "members": (_member(3), _member(7)),
        "score_variant": "max_per_candidate_segment",
        "scoring_semantics_version": 1,
        "view_keyset_hash": "keysetabc",
        "view_content_hash": "viewcontentabc",
        "evaluation_corpus_hash": "corpus-hash-1",
        "evaluation_corpus_count": 4,
        "evaluation_corpus_comparable": True,
        "evaluation_corpus_missing_count": 0,
        "evaluation_corpus_missing_digest": "",
    }
    base.update(overrides)
    return AnalyzeScopeIdentity(**base)


def test_every_v2_field_round_trips_exactly():
    """(a) Full-field round trip: decode(encode(identity)) == identity, field for field."""
    identity = _full_identity(
        catalog_id="catalog-9",
        catalog_fingerprint="cf" * 32,
        search_representation_hash=_SEMANTIC,
        config_ids=(2, 5, 8),
        members=(_member(2, exact="x" * 40), _member(5, exact="y" * 40), _member(8, exact="z" * 40)),
        score_variant="max_per_candidate_segment",
        scoring_semantics_version=3,
        view_keyset_hash="kk",
        view_content_hash="cc",
        evaluation_corpus_hash="ch",
        evaluation_corpus_count=7,
        evaluation_corpus_comparable=False,
        evaluation_corpus_missing_count=2,
        evaluation_corpus_missing_digest="md",
    )
    decoded = decode_analyze_scope_v2(encode_analyze_scope_v2(identity))
    assert decoded is not None
    assert decoded == identity
    # spot-check the semantic + catalog anchor survived, plus members with per-member detail.
    assert decoded.catalog_id == "catalog-9"
    assert decoded.catalog_fingerprint == "cf" * 32
    assert decoded.search_representation_hash == _SEMANTIC
    assert [m.config_id for m in decoded.members] == [2, 5, 8]
    assert [m.exact_segmentation_hash for m in decoded.members] == ["x" * 40, "y" * 40, "z" * 40]
    assert [m.threshold_configured for m in decoded.members] == [0.9, 0.5, 0.9]
    assert decoded.evaluation_corpus_hash == "ch"
    assert decoded.evaluation_corpus_missing_digest == "md"


def test_members_ordered_but_config_ids_canonicalize_ascending():
    """(b) Ordered alias determinism: config_ids sort ascending => canonical = lowest, aliases ordered."""
    identity = AnalyzeScopeIdentity(
        strategy_key="catalog:effnet:max_per_candidate_segment:v1:keysetabc",
        sim_metric="cosine",
        k=10,
        backbone="effnet",
        catalog_id="cat-1",
        catalog_fingerprint="f" * 64,
        search_representation_hash=_SEMANTIC,
        config_ids=(9, 3, 7),  # deliberately unsorted
        members=(_member(3), _member(7), _member(9)),
        score_variant="max_per_candidate_segment",
        scoring_semantics_version=1,
    )
    assert identity.config_ids == (3, 7, 9)
    assert identity.canonical_config_id == 3
    assert identity.alias_ids == (7, 9)
    # Deterministic: same result across a re-decode.
    decoded = decode_analyze_scope_v2(encode_analyze_scope_v2(identity))
    assert decoded is not None
    assert decoded.canonical_config_id == 3
    assert decoded.alias_ids == (7, 9)


def test_observed_baseline_scope_has_no_canonical_or_aliases():
    """A medoid baseline (empty config_ids, tagged observed_baseline) is a NON-class scope."""
    identity = _full_identity(
        strategy_key="global_pool:effnet:medoid",
        scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
        config_ids=(),
        members=(),
        catalog_id="cat-1",
        search_representation_hash="",
    )
    assert identity.canonical_config_id is None
    assert identity.alias_ids == ()
    assert decode_analyze_scope_v2(encode_analyze_scope_v2(identity)) == identity


def test_semantic_and_disposable_hashes_stay_separate():
    """(c) Payload separation: semantic search_representation_hash != view_keyset_hash != view_content_hash."""
    identity = _full_identity(
        view_keyset_hash="keysetabc",
        view_content_hash="viewcontentabc",
    )
    # Never conflate semantic with disposable, and never conflate the two disposable hashes.
    assert identity.search_representation_hash != identity.view_keyset_hash
    assert identity.search_representation_hash != identity.view_content_hash
    assert identity.view_keyset_hash != identity.view_content_hash
    payload = parse_analyze_scope(encode_analyze_scope_v2(identity))
    assert payload["search_representation_hash"] == _SEMANTIC
    assert payload["view_keyset_hash"] == "keysetabc"
    assert payload["view_content_hash"] == "viewcontentabc"
    assert payload["search_representation_hash"] != payload["view_keyset_hash"]


def test_catalog_id_and_fingerprint_retained():
    """(d) The durable catalog anchor (catalog_id + catalog_fingerprint) survives the round trip."""
    identity = _full_identity(catalog_id="catalog-AAA", catalog_fingerprint="fp" * 32)
    decoded = decode_analyze_scope_v2(encode_analyze_scope_v2(identity))
    assert decoded is not None
    assert decoded.catalog_id == "catalog-AAA"
    assert decoded.catalog_fingerprint == "fp" * 32


def test_partial_real_class_scope_refuses_to_encode():
    """(e) A partial catalog-class scope marked complete refuses to encode (never round-trips)."""
    # Real catalog anchor + config_ids, but missing fingerprint / semantic hash / members.
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            AnalyzeScopeIdentity(
                strategy_key="catalog:effnet:max_per_candidate_segment:v1:keysetabc",
                sim_metric="cosine",
                k=10,
                backbone="effnet",
                catalog_id="catalog-1",
                config_ids=(3,),
            )
        )
    # Members present but a member lacks its exact segmentation hash => still partial.
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(
                members=(ScopeMemberIdentity(config_id=3, threshold_configured=0.5, threshold_effective=0.5),)
            )
        )
    # Members present but a member lacks configured/effective thresholds => still partial.
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(members=(ScopeMemberIdentity(config_id=3, exact_segmentation_hash="e" * 40),))
        )
    # A catalog-class scope missing its score/scoring semantics is also refused.
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(score_variant="", scoring_semantics_version=0),
        )


def test_structural_and_baseline_scopes_encode_via_their_kind_discriminator():
    """Structural fixtures and non-class baselines encode COMPLETE only under their tagged v2 kind.

    There is no identity-less empty-field exemption: a catalog-less structural row must be tagged
    ``structural_fixture`` and a non-class baseline must be tagged ``observed_baseline`` — an
    untagged (default ``catalog_class``) scope carrying the same fields is REFUSED because it claims
    a real catalog class it does not carry.
    """
    # Structural fixture (no real catalog anchor): tagged structural_fixture encodes; the same
    # fields left as default catalog_class refuse (a class claims an anchor it lacks).
    structural = _full_identity(
        scope_kind=SCOPE_KIND_STRUCTURAL_FIXTURE,
        catalog_id="",
        catalog_fingerprint="",
        search_representation_hash="",
    )
    assert decode_analyze_scope_v2(encode_analyze_scope_v2(structural)) == structural
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(
                catalog_id="",
                catalog_fingerprint="",
                search_representation_hash="",
            )  # default scope_kind == catalog_class but no anchor => incomplete class
        )
    # A structural_fixture scope must not claim a catalog_id.
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(
                scope_kind=SCOPE_KIND_STRUCTURAL_FIXTURE,
                search_representation_hash="",
                catalog_id="catalog-1",
            )
        )
    # Observed baseline: tagged observed_baseline encodes; carrying class fields is refused.
    baseline = _full_identity(
        strategy_key="global_pool:effnet:medoid",
        scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
        catalog_id="catalog-1",
        search_representation_hash="",
        config_ids=(),
        members=(),
    )
    assert decode_analyze_scope_v2(encode_analyze_scope_v2(baseline)) == baseline
    with pytest.raises(ValueError):
        encode_analyze_scope_v2(
            _full_identity(
                strategy_key="global_pool:effnet:medoid",
                scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
                search_representation_hash="",
                config_ids=(3,),  # a baseline is never a class
                members=(_member(3),),
            )
        )


def test_v1_machine_is_removed_no_parseable_or_encodable_v1():
    """(f) The runtime has exactly one analyze-scope schema — v2; the v1 machine is gone.

    There is no v1 encoder symbol, no ``analyze_scope_v1`` prefix is ever emitted, and a
    v1-formatted line parses to ``None`` and is never decodable as v2 (never reinterpreted as
    current data).  A non-scope/unknown line is likewise not a scope.
    """
    # No v1 encoder / prefix symbols remain on the module (forbidden-vocabulary spec-first).
    assert not hasattr(_analyze_scope_mod, "encode_analyze_scope")
    assert not hasattr(_analyze_scope_mod, "_SCOPE_PREFIX")

    # A v1-prefixed line is not a v2 scope: parse => None, decode => None.
    v1_line = 'analyze_scope_v1|{"strategy_key":"catalog:effnet:max_per_candidate_segment:v1:k","sim_metric":"cosine","k":10,"backbone":"effnet","config_ids":[4,9]}'
    assert parse_analyze_scope(v1_line) is None
    assert decode_analyze_scope_v2(v1_line) is None
    # No current encoder emits the v1 prefix.
    v2 = encode_analyze_scope_v2(_full_identity())
    assert v2.startswith("analyze_scope_v2|")
    assert "analyze_scope_v1" not in v2
    assert parse_analyze_scope(v2) is not None
    # Unknown/foreign lines are not scopes at all.
    assert parse_analyze_scope("run_provenance|whatever") is None
    assert parse_analyze_scope("") is None
    # Round-trip preserves the explicit scope_kind.
    for kind in (SCOPE_KIND_OBSERVED_BASELINE, SCOPE_KIND_STRUCTURAL_FIXTURE):
        identity = _full_identity(
            strategy_key="global_pool:effnet:medoid"
            if kind == SCOPE_KIND_OBSERVED_BASELINE
            else "catalog:effnet:max_per_candidate_segment:v1:keysetabc",
            scope_kind=kind,
            catalog_id="" if kind == SCOPE_KIND_STRUCTURAL_FIXTURE else "catalog-1",
            catalog_fingerprint="" if kind == SCOPE_KIND_STRUCTURAL_FIXTURE else "f" * 64,
            search_representation_hash="",  # observed_baseline and structural_fixture carry no class semantic
            config_ids=() if kind == SCOPE_KIND_OBSERVED_BASELINE else (3, 7),
            members=() if kind == SCOPE_KIND_OBSERVED_BASELINE else (_member(3), _member(7)),
        )
        decoded = decode_analyze_scope_v2(encode_analyze_scope_v2(identity))
        assert decoded is not None
        assert decoded.scope_kind == kind
        assert decoded == identity
