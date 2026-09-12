"""Q1 resolver/scalar closure enforcement (CONTRACTS §12/§12.1).

Negative architecture guard: every retained integer identity crossing is a
machine-readable allowlist entry in ``q1_resolver_scalar_allowlist.json``. There
is no unconditional hydration integer exception — hydration is locator-addressed
and payload-only. The three locator ``FieldWriteResult`` intents are the only
public scalar write surface, and legacy integer scalar writers must be absent
(deleted, not forwarded/wrapped).
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import get_type_hints

import pytest

from nomarr.components.library import library_song_mutation_comp as mutation_comp
from nomarr.helpers.dataclasses.song_command_dataclass import (
    ChromaprintValue,
    FieldWriteResult,
    SongIdentity,
)
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.persistence.api.library_songs import LibrarySongsDb

pytestmark = pytest.mark.unit

_ARCH_DIR = Path(__file__).resolve().parent
_ALLOWLIST_PATH = _ARCH_DIR / "q1_resolver_scalar_allowlist.json"
_REPO_ROOT = _ARCH_DIR.parents[2]

# Hardcoded contract: the six machine-readable fields every allowlist entry must
# carry (CONTRACTS §12). Deliberately NOT read from the JSON so that a missing
# key in the data file cannot weaken its own schema check.
_REQUIRED_ALLOWLIST_FIELDS = (
    "owner",
    "boundary",
    "reason",
    "positive_test",
    "non_propagation",
    "removal_condition",
)

_LEGACY_SCALAR_WRITERS = (
    "update_library_song_modified_time",
    "set_library_song_chromaprint",
    "update_library_song_last_tagged_at",
)
_RESOLVER_NAMES = (
    "resolve_song_identity",
    "resolve_song_identities",
    "resolve_library_identity",
    "resolve_library_identities",
)

# Canonical public scalar writers; every other writer-shaped method touching
# modified-time/last-tagged/chromaprint is forbidden.
_CANONICAL_SCALAR_WRITERS = frozenset({"set_modified_time", "set_last_tagged", "set_chromaprint"})

# Repository primitives that actually mutate a scalar column. Only the three
# canonical facades may reference them.
_SCALAR_WRITE_PRIMITIVES = (
    "set_modified_time_by_locator",
    "set_last_tagged_by_locator",
    "set_chromaprint_by_locator",
    "_set_monotonic_scalar",
)

# Resolver-bridge modules that must remain fully allowlisted. ``db.py`` exposes no
# resolver of its own but is scanned so a future public bridge cannot hide there.
_RESOLVER_SCAN_MODULES = (
    "nomarr/persistence/api/library_songs.py",
    "nomarr/persistence/api/library.py",
    "nomarr/persistence/db.py",
)

# Declared module for each ``deleted_by_q1`` symbol prefix.
_DELETED_SYMBOL_MODULES = {
    "LibrarySongsDb": "nomarr/persistence/api/library_songs.py",
    "LibraryDb": "nomarr/persistence/api/library.py",
    "library_song_mutation_comp": "nomarr/components/library/library_song_mutation_comp.py",
}

_WRITE_VERB_PREFIXES = ("set_", "update_", "write_", "replace_", "persist_", "save_", "mark_", "record_")
_SCALAR_FIELD_TOKENS = ("modified_time", "last_tagged", "tagged_at", "chromaprint")


def _load_allowlist() -> dict:
    return json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))


def _source(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


def _allowlist_entries() -> list[dict]:
    data = _load_allowlist()
    return [*data["allowlisted_resolvers"], *data["allowlisted_integer_adapters"]]


def _public_method_bodies(relative: str) -> dict[str, str]:
    """Return ``{method_name: body_source}`` for public methods in *relative*.

    Only top-level, non-underscore methods are considered; ``resolve_*`` methods
    are the only methods expected to carry an integer handle.
    """
    source = _source(relative)
    lines = source.splitlines()
    starts: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^    def ([a-zA-Z][a-zA-Z0-9_]*)\(", line)
        if match:
            starts.append((match.group(1), index))
    bodies: dict[str, str] = {}
    for position, (name, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(lines)
        bodies[name] = "\n".join(lines[start:end])
    return bodies


def _extract_test_targets(entry: dict) -> list[tuple[str, str | None]]:
    """Parse ``positive_test`` into ``(file_path, optional::test_name)`` pairs.

    Allowlist values are free-text but every referenced target must begin with a
    repo-relative ``tests/...py`` path, optionally followed by ``::test_name``.
    """
    raw = entry["positive_test"]
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(r"(tests/[A-Za-z0-9_./-]+\.py)(?:::([A-Za-z0-9_]+))?", raw)
    ]


def _resolve_deleted_symbol(symbol: str) -> str:
    """Map a ``deleted_by_q1`` symbol to its declared module path."""
    for prefix, module in _DELETED_SYMBOL_MODULES.items():
        if symbol.startswith(f"{prefix}."):
            return module
    raise AssertionError(f"deleted_by_q1 symbol {symbol!r} has no declared module in the test map")


def test_required_allowlist_field_tuple_is_hardcoded() -> None:
    """The test owns the expected six-field schema; the JSON may not redefine it."""
    assert _REQUIRED_ALLOWLIST_FIELDS == (
        "owner",
        "boundary",
        "reason",
        "positive_test",
        "non_propagation",
        "removal_condition",
    )
    data = _load_allowlist()
    assert tuple(data["required_allowlist_fields"]) == _REQUIRED_ALLOWLIST_FIELDS


def test_every_allowlist_entry_carries_all_six_required_fields() -> None:
    """All six fields are validated on both allowlisted collections."""
    data = _load_allowlist()
    collections = {
        "allowlisted_resolvers": data["allowlisted_resolvers"],
        "allowlisted_integer_adapters": data["allowlisted_integer_adapters"],
    }
    for collection, entries in collections.items():
        assert entries, f"{collection} must not be empty"
        for entry in entries:
            for field in _REQUIRED_ALLOWLIST_FIELDS:
                assert entry.get(field), f"{collection}: {entry.get('symbol')} missing machine-readable field: {field}"


def test_every_positive_test_target_exists() -> None:
    """Each allowlisted entry's positive test file (and named test) actually exists."""
    for entry in _allowlist_entries():
        targets = _extract_test_targets(entry)
        assert targets, f"{entry['symbol']} has no resolvable positive_test target: {entry['positive_test']!r}"
        for relative, test_name in targets:
            path = _REPO_ROOT / relative
            assert path.is_file(), f"{entry['symbol']} positive_test file missing: {relative}"
            if test_name is not None:
                source = path.read_text(encoding="utf-8")
                assert re.search(rf"def {test_name}\b", source), (
                    f"{entry['symbol']} positive_test names missing test: {relative}::{test_name}"
                )


def test_every_public_resolver_is_allowlisted() -> None:
    """No public ``resolve_*`` bridge may exist in a Q1 resolver module unallowlisted."""
    allowed = {entry["symbol"].split(".")[-1] for entry in _load_allowlist()["allowlisted_resolvers"]}
    for relative in _RESOLVER_SCAN_MODULES:
        defined = set(re.findall(r"^    def (resolve_[a-z_]+)\(", _source(relative), flags=re.MULTILINE))
        assert defined <= allowed, f"{relative}: unallowlisted resolver(s): {sorted(defined - allowed)}"


def test_library_facade_forwarders_are_allowlisted() -> None:
    allowed = {entry["symbol"].split(".")[-1] for entry in _load_allowlist()["allowlisted_resolvers"]}
    source = _source("nomarr/persistence/api/library.py")
    for name in _RESOLVER_NAMES:
        assert re.search(rf"^    def {name}\(", source, flags=re.MULTILINE), f"forwarder {name} missing"
        assert name in allowed


def test_deleted_by_q1_symbols_are_absent_from_their_declared_modules() -> None:
    """Every ``deleted_by_q1`` symbol is genuinely gone from its declared module."""
    for symbol in _load_allowlist()["deleted_by_q1"]:
        module = _resolve_deleted_symbol(symbol)
        method = symbol.split(".")[-1]
        source = _source(module)
        assert not re.search(rf"def {method}\b", source), f"deleted symbol {symbol} still defined in {module}"


def test_legacy_integer_scalar_writers_are_absent_not_forwarded() -> None:
    for relative in ("nomarr/persistence/api/library_songs.py", "nomarr/persistence/api/library.py"):
        source = _source(relative)
        for legacy in _LEGACY_SCALAR_WRITERS:
            assert not re.search(rf"def {legacy}\b", source), f"{legacy} still defined in {relative}"

    mutation = _source("nomarr/components/library/library_song_mutation_comp.py")
    assert not re.search(r"def get_song_library_key\b", mutation)
    for legacy in _LEGACY_SCALAR_WRITERS:
        assert f"{legacy}(" not in mutation, f"adapter still forwards deleted writer {legacy}"


def test_three_scalar_intents_are_the_public_scalar_write_surface() -> None:
    for name in ("set_modified_time", "set_last_tagged", "set_chromaprint"):
        hints = get_type_hints(getattr(LibrarySongsDb, name))
        assert hints["return"] is FieldWriteResult
        assert hints["song"] is SongIdentity
    assert get_type_hints(LibrarySongsDb.set_chromaprint)["value"] is ChromaprintValue


def test_only_canonical_methods_reference_scalar_write_primitives() -> None:
    """No public facade method besides the three canonical setters writes a scalar column."""
    bodies = _public_method_bodies("nomarr/persistence/api/library_songs.py")
    writers = {
        name for name, body in bodies.items() if any(primitive in body for primitive in _SCALAR_WRITE_PRIMITIVES)
    }
    assert writers == _CANONICAL_SCALAR_WRITERS, (
        f"scalar-primitive writers must be exactly {sorted(_CANONICAL_SCALAR_WRITERS)}, got {sorted(writers)}"
    )

    forwarder_bodies = _public_method_bodies("nomarr/persistence/api/library.py")
    forwarders = {
        name
        for name, body in forwarder_bodies.items()
        if any(f"self._songs.{canonical}(" in body for canonical in _CANONICAL_SCALAR_WRITERS)
    }
    assert forwarders == _CANONICAL_SCALAR_WRITERS, (
        f"scalar forwarders must be exactly {sorted(_CANONICAL_SCALAR_WRITERS)}, got {sorted(forwarders)}"
    )


def test_no_ad_hoc_public_scalar_writer_names() -> None:
    """Writer-verb methods touching scalar fields must be one of the three canonical setters."""
    offenders: list[str] = []
    for relative in ("nomarr/persistence/api/library_songs.py", "nomarr/persistence/api/library.py"):
        for name in _public_method_bodies(relative):
            if name in _CANONICAL_SCALAR_WRITERS:
                continue
            if name.startswith(_WRITE_VERB_PREFIXES) and any(token in name for token in _SCALAR_FIELD_TOKENS):
                offenders.append(f"{relative}:{name}")
    assert not offenders, f"ad-hoc/legacy public scalar writer(s): {offenders}"


def test_allowlisted_symbols_actually_exist() -> None:
    data = _load_allowlist()
    for entry in data["allowlisted_resolvers"]:
        assert hasattr(LibrarySongsDb, entry["symbol"].split(".")[-1]), f"stale allowlist entry {entry['symbol']}"
    for entry in data["allowlisted_integer_adapters"]:
        assert hasattr(mutation_comp, entry["symbol"].split(".")[-1]), f"stale allowlist entry {entry['symbol']}"


def test_hydrate_input_is_locator_addressed() -> None:
    assert "song_id" not in HydrateSongInput.__init__.__annotations__
    assert "song_id" not in {field.name for field in dataclasses.fields(SongIdentity)}
