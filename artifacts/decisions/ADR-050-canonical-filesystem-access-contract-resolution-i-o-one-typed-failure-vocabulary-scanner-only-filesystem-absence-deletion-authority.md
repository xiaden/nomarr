# ADR-050: Canonical filesystem-access contract (resolution ≠ I/O; one typed failure vocabulary; scanner-only filesystem-absence deletion authority)

**Status:** Accepted  
**Date:** 2026-09-15  
**Tags:** filesystem, path-resolution, error-taxonomy, architecture  
**Source Log:** nyx#L55  

## Context

Nomarr fuses three distinct concerns into one path-validation surface — path/config resolution, filesystem availability, and operation-specific I/O failure. `path_comp.build_library_path_from_db(..., check_disk=True)` performs filesystem checks as part of resolution, and callers (tag writeback, ML processing, scanning, playlist output) interpret the resulting statuses differently. Boolean preflight APIs (`Path.exists()`/`is_file()`, `os.path.isfile/exists`) destroy errno fidelity, so transient NAS conditions, permission denial, stale mounts, and bare `ENOENT` (autofs answers `-ENOENT` while mounted) are indistinguishable from authoritative absence. The false-absence sources are shared producers upstream of four user-data delete consumers, so a storage outage could delete persisted songs; the tag-write path classified retryability from human-readable error strings. Measured cost: ~4-5 stat-class syscalls per file and every folder enumerated twice (~200k-750k NAS round-trips per full scan at 50k-150k songs). The scanner's existing reconciliation invariant — inability to inspect storage is not proof that files are absent — must be generalised, not regressed.

## Decision

1. Path resolution is semantic/config-only (which library owns the path, normalized relative path, absolute resolved path, structural/config validity). The real filesystem operation is authoritative; resolution performs no preflight disk checks merely to predict whether a later operation may succeed, and TOCTOU-shaped "check existence then perform the real operation" is avoided unless the metadata probe is itself the requested behaviour.

2. One typed filesystem failure vocabulary: `FsFact` carrying a tri-state `presence` (`present`/`absent`/`unknown`) plus a `kind` from a fixed stdlib-only taxonomy (`resource_missing`, `unconfirmed_missing`, `permission_denied`, `storage_unavailable`, `transient_io`, `storage_full`, `read_only_fs`, `invalid_path`, `wrong_resource_type`, `unknown`) and the raw `errno`/`detail`. `absent` requires same-pass enumeration corroboration and is NEVER authorized by a bare `ENOENT`. Produced by one shared stdlib-only classifier/probe; no third-party filesystem abstraction.

3. Deletion authority: scanner reconciliation is the sole authority for automatic Song deletion based on filesystem absence. Delete authority is removed from ML processing (`process_file_wf`) and from reconciliation's `not_found` branch. Explicit semantic/configuration deletion policies may remain separate deletion authorities, but they must never infer filesystem absence from a failed or inconclusive filesystem operation — `not_found`, `unconfirmed_missing`, `storage_unavailable`, `permission_denied`, `transient_io`, or any other non-authoritative filesystem condition never reaches a Song-deletion path. `delete_invalid` is scoped to genuine config/semantic invalidity only.

4. `pathlib`↔`os.path` divergence rule: contract boundaries classify with `os.stat` + `errno`, never `Path.exists()/is_file()` or `os.path.isfile/exists` (their boolean API loses errno), and `Path.resolve()`'s `RuntimeError` (symlink loop) is normalised to `invalid_path`.

Explicitly NOT owned by this decision: the tag-write retry budget, partial-success publication, and Navidrome rescan policy (see ADR-051).

## Consequences

Positive: one lossless failure vocabulary shared by scanner, audio loader, tag reader, and tag writer, each retaining its own policy; the false-absence → destructive-delete class is closed by construction; per-file preflight probes are removed (reducing syscall amplification, not increasing it); the scanner's bounded bulk enumeration and its "cannot-inspect is not absence" precedent are preserved; the SMB/CIFS unlink-before-rename window and the uncaught symlink-loop `RuntimeError` are addressed by the companion plans.

Negative / accepted: the contract is fact-only — it reports, it does not decide retry/delete/preserve; policy remains operation-specific. A syscall that never returns (hung mount) remains an accepted residual outside the contract: no executors, timeout wrappers, circuit breakers, process isolation, or mount-health machinery are introduced. Bare `ENOENT` is deliberately never treated as absence, so a genuinely vanished file whose folder cannot be corroborated stays `unknown` rather than deleted.

Migration: `LibraryPath.status`/`reason` become derived views for one milestone; `FilesystemError(ValueError)` is placed in `helpers/exceptions.py` so existing `except ValueError` call sites keep working while still carrying the structured fact.

## References

Design: `artifacts/designs/pending/DD-canonical-filesystem-access-contract.md` (v0.5). Process: `artifacts/designs/process/ARCHITECTURE-canonical-filesystem-access-contract.md`, `COMPLEXITY-canonical-filesystem-access-contract.md`, `ADVERSARIAL-canonical-filesystem-access-contract.md` (T1-T9 + counter-design pass), `RESEARCH-filesystem-io-inventory.md`, `RESEARCH-filesystem-error-taxonomy.md`, `estimate-fs-contract-and-162.md`. Related: ADR-035 (essentia as audio DSP backend), ADR-042 (no new dependencies/linters), ADR-046 (thin persistence intent-facade callers), ADR-047 (application semantics vs persistence representation), ADR-048 (SongIdentity locator). Precedent: the #164 scanner fix that classified an unreadable folder as unreconciled (`fix(library-scan): stop treating unreadable folders as authoritatively empty`).
