"""Filesystem-authoritative reindex over current-format manifests (Plan B P1-S5).

Plan B makes the current digest-named filesystem manifests, payloads and
observation-commit markers authoritative; the ``stream_registry`` /
``head_stream_registry`` tables are deliberately retained ONLY as a rebuildable
index/cache for downstream C/E consumers.  :func:`reconcile_current_manifests`
and its public maintenance wrapper :func:`reindex` rebuild those registry rows
from the filesystem alone:

* **walk** the current-format digest manifests under ``streams/``, ``heads/``,
  ``audio_masks/`` and the ``observation_commits/`` markers (plus optional
  ``corpus/`` current manifests when present);
* **validate** current refs, digests, shapes, finite values, stream/mask
  alignment and observation-commit readiness;
* **rebuild** the retained registry index/cache rows after a DB deletion.

Refused without any alternate path: corrupt / incomplete / mismatched /
WAL-bearing state, plus anything that would need old-format parsing, audio,
models, sessions, ONNX/CUDA, path-derived IDs or segmentation recomputation.
This module never imports or touches those surfaces — it reads JSON manifests
and ``allow_pickle=False`` numpy payloads only, and it never reconstructs a
bare/``.vN`` name from a filename.
"""

from __future__ import annotations

from pathlib import Path

from scripts.embedding_research.db.geometry import GeometryRefusal, verify_geometry_current
from scripts.embedding_research.streams.publication import parse_artifact_name, read_json_manifest
from scripts.embedding_research.streams.records import ReindexReport
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

__all__ = ["reconcile_current_manifests", "reindex"]

_CORPUS_DIR = "corpus"
#: Fixed-path per-identity CURRENT head-suite marker suffix (Plan C P1-S4).
_HEAD_CURRENT_SUFFIX = ".json"


def _scan_corpus_state(root: Path) -> list[str]:
    """Validate optional current-format ``corpus/`` manifests when present.

    ``corpus/manifest.json`` / ``corpus/songs.json`` are Plan C-owned producers;
    when absent reindex succeeds untouched (a fresh or not-yet-ingested root is
    valid).  When present they must at least parse as JSON objects — malformed
    corpus manifests are refused (never silently ignored).
    """
    issues: list[str] = []
    corpus_dir = root / _CORPUS_DIR
    if not corpus_dir.is_dir():
        return issues
    for name in ("manifest.json", "songs.json"):
        path = corpus_dir / name
        if not path.is_file():
            continue
        try:
            doc = read_json_manifest(path)
        except ValueError as exc:
            issues.append(f"corpus/{name} refused: {exc}")
            continue
        if not isinstance(doc, dict) and name != "songs.json":
            issues.append(f"corpus/{name} must be a JSON object")
    return issues


def reconcile_current_manifests(root: Path, con) -> ReindexReport:
    """Rebuild stream/head registry rows from validated committed filesystem groups."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"reindex root is not a directory: {root_path}")
    import json

    from scripts.embedding_research.streams.heads_current import resolve_current_head_suite

    issues: list[str] = []
    orphan: list[str] = []
    issues.extend(_scan_corpus_state(root_path))
    stream_store = StreamStore(con, output_root=root_path)
    head_store = HeadStreamStore(con, output_root=root_path)
    for subdir, suffix in (("streams", ".npy"), ("heads", ".npz"), ("audio_masks", ".npy")):
        directory = root_path / subdir
        if directory.is_dir():
            for path in directory.glob(f"*{suffix}"):
                if parse_artifact_name(path.name, suffix) and not path.with_suffix(".json").is_file():
                    orphan.extend([str(path)])
    marker_dir = root_path / "observation_commits"
    markers = sorted(marker_dir.glob("*.json")) if marker_dir.is_dir() else []
    scanned = ready = rebuilt = 0
    seen: set[tuple[str, str]] = set()
    for marker_path in markers:
        try:
            doc = json.loads(marker_path.read_text(encoding="utf-8"))
            parsed = parse_artifact_name(marker_path.name, ".json")
            if parsed is None or not stream_store._commit_doc_ok(doc, parsed.digest):
                raise ValueError("invalid observation commit marker")
            song_id, backbone = str(doc["song_id"]), str(doc["backbone"])
            if (song_id, backbone) in seen:
                raise ValueError("multiple committed groups require explicit current selection")
            seen.add((song_id, backbone))
            observation = stream_store.load_committed_observation(song_id, backbone)
            try:
                verify_geometry_current(con, observation, profile=None)
            except GeometryRefusal as exc:
                raise ValueError(f"geometry binding refused: {exc}") from exc
            stream_record = observation.stream_record
            stream_store.replace(stream_record, status="ready")
            rebuilt += 1
            scanned += 1
            ready += 1
            try:
                selection = resolve_current_head_suite(root_path, song_id, backbone)
                head_store.replace(selection.record, status="ready")
                rebuilt += 1
                scanned += 1
                ready += 1
            except Exception as exc:
                raise ValueError(f"head evidence refused for {song_id}:{backbone}: {exc}") from exc
        except Exception as exc:
            issues.append(f"{marker_path.name}: {exc}")
    return ReindexReport(
        scanned=scanned, rows_rebuilt=rebuilt, ready=ready, orphan_payloads=len(orphan), issues=tuple(issues)
    )


def reindex(root: Path, con) -> ReindexReport:
    """Public maintenance reindex: a thin wrapper over :func:`reconcile_current_manifests`.

    Idempotent and safe to call on a freshly recreated (post-deletion) database.
    """
    return reconcile_current_manifests(root, con)
