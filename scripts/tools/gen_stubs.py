#!/usr/bin/env python3
"""Generate collection-specific persistence stub files from collection classes.

Usage
-----
    python scripts/tools/gen_stubs.py          # write all stubs (overwrite)
    python scripts/tools/gen_stubs.py --clear  # delete existing then write

Protected files (never touched):
    _base.pyi, _base.py, __init__.py

Generated files:
    - Per-collection .pyi stubs in nomarr/persistence/stubs/ (one per collection).
      Each stub declares a typed Protocol covering base verbs (get, delete, truncate),
      field accessors (FieldAccessorProtocol per Field[T] annotation), and any
      collection-specific methods (traversals, cascade delete, state transitions,
      vector ops).
    - nomarr/persistence/db.pyi: typed stub for Database, mapping each attribute
      to its per-collection Namespace Protocol so mypy catches wrong API calls.
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
DB_STUB_PATH = ROOT / "nomarr" / "persistence" / "db.pyi"
PROTECTED = {"_base.pyi", "_base.py", "__init__.py"}

_SNAKE_CASE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_CASE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")

_BASE_COLLECTION_TYPES: tuple[type, ...] = (DocumentCollection, EdgeCollection, VectorCollection)


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


def _get_field_names(cls: type[object]) -> list[str]:
    """Return names of ``Field[T]`` / ``UniqueField[T]`` annotated attributes."""
    seen: set[str] = set()
    fields: list[str] = []
    for klass in cls.__mro__:
        if klass in _BASE_COLLECTION_TYPES or klass is object:
            break
        for attr_name, annotation in (getattr(klass, "__annotations__", None) or {}).items():
            if attr_name.startswith("__") or attr_name in seen:
                continue
            ann_str = annotation if isinstance(annotation, str) else str(annotation)
            if "Field[" in ann_str:
                seen.add(attr_name)
                fields.append(attr_name)
    return fields


def _needs_stub(cls: type[object]) -> bool:
    """Return whether ``cls`` needs a generated per-collection stub.

    All collection classes get a stub — edge collections and simple document
    collections included — so that ``db.pyi`` can type every Database attribute.
    """
    return issubclass(cls, _BASE_COLLECTION_TYPES)


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

    is_edge = issubclass(cls, EdgeCollection)
    is_vector = issubclass(cls, VectorCollection)
    is_doc = not is_edge and not is_vector
    needs_traversal = is_doc and bool(getattr(cls, "EDGES", []))
    needs_delete_cascade = is_doc and _has_outbound_cascade(cast("type[DocumentCollection]", cls))
    is_state_graph = issubclass(cls, StateGraphCollection)

    field_names = _get_field_names(cls)

    base_imports: set[str] = {"CollectionDeleteVerbProtocol", "CollectionGetVerbProtocol", "FieldAccessorProtocol"}
    if needs_delete_cascade:
        base_imports.add("DeleteWithCascadeProtocol")
    if needs_traversal:
        base_imports.add("TraversalVerbProtocol")

    out = StringIO()
    out.write("from __future__ import annotations\n\n")
    out.write("from collections.abc import Callable\n")
    out.write("from typing import Any, Protocol, runtime_checkable\n")
    out.write(f"from ._base import {', '.join(sorted(base_imports))}\n")
    out.write("\n")

    out.write("@runtime_checkable\n")
    out.write(f"class {cls.__name__}Namespace(Protocol):\n")

    # Base verbs present on every collection
    out.write("    get: CollectionGetVerbProtocol\n")
    if needs_delete_cascade:
        out.write("    delete: DeleteWithCascadeProtocol\n")
    else:
        out.write("    delete: CollectionDeleteVerbProtocol\n")
    out.write("    truncate: Callable[[], None]\n")
    out.write("    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...\n")
    out.write("    def count(self, *args: Any, **kwargs: Any) -> int: ...\n")
    out.write("    def update(self, *args: Any, **kwargs: Any) -> None: ...\n")
    out.write("    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...\n")
    if not is_vector:
        # VectorCollection stubs define update_many with their own signature below
        out.write("    def update_many(self, docs: list[dict[str, Any]]) -> None: ...\n")
    out.write("    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...\n")
    out.write("    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...\n")

    # Traversal helpers
    if needs_traversal:
        for edge_def in getattr(cls, "EDGES", []):
            out.write(f"    {_snake_case(edge_def.via.__name__)}: TraversalVerbProtocol\n")

    # State graph transition
    if is_state_graph:
        out.write("    def transition(self, file_ids: list[str], from_state: str, to_state: str) -> None: ...\n")

    # Vector-specific methods
    if is_vector:
        _write_vector_methods(out, cast("type[VectorCollection]", cls))

    # Per-field FieldAccessor attributes
    for field_name in field_names:
        out.write(f"    {field_name}: FieldAccessorProtocol\n")

    # Edge collections with no fields and no special methods need an ellipsis body
    if not (field_names or needs_traversal or is_state_graph or is_vector):
        out.write("    ...\n")

    return out.getvalue()


def generate_db_stub(classes: list[type[object]]) -> str:
    """Generate ``nomarr/persistence/db.pyi`` mapping Database attrs to Namespace types.

    ``VectorCollection`` subclasses are skipped — they are registered dynamically
    via ``db.register()`` rather than as fixed attributes.
    """
    static_classes = [cls for cls in classes if not issubclass(cls, VectorCollection)]
    attr_to_cls: dict[str, type[object]] = {_snake_case(cls.__name__): cls for cls in static_classes}

    out = StringIO()
    out.write("from __future__ import annotations\n\n")
    out.write("from typing import Any\n\n")

    for attr_name in sorted(attr_to_cls):
        cls = attr_to_cls[attr_name]
        stub_module = _snake_case(cls.__name__)
        out.write(f"from nomarr.persistence.stubs.{stub_module} import {cls.__name__}Namespace\n")

    out.write("\n\n")
    out.write("class Database:\n")

    for attr_name, cls in attr_to_cls.items():
        out.write(f"    {attr_name}: {cls.__name__}Namespace\n")

    out.write("\n")
    out.write("    # Private attributes\n")
    out.write("    _template_namespaces: dict[str, Any]\n")
    out.write("\n")
    out.write("    USERNAME: str\n")
    out.write("    DB_NAME: str\n")
    out.write("\n")
    out.write("    # Instance attributes set in __init__\n")
    out.write("    db: Any  # SafeDatabase — raw python-arango database handle\n")
    out.write("    hosts: str | None\n")
    out.write("    password: str | None\n")
    out.write("    username: str\n")
    out.write("    db_name: str\n")
    out.write("\n")
    out.write("    def __init__(self, hosts: str | None = ..., password: str | None = ...) -> None: ...\n")
    out.write("    def register(self, collection_name: str, template_name: str) -> Any: ...\n")
    out.write("    def get_version(self) -> str | None: ...\n")
    out.write("    def set_version(self, version: str) -> None: ...\n")
    out.write("    def close(self) -> None: ...\n")

    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate persistence .pyi stubs from collection classes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Writes one collection-specific .pyi per collection into
            nomarr/persistence/stubs/. Also writes nomarr/persistence/db.pyi
            to give Database attributes precise types for mypy.
            Protected files (_base.pyi, _base.py, __init__.py) are never touched.
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
        if DB_STUB_PATH.exists():
            DB_STUB_PATH.unlink()
            print(f"  deleted  {DB_STUB_PATH.relative_to(ROOT)}")

    all_classes = _iter_collection_classes()
    written_paths: set[Path] = set()

    for cls in all_classes:
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

    db_content = generate_db_stub(all_classes)
    DB_STUB_PATH.write_text(db_content, encoding="utf-8", newline="\n")
    print(f"  written  {DB_STUB_PATH.relative_to(ROOT)}")

    print(
        f"Done. Wrote {len(written_paths)} stub file(s), removed {stale} stale file(s) — {STUBS_DIR.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
