#!/usr/bin/env python3
"""Generate .pyi stub files for nomarr/persistence/stubs/ from SCHEMA.

Usage
-----
    python scripts/tools/gen_stubs.py          # write all stubs (overwrite)
    python scripts/tools/gen_stubs.py --clear  # delete existing then write

Protected files (never touched):
    _base.pyi, _base.py, __init__.py

One file per regular collection, one shared vectors_track.pyi for the
TEMPLATE family.  EDGE, STATE_GRAPH, INFRASTRUCTURE, DOCUMENT, and TEMPLATE
collections are all handled.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from io import StringIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from nomarr.persistence.schema import SCHEMA, CollectionType  # noqa: E402

STUBS_DIR = ROOT / "nomarr" / "persistence" / "stubs"
PROTECTED = {"_base.pyi", "_base.py", "__init__.py"}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _pascal(name: str) -> str:
    """snake_case → PascalCase (handles leading underscores like _key → Key)."""
    return "".join(w.title() for w in name.lstrip("_").split("_"))


def _col_pascal(col_name: str) -> str:
    """Collection name → PascalCase prefix used in class names."""
    return "".join(w.title() for w in col_name.split("_"))


def _cap_sig(caps: frozenset[str]) -> str:
    """Capability frozenset → stable PascalCase suffix for Protocol class names.

    'get' is baseline and is omitted unless it's the only capability.
    """
    rest = sorted(caps - {"get"})
    if not rest:
        return "GetOnly"
    return "Get" + "".join(c.title() for c in rest)


# ──────────────────────────────────────────────────────────────────────────────
# Import collection logic
# ──────────────────────────────────────────────────────────────────────────────


def _base_imports(
    col_type: str,
    field_specs: dict[str, dict[str, Any]],
    col_caps: set[str],
) -> list[str]:
    """Determine which names to import from _base.pyi."""
    names: set[str] = set()

    # CollectionGetProtocol on every collection's main namespace
    names.add("CollectionGetProtocol")

    # Field-level imports
    for fspec in field_specs.values():
        caps = frozenset(fspec.get("capabilities", []))
        if "get" in caps:
            if fspec.get("unique"):
                names.add("UniqueGetModifierProtocol")
            else:
                names.add("GetModifierProtocol")
        if "delete" in caps:
            names.add("DeleteModifierProtocol")
        if "aggregate" in caps:
            names.add("AggResult")

    # Collection-level imports
    if "traversal" in col_caps:
        names.add("TraversalProtocol")

    return sorted(names)


# ──────────────────────────────────────────────────────────────────────────────
# Field namespace Protocol generation
# ──────────────────────────────────────────────────────────────────────────────


def _field_protocol_body(caps: frozenset[str], *, unique: bool = False) -> list[str]:
    """Return the indented body lines for a field Protocol class."""
    body: list[str] = []

    if "get" in caps:
        proto = "UniqueGetModifierProtocol" if unique else "GetModifierProtocol"
        body.append(f"    get: {proto}")
    if "delete" in caps:
        body.append("    delete: DeleteModifierProtocol")

    if "count" in caps:
        body.append("    def count(self, value: Any) -> int: ...")
    if "collect" in caps:
        body.extend([
            "    def collect(",
            "        self,",
            "        *,",
            "        filter: dict[str, Any] | None = ...,",
            "        limit: int | None = ...,",
            "        offset: int = ...,",
            "    ) -> list[Any]: ...",
        ])
    if "aggregate" in caps:
        body.extend([
            "    def aggregate(",
            "        self,",
            "        *,",
            "        filter: dict[str, Any] | None = ...,",
            "        limit: int | None = ...,",
            "        offset: int = ...,",
            "    ) -> list[AggResult]: ...",
        ])
    if "update" in caps:
        body.append("    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...")
    if "upsert" in caps:
        body.append(
            "    def upsert(self, docs: list[dict[str, Any]],"
            " match_field: str | list[str]) -> list[str]: ..."
        )

    if not body:
        body.append("    ...")

    return body


# ──────────────────────────────────────────────────────────────────────────────
# Collection-level method generation
# ──────────────────────────────────────────────────────────────────────────────


def _collection_methods(col_caps: set[str], col_type: str) -> list[str]:
    """Return the collection-level method stub lines (not field attributes)."""
    lines: list[str] = []

    if "count" in col_caps:
        lines.append("    def count(self) -> int: ...")
        lines.append("    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...")
    if "insert" in col_caps:
        lines.append("    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...")
    if "update" in col_caps:
        lines.append(
            "    def update_by_filter(self, filter_dict: dict[str, Any],"
            " fields: dict[str, Any]) -> None: ..."
        )
    if "update_many" in col_caps:
        lines.append("    def update_many(self, docs: list[dict[str, Any]]) -> None: ...")
    if "delete" in col_caps:
        lines.append("    def delete(self, ids: list[str]) -> None: ...")
        lines.append("    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...")
    if "cascade" in col_caps:
        lines.append("    def cascade(self, ids: list[str]) -> int: ...")
    if "truncate" in col_caps:
        lines.append("    def truncate(self) -> None: ...")
    if "move_collection" in col_caps:
        lines.append("    def move_collection(self, dest: str) -> int: ...")
    if "transition" in col_caps or col_type == CollectionType.STATE_GRAPH:
        lines.append(
            "    def transition(self, ids: list[str],"
            " from_edge_target: str, to_edge_target: str) -> None: ..."
        )
    if "ann_search" in col_caps:
        lines.extend([
            "    def ann_search(",
            "        self,",
            "        query_vector: list[float],",
            "        limit: int,",
            "        nprobe: int,",
            "        *,",
            "        filter: dict[str, Any] | None = ...,",
            "    ) -> list[dict[str, Any]]: ...",
        ])
    if "traversal" in col_caps:
        lines.append("    traversal: TraversalProtocol")

    return lines


# ──────────────────────────────────────────────────────────────────────────────
# Per-collection stub generation
# ──────────────────────────────────────────────────────────────────────────────


def generate_stub(col_name: str, spec: dict[str, Any]) -> str:
    """Generate the full .pyi content for one collection."""
    col_type = spec.get("type", CollectionType.DOCUMENT)
    col_caps: set[str] = set(spec.get("capabilities", []))
    fields: dict[str, dict[str, Any]] = spec.get("fields", {})
    prefix = _col_pascal(col_name)

    # Group fields by (capability frozenset, is_unique) — unique fields get
    # a narrower get protocol, so they need their own Protocol class.
    cap_unique_to_fields: dict[tuple[frozenset[str], bool], list[str]] = {}
    for fname, fspec in fields.items():
        fcaps = frozenset(fspec.get("capabilities", []))
        is_unique = bool(fspec.get("unique", False))
        cap_unique_to_fields.setdefault((fcaps, is_unique), []).append(fname)

    imports = _base_imports(col_type, fields, col_caps)

    out = StringIO()
    out.write("from __future__ import annotations\n\n")
    out.write("from typing import Any, Protocol, runtime_checkable\n\n")
    if imports:
        out.write("from nomarr.persistence.stubs._base import (\n")
        for imp in imports:
            out.write(f"    {imp},\n")
        out.write(")\n")
    out.write("\n\n")

    # One Protocol per unique (caps, is_unique) pair
    cap_unique_to_class: dict[tuple[frozenset[str], bool], str] = {}
    for (fcaps, is_unique), fnames in cap_unique_to_fields.items():
        sig = _cap_sig(fcaps)
        unique_suffix = "Unique" if is_unique else ""
        class_name = f"{prefix}{unique_suffix}{sig}Namespace"
        cap_unique_to_class[(fcaps, is_unique)] = class_name

        out.write("@runtime_checkable\n")
        out.write(f"class {class_name}(Protocol):\n")
        body = _field_protocol_body(fcaps, unique=is_unique)
        out.write("\n".join(body) + "\n")
        out.write("\n\n")

    # Main collection Protocol
    out.write("@runtime_checkable\n")
    out.write(f"class {prefix}Namespace(Protocol):\n")
    out.write("    get: CollectionGetProtocol\n")

    for fname, fspec in fields.items():
        fcaps = frozenset(fspec.get("capabilities", []))
        is_unique = bool(fspec.get("unique", False))
        out.write(f"    {fname}: {cap_unique_to_class[(fcaps, is_unique)]}\n")

    methods = _collection_methods(col_caps, col_type)
    if fields and methods:
        out.write("\n")
    out.write("\n".join(methods) + "\n")

    # Edge case: no fields and no methods → need at least `...`
    if not fields and not methods:
        out.write("    ...\n")

    out.write("\n")
    return out.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# vectors_track special case (two TEMPLATE specs → one shared file)
# ──────────────────────────────────────────────────────────────────────────────


def generate_vectors_track_stub(
    hot_spec: dict[str, Any],
    cold_spec: dict[str, Any],
) -> str:
    """Generate the combined vectors_track.pyi for both hot and cold tiers."""
    out = StringIO()
    out.write("from __future__ import annotations\n\n")
    out.write("from typing import Any, Protocol, runtime_checkable\n\n")
    out.write("from nomarr.persistence.stubs._base import (\n")
    out.write("    CollectionGetProtocol,\n")
    out.write("    DeleteModifierProtocol,\n")
    out.write("    GetModifierProtocol,\n")
    out.write("    UniqueGetModifierProtocol,\n")
    out.write(")\n\n\n")

    # Shared field Protocol classes (both tiers have the same fields)
    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackGetOnlyNamespace(Protocol):\n")
    out.write("    get: GetModifierProtocol\n")
    out.write("\n\n")

    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackUniqueGetOnlyNamespace(Protocol):\n")
    out.write("    get: UniqueGetModifierProtocol\n")
    out.write("\n\n")

    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackIdNamespace(Protocol):\n")
    out.write("    get: UniqueGetModifierProtocol\n\n")
    out.write("    def collect(\n")
    out.write("        self,\n")
    out.write("        *,\n")
    out.write("        filter: dict[str, Any] | None = ...,\n")
    out.write("        limit: int | None = ...,\n")
    out.write("        offset: int = ...,\n")
    out.write("    ) -> list[Any]: ...\n")
    out.write("\n\n")

    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackFileIdNamespace(Protocol):\n")
    out.write("    get: GetModifierProtocol\n")
    out.write("    delete: DeleteModifierProtocol\n")
    out.write("\n\n")

    # Hot namespace
    hot_caps: set[str] = set(hot_spec.get("capabilities", []))
    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackHotNamespace(Protocol):\n")
    out.write("    get: CollectionGetProtocol\n")
    out.write("    _key: VectorsTrackUniqueGetOnlyNamespace\n")
    out.write("    _id: VectorsTrackUniqueGetOnlyNamespace\n")
    out.write("    file_id: VectorsTrackFileIdNamespace\n")
    out.write("    vector: VectorsTrackGetOnlyNamespace\n")
    out.write("\n")
    out.write("\n".join(_collection_methods(hot_caps, CollectionType.TEMPLATE)) + "\n")
    out.write("    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...\n")
    out.write("    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]: ...\n")
    out.write("    def upsert_vector(\n")
    out.write("        self,\n")
    out.write("        file_id: str,\n")
    out.write("        model_suite_hash: str,\n")
    out.write("        embed_dim: int,\n")
    out.write("        vector: list[float],\n")
    out.write("        num_segments: int,\n")
    out.write("    ) -> None: ...\n")
    out.write("\n\n")

    # Cold namespace
    cold_caps: set[str] = set(cold_spec.get("capabilities", []))
    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackColdNamespace(Protocol):\n")
    out.write("    get: CollectionGetProtocol\n")
    out.write("    _key: VectorsTrackUniqueGetOnlyNamespace\n")
    out.write("    _id: VectorsTrackUniqueGetOnlyNamespace\n")
    out.write("    file_id: VectorsTrackFileIdNamespace\n")
    out.write("    vector: VectorsTrackGetOnlyNamespace\n")
    out.write("\n")
    out.write("\n".join(_collection_methods(cold_caps, CollectionType.TEMPLATE)) + "\n")
    out.write("    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...\n")
    out.write("    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]: ...\n")
    out.write("\n\n")

    # Maintenance Protocol
    out.write("@runtime_checkable\n")
    out.write("class VectorsTrackMaintenanceProtocol(Protocol):\n")
    out.write("    def drop_index(self) -> None: ...\n")
    out.write("    def build_index(self, *, embed_dim: int, nlists: int) -> None: ...\n")
    out.write("    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None: ...\n")
    out.write("    def get_stats(self) -> dict[str, int | bool]: ...\n")
    out.write("\n")

    return out.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate persistence .pyi stubs from SCHEMA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Writes one .pyi per collection into nomarr/persistence/stubs/.
            Protected files (_base.pyi, _base.py, __init__.py) are never touched.
            TEMPLATE collections (vectors_track_hot / cold) share vectors_track.pyi.
        """),
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing (non-protected) .pyi files before writing.",
    )
    args = parser.parse_args()

    if args.clear:
        for p in STUBS_DIR.glob("*.pyi"):
            if p.name not in PROTECTED:
                p.unlink()
                print(f"  deleted  {p.name}")

    written = 0
    template_specs: dict[str, dict[str, Any]] = {}

    for col_name, spec in SCHEMA.items():
        col_type = spec.get("type")

        if col_type == CollectionType.TEMPLATE:
            template_specs[col_name] = spec
            continue

        content = generate_stub(col_name, spec)
        out_path = STUBS_DIR / f"{col_name}.pyi"
        out_path.write_text(content, encoding="utf-8")
        print(f"  written  {out_path.name}")
        written += 1

    # vectors_track is the only TEMPLATE family; both tiers share one file
    if "vectors_track_hot" in template_specs and "vectors_track_cold" in template_specs:
        content = generate_vectors_track_stub(
            template_specs["vectors_track_hot"],
            template_specs["vectors_track_cold"],
        )
        out_path = STUBS_DIR / "vectors_track.pyi"
        out_path.write_text(content, encoding="utf-8")
        print(f"  written  {out_path.name}")
        written += 1
    else:
        for tname, tspec in template_specs.items():
            content = generate_stub(tname, tspec)
            out_path = STUBS_DIR / f"{tname}.pyi"
            out_path.write_text(content, encoding="utf-8")
            print(f"  written  {out_path.name}")
            written += 1

    print(f"\n{written} stub file(s) written to {STUBS_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
