from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import GetModifierProtocol

@runtime_checkable
class FileHasStateFieldNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...
    def collect(self, *, limit: int | None = ..., offset: int = ...) -> list[Any]: ...

@runtime_checkable
class FileHasStateGetOnlyNamespace(Protocol):
    def count(self, value: str) -> int: ...
    get: GetModifierProtocol

    def collect(self, *, limit: int | None = ..., offset: int = ...) -> list[Any]: ...

@runtime_checkable
class FileHasStateNamespace(Protocol):
    _from: FileHasStateFieldNamespace
    _to: FileHasStateGetOnlyNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def get(self, id: str) -> dict[str, Any] | None: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
