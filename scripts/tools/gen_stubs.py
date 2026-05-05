#!/usr/bin/env python3
"""Generate collection-specific persistence stub files from collection classes.

Usage
-----
    python scripts/tools/gen_stubs.py          # write all stubs (overwrite)
    python scripts/tools/gen_stubs.py --clear  # delete existing then write

Protected files (never touched):
    _base.pyi, _base.py, __init__.py

Only collection-specific verbs are emitted into per-collection stubs:
- traversal helpers declared via ``EDGES`` on ``DocumentCollection`` subclasses
- ``delete.cascade`` for collections with outbound ``CASCADE`` edges
- ``transition`` for ``StateGraphCollection`` subclasses
- vector helpers for ``VectorCollection`` subclasses

Generic flat verbs remain outside generated per-collection stubs.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from io import StringIO
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import nomarr.persistence.collections as collections_module  # noqa: E402
from nomarr.persistence.base import (  # noqa: E402
    CASCADE,
    DocumentCollection,
    EdgeCollection,
    StateGraphCollection,
    VectorCollection,
)

STUBS_DIR = ROOT / "nomarr" / "persistence" / "stubs"
PROTECTED = {"_base.pyi", "_base.py", "__init__.py"}

_SNAKE_CASE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_CASE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _snake_case(name: str) -> str:
    """Convert ``CamelCase`` class names to ``snake_case``."""
    return _SNAKE_CASE_RE_2.sub(r"\1_\2", _SNAKE_CASE_RE_1.sub(r"\1_\2", name)).lower()


def _iter_collection_classes() -> list[type[object]]:
    """Return exported collection classes in source-defined order."""
    exported = getattr(collections_module, "__all__", [])
    collection_classes: list[type[object]] = []

    for name in exported:
        value = getattr(collections_module, name, None)
        if not isinstance(value, type):
            continue
        if issubclass(value, (DocumentCollection, EdgeCollection, VectorCollection)):
            collection_classes.append(cast("type[object]", value))

    return collection_classes


def _has_outbound_cascade(cls: type[DocumentCollection]) -> bool:
    """Return whether the collection gets ``delete.cascade`` attached."""
    return any(edge.on_delete == CASCADE and edge.direction == "OUTBOUND" for edge in getattr(cls, "EDGES", []))


def _needs_stub(cls: type[object]) -> bool:
    """Return whether ``cls`` needs a generated per-collection stub."""
    if issubclass(cls, EdgeCollection):
        return False

    if issubclass(cls, VectorCollection):
        return True

    if issubclass(cls, DocumentCollection):
        if getattr(cls, "EDGES", []):
            return True
        if issubclass(cls, StateGraphCollection):
            return True
        return _has_outbound_cascade(cast("type[DocumentCollection]", cls))

    return False


def _write_vector_methods(out: StringIO, cls: type[VectorCollection]) -> None:
    out.write("    def ann_search(\n")
    out.write("        self,\n")
    out.write("        query_vector: list[float],\n")
    out.write("        limit: int,\n")
    out.write("        nprobe: int,\n")
    out.write("        *,\n")
    out.write("        filter: dict[str, Any] | None = ...,\n")
    out.write("    ) -> list[dict[str, Any]]: ...\n")
    out.write("    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...\n")
    out.write("    def update_many(self, docs: list[dict[str, Any]]) -> None: ...\n")

    if cls.VECTOR_TIER == "hot":
        out.write("    def upsert_vector(\n")
        out.write("        self,\n")
        out.write("        file_id: str,\n")
        out.write("        model_suite_hash: str,\n")
        out.write("        embed_dim: int,\n")
        out.write("        vector: list[float],\n")
        out.write("        num_segments: int,\n")
        out.write("    ) -> None: ...\n")
        out.write("    def move_collection(self, dest: str) -> int: ...\n")


def generate_stub(cls: type[object]) -> str | None:
    """Generate the full ``.pyi`` content for one collection class."""
    if not _needs_stub(cls):
        return None

    needs_traversal = issubclass(cls, DocumentCollection) and bool(getattr(cls, "EDGES", []))
    needs_delete_cascade = issubclass(cls, DocumentCollection) and _has_outbound_cascade(
        cast("type[DocumentCollection]", cls)
    )
    is_state_graph = issubclass(cls, StateGraphCollection)
    is_vector = issubclass(cls, VectorCollection)

    base_imports: list[str] = []
    if needs_delete_cascade:
        base_imports.append("DeleteWithCascadeProtocol")
    if needs_traversal:
        base_imports.append("TraversalVerbProtocol")

    out = StringIO()
    out.write("from __future__ import annotations\n\n")
    out.write("from typing import Any, Protocol, runtime_checkable\n")
    if base_imports:
        out.write(f"from ._base import {', '.join(sorted(base_imports))}\n")
    out.write("\n")

    out.write("@runtime_checkable\n")
    out.write(f"class {cls.__name__}Namespace(Protocol):\n")

    body_written = False

    if needs_delete_cascade:
        out.write("    delete: DeleteWithCascadeProtocol\n")
        body_written = True

    if needs_traversal:
        for edge_def in getattr(cls, "EDGES", []):
            out.write(f"    {_snake_case(edge_def.via.__name__)}: TraversalVerbProtocol\n")
        body_written = True

    if is_state_graph:
        out.write("    def transition(self, file_ids: list[str], from_state: str, to_state: str) -> None: ...\n")
        body_written = True

    if is_vector:
        _write_vector_methods(out, cast("type[VectorCollection]", cls))
        body_written = True

    if not body_written:
        out.write("    ...\n")

    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate persistence .pyi stubs from collection classes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Writes one collection-specific .pyi per generated collection into
            nomarr/persistence/stubs/. Protected files (_base.pyi, _base.py,
            __init__.py) are never touched.
            """
        ),
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing (non-protected) .pyi files before writing.",
    )
    args = parser.parse_args()

    STUBS_DIR.mkdir(parents=True, exist_ok=True)

    if args.clear:
        for path in STUBS_DIR.glob("*.pyi"):
            if path.name not in PROTECTED:
                path.unlink()
                print(f"  deleted  {path.name}")

    written_paths: set[Path] = set()
    for cls in _iter_collection_classes():
        content = generate_stub(cls)
        if content is None:
            continue

        stub_path = STUBS_DIR / f"{_snake_case(cls.__name__)}.pyi"
        stub_path.write_text(content, encoding="utf-8", newline="\n")
        written_paths.add(stub_path)
        print(f"  written  {stub_path.name}")

    stale = 0
    for path in STUBS_DIR.glob("*.pyi"):
        if path.name not in PROTECTED and path not in written_paths:
            path.unlink()
            print(f"  removed  {path.name}  (stale — no matching collection class)")
            stale += 1

    print(f"Done. Wrote {len(written_paths)} stub file(s), removed {stale} stale file(s) — {STUBS_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
