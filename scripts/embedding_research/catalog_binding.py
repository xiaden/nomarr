"""Fail-closed catalog-to-observation binding seam (Apparatus Plan A P1-S2).

Every derived phase that consumes a compact catalog — disposable search-view gathering,
segmented catalog analysis, the observed global-medoid baseline, and shared head
analysis — must operate over the SAME committed observation version the catalog was
built over.  ``build_segmentation_catalog`` records that immutable observation-version
evidence (stream/mask refs + digests, commit identity, patch count/alignment, audio
fingerprint, mask semantics, and group format version) in the compact
``observation_evidence`` table per requested ``(song_id, backbone)`` and folds it into
catalog identity (see :func:`catalog_identity.catalog_fingerprint` /
``song_signature``).

This module is the ONE seam that binds a derived phase to that recorded evidence: it
re-reads the CURRENT committed observation group (filesystem-authoritative) for each
requested ``(song_id, backbone)`` and compares it EXACTLY (every evidence field, not a
subset) against the recorded catalog row.  A superseded group — a NEWER committed group
selected after the catalog was built — as well as an older/mismatched/corrupt/absent
group is REFUSED with a typed :class:`CatalogObservationBindingError`.  There is NO
fallback to another committed group, NO mask-less interpretation, and NO alternate
artifact reader: derived phases are never silently rebound to a different observation
version.

This module owns no schema; the ``observation_evidence`` column-order vocabulary lives in
``catalog_storage`` (the compact-schema column-order home).  This module is pure (the
only reads are the catalog ``observation_evidence`` rows and the committed-group identity
reader), so it is importable by every derived-phase module and ``run.py`` without a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.embedding_research.catalog_storage import (
    OBSERVATION_EVIDENCE_COLS,
    OBSERVATION_EVIDENCE_TABLE,
)
from scripts.embedding_research.streams.records import StreamStoreError

if TYPE_CHECKING:
    from collections.abc import Sequence


__all__ = [
    "CatalogObservationBindingError",
    "bind_catalog_observation_identity",
    "verify_catalog_observation_binding",
]


class CatalogObservationBindingError(RuntimeError):
    """A derived phase's requested observation group no longer matches the catalog evidence.

    Raised (fail closed) when the CURRENT committed observation group for a requested
    ``(song_id, backbone)`` differs from the evidence the selected catalog recorded at
    build time — a superseded/newer/older/mismatched/corrupt/absent group.  The derived
    phase must refuse; it never silently selects another committed group.
    """


def _identity_fields(identity) -> dict[str, object]:
    """Project a committed group identity onto the catalog evidence column vocabulary."""
    return {
        "song_id": identity.song_id,
        "backbone": identity.backbone,
        "stream_ref": identity.stream_ref,
        "stream_digest": identity.stream_digest,
        "mask_ref": identity.mask_ref,
        "mask_digest": identity.mask_digest,
        "commit_sha256": identity.commit_sha256,
        "alignment_token": identity.alignment_token,
        "patch_count": int(identity.patch_count),
        "audio_content_sha256": identity.audio_content_sha256,
        "mask_semantics_version": identity.mask_semantics_version,
        "group_format_version": identity.group_format_version,
    }


def _current_identity(stream_store, song_id: str, backbone: str):
    """The current committed group identity via any committed-identity seam, or ``None``."""
    identity = getattr(stream_store, "committed_identity", None)
    if identity is not None:
        try:
            return identity(song_id, backbone)
        except StreamStoreError:
            return None
    loader = getattr(stream_store, "load_committed_identity", None)
    if loader is not None:
        try:
            return loader(song_id, backbone)
        except StreamStoreError:
            return None
    raise CatalogObservationBindingError(
        "the provided stream seam exposes no committed-observation identity reader; "
        "a catalog-bound derived phase requires a store-backed current committed group"
    )


def verify_catalog_observation_binding(con, stream_store, *, backbone: str, song_ids: Sequence[str]) -> None:
    """Fail-closed: verify every requested ``(song_id, backbone)`` is STILL the catalog's committed version.

    For each requested ``song_id`` re-reads the catalog's recorded ``observation_evidence``
    row for ``(song_id, backbone)`` and the CURRENT committed group identity, and compares
    them field-by-field EXACTLY.  Raises :class:`CatalogObservationBindingError` on:
      * no recorded evidence in the catalog for a requested ``(song_id, backbone)``
        (the catalog was not built over that observation — nothing to bind to),
      * no current committed group (absent / corrupt / uncommitted — fail closed),
      * ANY evidence-field mismatch, including a SUPERSEDED group (a NEWER committed group
        selected after the catalog was built), an OLDER group, or a partially-identical group.

    On success every requested ``(song_id, backbone)`` provably matches the catalog-bound
    observation version exactly; the caller may then gather/search/analyze/baseline/head-run
    over that catalog with confidence it has not been silently rebound.
    """
    for song_id in song_ids:
        recorded = con.execute(
            f"SELECT {', '.join(OBSERVATION_EVIDENCE_COLS)} FROM {OBSERVATION_EVIDENCE_TABLE} "
            "WHERE song_id = ? AND backbone = ?",
            [song_id, backbone],
        ).fetchone()
        if recorded is None:
            raise CatalogObservationBindingError(
                f"catalog holds no recorded observation evidence for requested "
                f"({song_id!r}, {backbone!r}); the catalog was not built over this committed "
                "observation — refusing (no unrecorded observation may be gathered/searched)"
            )
        recorded_fields = dict(zip(OBSERVATION_EVIDENCE_COLS, recorded, strict=False))
        current = _current_identity(stream_store, song_id, backbone)
        if current is None:
            raise CatalogObservationBindingError(
                f"no current committed observation group for ({song_id!r}, {backbone!r}) "
                "matching the catalog evidence; the catalog-bound observation is absent, "
                "corrupt, or uncommitted — refusing"
            )
        current_fields = _identity_fields(current)
        mismatched = [
            field for field in OBSERVATION_EVIDENCE_COLS if str(current_fields[field]) != str(recorded_fields[field])
        ]
        if mismatched:
            detail = "; ".join(
                f"{field}: catalog={recorded_fields[field]!r} current={current_fields[field]!r}"
                for field in mismatched[:6]
            )
            raise CatalogObservationBindingError(
                f"catalog observation binding refused for ({song_id!r}, {backbone!r}): the "
                f"current committed observation group does not EXACTLY match the catalog "
                f"evidence ({detail}); a superseded/newer/older/mismatched group is never "
                "silently selected"
            )


def bind_catalog_observation_identity(con, stream_store, *, backbone: str, song_ids: Sequence[str]) -> None:
    """Alias for :func:`verify_catalog_observation_binding` (explicit bind semantics)."""
    verify_catalog_observation_binding(con, stream_store, backbone=backbone, song_ids=song_ids)
