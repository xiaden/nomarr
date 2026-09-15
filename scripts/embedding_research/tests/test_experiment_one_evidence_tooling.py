"""Focused contracts for normalized Experiment One evidence tooling."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from scripts.embedding_research import config
from scripts.embedding_research.cleanup import GeometryResetUnavailableError, reset_analysis, reset_geometry
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.tools import _evidence

EMITTERS = tuple(sorted(Path(__file__).parents[1].joinpath("tools").glob("emit_*.py")))


def test_every_geometry_emitter_declares_normalized_surface_proof():
    """Every evidence producer is explicit about the normalized result layer."""
    assert EMITTERS
    for path in EMITTERS:
        source = path.read_text(encoding="utf-8")
        assert "normalized_result_layer" in source, path.name


def test_evidence_is_normalized_finite_and_deterministic(tmp_path, monkeypatch):
    monkeypatch.setattr(_evidence, "OUTPUT_ROOT", tmp_path)
    payload = {"value": 1, "finite": True}
    first = _evidence.write_evidence("result.json", payload).read_bytes()
    second = _evidence.write_evidence("result.json", payload).read_bytes()
    document = json.loads(first)
    assert first == second
    document["result_layer"] = _evidence.normalized_result_layer()
    assert document["result_layer"]["surface_names"]
    assert document["result_layer"]["baseline"] == {"threshold_independent": True, "block_count": 1}
    with pytest.raises(ValueError):
        _evidence.write_evidence("../outside.json", payload)


def test_scanners_detect_injected_retired_nested_marker(tmp_path):
    retired = tmp_path / "retired.json"
    retired.write_text('{"evidence_json": {"queries": []}}', encoding="utf-8")
    matches = _evidence.scan_result_layer_files(tmp_path)
    assert matches == [{"path": "retired.json", "tokens": ["evidence_json"]}]


def test_analysis_reset_table_set_and_geometry_byte_preservation(tmp_path):
    db_path = tmp_path / "research.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    blob = b"immutable-geometry\x00\xff"
    con.execute(
        "INSERT INTO song_patch_geometry (geometry_id, song_id, backbone, observation_group_sha256, "
        "stream_ref, stream_fingerprint_sha256, stream_payload_sha256, mask_ref, mask_payload_sha256, "
        "patch_count, embedding_dim, stream_dtype, stream_format_version, embed_semantics_version, "
        "preprocess_fn, preprocess_version, backbone_model_hash, audio_params, provenance_source, "
        "provenance_assumption, alignment_token, audio_content_sha256, mask_semantics_version, "
        "group_format_version, provenance_identity, geometry_semantics_version, numerical_profile_digest, "
        "geometry_blob_byte_length, geometry_blob_sha256, gram_blob, status, writer_run_id, created_at_ms, updated_at_ms) "
        "VALUES ('g', 's', 'effnet', 'o', 'stream', 'f', 'p', 'mask', 'm', 1, 1, 'float32', '1', 1, "
        "'identity', '1', 'model', '{}', 'synthetic', 'synthetic', 'a', 'audio', '1', '1', 'identity', '1', 'profile', ?, 'hash', ?, 'committed', 'run', 1, 1)",
        [len(blob), blob],
    )
    con.close()
    reset_analysis(tmp_path, db_path)
    check = duckdb.connect(str(db_path), read_only=True)
    assert check.execute("SELECT gram_blob FROM song_patch_geometry").fetchone()[0] == blob
    check.close()
    with pytest.raises(GeometryResetUnavailableError, match="GEOMETRY_RESET_UNAVAILABLE"):
        reset_geometry()


# Keep this assertion local to the test module so future schema additions cannot silently
# reintroduce disposable deletion of the immutable upstream geometry table.
def test_analysis_reset_excludes_song_patch_geometry():
    assert (
        "song_patch_geometry"
        not in __import__(
            "scripts.embedding_research.cleanup", fromlist=["_DISPOSABLE_ANALYSIS_TABLES"]
        )._DISPOSABLE_ANALYSIS_TABLES
    )
    assert config.OUTPUT_ROOT


def test_scanner_does_not_flag_legitimate_flat_evidence_json(tmp_path):
    """A flat ``evidence_json`` head-evidence column is legitimate, not the retired blob."""
    flat_evidence = {
        "geometry_id": "g-1",
        "observation_group_sha256": "0" * 64,
        "geometry_semantics_version": "1",
        "numerical_profile_digest": "profile",
        "threshold_id": "t-1",
        "structural_identity": "identity",
        "search_representation_id": "rep-1",
        "evaluation_id": "eval-1",
        "scoring_semantics_version": "1",
        "execution_id": "exec-1",
        "head": "mood",
        "segment_id": "seg-1",
        "member_patch_indices": [0, 1, 2],
        "class1": "calm",
        "searchable_weight": 0.5,
        "observed_medoid_source_index": 0,
        "observed_medoid_centrality": 0.9,
        "collapse_class_id": "c-1",
        "collapse_member_threshold_indices": [],
        "status": "done",
    }
    document = tmp_path / "flat_head_evidence.json"
    document.write_text(json.dumps({"evidence_json": flat_evidence}), encoding="utf-8")
    assert _evidence.scan_result_layer_files(tmp_path) == []


def test_scanner_does_not_flag_report_shaped_threshold_map_metadata(tmp_path):
    """A report-shaped ``threshold_map`` metadata dict is not the retired nested blob."""
    document = tmp_path / "report_metadata.json"
    document.write_text(
        json.dumps({"corrective_evidence": {"threshold_map": {"count": 3, "first_index": 0, "last_index": 2}}}),
        encoding="utf-8",
    )
    assert _evidence.scan_result_layer_files(tmp_path) == []


def test_scanner_flags_nested_evidence_json_even_when_deeper_in_document(tmp_path):
    """``evidence_json`` nested in a list is detected at any depth, not just top-level."""
    document = tmp_path / "deep_retired.json"
    document.write_text(
        json.dumps({"outer": [{"evidence_json": {"neighborhood": []}}]}),
        encoding="utf-8",
    )
    matches = _evidence.scan_result_layer_files(tmp_path)
    assert len(matches) == 1
    assert matches[0]["path"] == "deep_retired.json"
    assert "evidence_json" in matches[0]["tokens"]


def test_retired_evidence_json_returns_false_for_non_json_and_flat_documents():
    """Malformed text must not raise, and a flat ``evidence_json`` is not retired."""
    assert _evidence._retired_evidence_json("not json") is False
    assert _evidence._retired_evidence_json('{"evidence_json": {"status": "done"}}') is False
