"""CPU-only verification of current geometry-era observation artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from scripts.embedding_research.streams.publication import parse_artifact_name

_log = logging.getLogger(__name__)

# current-format digest payload families: <subdir> -> payload suffix.
_PAYLOAD_FAMILIES: tuple[tuple[str, str], ...] = (
    ("streams", ".npy"),
    ("heads", ".npz"),
    ("audio_masks", ".npy"),
)


@dataclass
class VerificationReport:
    """Outcome of a current-format artifact audit (module CONTRACTS type)."""

    verified: int = 0
    recovered: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _file_sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_payload_families(root: Path, *, strict: bool, report: VerificationReport) -> None:
    for sub, suffix in _PAYLOAD_FAMILIES:
        base = root / sub
        if not base.is_dir():
            continue
        for payload in sorted(base.glob(f"*{suffix}")):
            identity = parse_artifact_name(payload.name, suffix)
            if identity is None:
                # Not a current-format digest name — outside the current grammar,
                # never classified, never hashed (current names only).
                continue
            sibling = payload.with_suffix(".json")
            if not sibling.is_file():
                report.refusals.append(f"{sub}/{payload.name}: current-format payload has no sibling manifest")
                continue
            try:
                manifest = json.loads(sibling.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                report.refusals.append(f"{sub}/{payload.name}: sibling manifest is unreadable/malformed")
                continue
            if not isinstance(manifest, dict):
                report.refusals.append(f"{sub}/{payload.name}: sibling manifest is not a JSON object")
                continue
            report.verified += 1
            if strict:
                _strict_payload_check(sub, payload, suffix, identity.digest, manifest, report)


def _strict_payload_check(
    sub: str,
    payload: Path,
    suffix: str,
    expected_digest: str,
    manifest: dict,
    report: VerificationReport,
) -> None:
    """Freshly hash *payload* and validate its loaded content (shape/finite/dtype).

    The structural check is family-aware via *sub*: ``streams`` (float .npy) and
    ``heads`` (per-key float .npz) must carry finite floating data, while
    ``audio_masks`` payloads are uint8 masks by contract (never NaN/Inf) whose
    length must equal the ``patch_count`` declared by the sibling *manifest*.
    """
    try:
        actual = _file_sha256_hex(payload)
    except OSError:
        report.refusals.append(f"{sub}/{payload.name}: unreadable during strict digest verification")
        return
    if actual != expected_digest:
        report.refusals.append(
            f"{sub}/{payload.name}: payload digest {actual[:16]}… does not match its name digest "
            f"{expected_digest[:16]}… (payload tampered or corrupted) — run verify --strict"
        )
        return
    # shape / dtype / finiteness structural check of the current payload.
    try:
        if suffix == ".npz":
            data = np.load(payload, allow_pickle=False)
            for key in data.files:
                arr = data[key]
                if not np.issubdtype(arr.dtype, np.floating):
                    report.refusals.append(f"{sub}/{payload.name}[{key}]: non-floating head payload")
                    return
                if not np.isfinite(arr).all():
                    report.refusals.append(f"{sub}/{payload.name}[{key}]: non-finite head payload")
                    return
        else:
            arr = np.load(payload, allow_pickle=False)
            if sub == "audio_masks":
                patch_count = manifest.get("patch_count")
                if not isinstance(patch_count, int):
                    report.refusals.append(f"{sub}/{payload.name}: sibling manifest carries no patch_count")
                    return
                if arr.dtype != np.uint8:
                    report.refusals.append(f"{sub}/{payload.name}: mask payload is not uint8")
                    return
                if arr.ndim != 1 or arr.size != patch_count:
                    report.refusals.append(
                        f"{sub}/{payload.name}: mask payload length {arr.size} != declared patch_count {patch_count}"
                    )
                    return
            else:
                if not np.issubdtype(arr.dtype, np.floating):
                    report.refusals.append(f"{sub}/{payload.name}: non-floating payload")
                    return
                if not np.isfinite(arr).all():
                    report.refusals.append(f"{sub}/{payload.name}: non-finite payload")
                    return
    except (OSError, ValueError):
        report.refusals.append(f"{sub}/{payload.name}: payload unreadable/unloadable during strict verification")


def _verify_geometry_artifacts(
    root: Path,
    *,
    report: VerificationReport,
    con: Any = None,
    profile: Any = None,
) -> None:
    """Verify every committed observation is bound to its current persisted geometry.

    Filesystem-only audits (``con is None``) skip this seam because the geometry identity is
    owned by the research DB.  With a connection, a missing/stale/duplicate/corrupt binding is
    a refusal and never silently ignored.
    """
    if con is None:
        return
    from scripts.embedding_research.db.geometry import GeometryRefusal, verify_geometry_current
    from scripts.embedding_research.streams.store import StreamStore

    marker_dir = root / "observation_commits"
    if not marker_dir.is_dir():
        return
    store = StreamStore(con, output_root=root)
    for marker in sorted(marker_dir.glob("*.json")):
        try:
            doc = json.loads(marker.read_text(encoding="utf-8"))
            observation = store.load_committed_observation(str(doc["song_id"]), str(doc["backbone"]))
            record = verify_geometry_current(con, observation, profile=profile)
        except GeometryRefusal as exc:
            report.refusals.append(f"geometry {marker.name}: {exc.code}: {exc}")
            continue
        except Exception as exc:  # store/schema refusal is a fail-closed refusal
            report.refusals.append(f"geometry {marker.name}: INTEGRITY_REFUSED: {exc}")
            continue
        if record is None:
            report.refusals.append(
                f"geometry {marker.name}: INTEGRITY_REFUSED: no committed geometry for the current observation"
            )


def verify_current_artifacts(
    root: Path,
    *,
    strict: bool = False,
    con: Any = None,
    profile: Any = None,
) -> VerificationReport:
    """Audit the current-format artifacts under *root* (see module docstring).

    Returns a :class:`VerificationReport`; it never raises on a corrupt tree —
    the caller (run.py) maps refusals to a nonzero exit.  When *con* is supplied the
    DB-backed geometry binding seam is verified too; without it the audit stays
    filesystem-only.
    """
    root = Path(root)
    report = VerificationReport()

    # Corpus manifest presence/parse is informational (corpus may not exist yet).
    corpus_manifest = root / "corpus" / "manifest.json"
    if corpus_manifest.is_file():
        try:
            data = json.loads(corpus_manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                report.refusals.append("corpus/manifest.json is not a JSON object")
        except (OSError, ValueError):
            report.refusals.append("corpus/manifest.json is unreadable/malformed")

    _verify_payload_families(root, strict=strict, report=report)
    _verify_geometry_artifacts(root, report=report, con=con, profile=profile)
    return report
