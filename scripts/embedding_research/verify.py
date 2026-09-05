"""``python run.py verify [--strict]`` — current-format artifact audit.

DD durable-artifact contract: verify validates current-format filename-to-manifest
identity (every payload has a sibling manifest that parses), payload
shape/finiteness, the current catalog, and a clean catalog close (no non-empty
sibling WAL).  ``--strict`` freshly rehashes every current payload (recomputing
the payload digest and comparing it to the digest that names the file), so an
mtime-preserving same-size tamper is caught only under strict verification.
Commit markers (``observation_commits/``) are NOT validated here — that is
``reindex``'s scope (``streams/reindex.py``).  Verify OWNS read-write WAL
recovery/checkpoint of a WAL-bearing current catalog (recovering it, then
re-validating) and reports corruption as refusals.

Non-strict never rehashes and never mutates payloads; the only filesystem
mutation verify performs (both modes) is the verify-owned catalog WAL
recovery/checkpoint.  Verify is CPU-only: it never opens audio/models/sessions.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from scripts.embedding_research import catalog_storage
from scripts.embedding_research.streams.publication import parse_artifact_name

_log = logging.getLogger(__name__)

# current-format digest payload families: <subdir> -> payload suffix.
_PAYLOAD_FAMILIES: tuple[tuple[str, str], ...] = (
    ("streams", ".npy"),
    ("heads", ".npz"),
    ("audio_masks", ".npy"),
)
_CATALOGS_DIR = "catalogs"
_CATALOGS_CURRENT = "current.json"
_STRAY_HINT = "run cleanup --scope stray"


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
                # never classified, never hashed (DD: no legacy-name handling).
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
                _strict_payload_check(sub, payload, suffix, identity.digest, report)


def _strict_payload_check(
    sub: str,
    payload: Path,
    suffix: str,
    expected_digest: str,
    report: VerificationReport,
) -> None:
    """Freshly hash *payload* and validate its loaded content (shape/finite/dtype)."""
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
            if not np.issubdtype(arr.dtype, np.floating):
                report.refusals.append(f"{sub}/{payload.name}: non-floating payload")
                return
            if not np.isfinite(arr).all():
                report.refusals.append(f"{sub}/{payload.name}: non-finite payload")
                return
    except (OSError, ValueError):
        report.refusals.append(f"{sub}/{payload.name}: payload unreadable/unloadable during strict verification")


def _verify_catalog(root: Path, *, report: VerificationReport) -> None:
    """Validate the current catalog; verify OWNS read-write WAL recovery/checkpoint."""
    catalogs = root / _CATALOGS_DIR
    current_file = catalogs / _CATALOGS_CURRENT
    if not catalogs.is_dir() or not current_file.is_file():
        report.issues.append("no current catalog selected (no catalogs/current.json) — nothing to verify")
        return

    def _open_verified() -> tuple[Any | None, str | None]:
        """Return (handle, None) on success or (None, wal_msg) when WAL-bearing.

        Non-WAL failures are appended to ``report.refusals`` here.
        """
        try:
            return catalog_storage.open_current_catalog(root, verify=True), None
        except catalog_storage.CatalogWalError as exc:
            return None, str(exc)
        except (catalog_storage.CatalogIncompleteError, catalog_storage.CatalogMismatchError) as exc:
            report.refusals.append(f"current catalog refused: {exc}")
            return None, None
        except Exception as exc:  # pragma: no cover - defensive
            report.refusals.append(f"current catalog refusal: {exc}")
            return None, None

    def _record_verified(handle: Any | None) -> bool:
        if handle is None:
            return False
        try:
            report.verified += 1
            _log.debug("verified current catalog %s", getattr(handle, "catalog_id", "?"))
        finally:
            with contextlib.suppress(Exception):
                handle.con.close()
        return True

    handle, wal_msg = _open_verified()
    if _record_verified(handle):
        return
    if wal_msg is None:
        # A non-WAL refusal was already appended by _open_verified.
        return

    # WAL-bearing current catalog: verify owns read-write recovery/checkpoint.
    try:
        selection = json.loads(current_file.read_text(encoding="utf-8"))
        catalog_id = selection.get("catalog_id")
    except (OSError, ValueError):
        report.refusals.append("catalogs/current.json is unreadable/malformed")
        return
    if not catalog_id:
        report.refusals.append("catalogs/current.json does not select a catalog_id")
        return
    db = catalogs / catalog_id / "catalog.duckdb"
    if not db.is_file():
        report.refusals.append(f"current catalog {catalog_id}: catalog.duckdb missing (WAL-bearing refusal {wal_msg})")
        return
    try:
        with duckdb.connect(str(db), read_only=False) as con:
            con.execute("CHECKPOINT")
        report.recovered.append(catalog_id)
    except Exception as exc:
        report.refusals.append(f"current catalog {catalog_id}: WAL recovery/checkpoint failed: {exc}")
        return
    # Re-validate the recovered catalog.
    handle2, wal_msg2 = _open_verified()
    if wal_msg2 is not None:
        report.refusals.append(f"current catalog {catalog_id}: still WAL-bearing after recovery ({wal_msg2})")
        return
    if not _record_verified(handle2):
        report.refusals.append(f"current catalog {catalog_id}: still refused after WAL recovery/checkpoint")


def verify_current_artifacts(root: Path, *, strict: bool = False) -> VerificationReport:
    """Audit the current-format artifacts under *root* (see module docstring).

    Returns a :class:`VerificationReport`; it never raises on a corrupt tree —
    the caller (run.py) maps refusals to a nonzero exit.
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
    _verify_catalog(root, report=report)
    return report
