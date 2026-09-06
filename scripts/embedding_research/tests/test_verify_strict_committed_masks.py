"""Strict verify must PASS over an intact committed-mask fixture tree.

Regression for the MINOR structural-verify defect: ``_strict_payload_check``
required a floating dtype for EVERY payload family, but committed audio masks are
``uint8[P]`` by contract (the mask store writes ``MASK_DTYPE = "uint8"`` and the
``_mask_payload_ok`` predicate requires ``dtype == uint8`` and ``len ==
patch_count``).  ``verify --strict`` therefore refused valid committed masks with
a "non-floating payload" false positive.  The strict structural check is now
family-aware via ``sub``:

* ``audio_masks`` (bare ``.npy``): ``uint8``, 1-D, length ``== patch_count``
  declared by the sibling manifest — never floating/finite (uint8 is never
  NaN/Inf).
* ``streams`` (bare ``.npy``) and ``heads`` (``.npz``): float + finite (unchanged).

The digest-mismatch refusal and all non-strict behavior are unchanged.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research import verify

if TYPE_CHECKING:
    import pathlib


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _npy_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


def _commit_writer(root: pathlib.Path, sub: str, song: str, backbone: str, arr: np.ndarray) -> pathlib.Path:
    """Write ``arr`` as a digest-named current-format payload, return its path."""
    data = _npy_bytes(arr)
    subdir = root / sub
    subdir.mkdir(parents=True, exist_ok=True)
    name = f"{song}.{backbone}.{_sha256(data)}.npy"
    payload = subdir / name
    payload.write_bytes(data)
    return payload


def _write_manifest(payload: pathlib.Path, manifest: dict) -> None:
    payload.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")


def _observation_group(root: pathlib.Path, song: str, backbone: str, stream: np.ndarray, mask: np.ndarray):
    """Publish one complete current-format group: a float stream + a committed uint8 mask."""
    stream_payload = _commit_writer(root, "streams", song, backbone, np.ascontiguousarray(stream, dtype=np.float32))
    _write_manifest(stream_payload, {"kind": "stream", "schema_version": "1"})

    mask_payload = _commit_writer(root, "audio_masks", song, backbone, np.ascontiguousarray(mask, dtype=np.uint8))
    mask_bytes = mask_payload.read_bytes()
    _write_manifest(
        mask_payload,
        {
            "kind": "mask",
            "schema_version": "1",
            "payload_sha256": _sha256(mask_bytes),
            "song_id": song,
            "backbone": backbone,
            "patch_count": int(mask.size),
        },
    )
    return stream_payload, mask_payload


def test_strict_verify_passes_committed_uint8_mask_tree(tmp_path):
    """``verify --strict`` PASSES an intact committed-mask tree (uint8 mask not refused)."""
    stream = np.arange(12, dtype=np.float32).reshape(3, 4)  # patch_count 3
    mask = np.array([1, 0, 1], dtype=np.uint8)  # uint8[3] — non-floating by contract
    _stream_payload, mask_payload = _observation_group(tmp_path, "s1", "effnet", stream, mask)
    assert mask_payload.is_file()

    report = verify.verify_current_artifacts(tmp_path, strict=True)
    # 1 stream payload + 1 committed uint8 mask payload, neither refused.
    assert report.verified == 2, report.verified
    assert report.refusals == [], report.refusals


def test_strict_verify_refuses_tampered_committed_mask_only_under_strict(tmp_path):
    """A same-size tamper of a committed uint8 mask is refused ONLY under strict."""
    stream = np.arange(12, dtype=np.float32).reshape(3, 4)
    mask = np.array([1, 0, 1], dtype=np.uint8)
    _stream_payload, mask_payload = _observation_group(tmp_path, "s1", "effnet", stream, mask)

    baseline = verify.verify_current_artifacts(tmp_path, strict=True)
    assert baseline.refusals == [], baseline.refusals

    # Rewrite the mask payload in place (digest-name + sibling manifest kept), same size.
    data = bytearray(mask_payload.read_bytes())
    data[-1] ^= 0xFF
    assert len(data) == mask_payload.stat().st_size
    mask_payload.write_bytes(bytes(data))

    # Non-strict never rehashes, so it does not catch the mask tamper.
    non_strict = verify.verify_current_artifacts(tmp_path, strict=False)
    assert non_strict.refusals == [], non_strict.refusals
    # Strict rehashes and refuses the tampered committed mask (digest check unchanged).
    strict = verify.verify_current_artifacts(tmp_path, strict=True)
    assert any("does not match its name digest" in r for r in strict.refusals), strict.refusals
