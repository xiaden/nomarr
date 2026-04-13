from __future__ import annotations

from typing import Any, Protocol, TypedDict

from nomarr.persistence.schema import FilterDict

class AggResult(TypedDict):
    value: str
    count: int

class GetOneProtocol(Protocol):
    def __call__(self, value: Any) -> dict[str, Any] | None: ...

class GetOneByIdProtocol(Protocol):
    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...
    def id(self, doc_id: str) -> dict[str, Any] | None: ...

class GetManyProtocol(Protocol):
    def __call__(
        self,
        value: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class GetManyByFilterProtocol(Protocol):
    def __call__(self, ids: list[str]) -> list[dict[str, Any]]: ...
    def id(self, ids: list[str]) -> list[dict[str, Any]]: ...
    def by_filter(
        self,
        filter_dict: dict[str, Any],
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class CollectionGetProtocol(Protocol):
    one: GetOneByIdProtocol
    many: GetManyByFilterProtocol

    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...

class GetModifierProtocol(Protocol):
    def __call__(self, value: Any) -> dict[str, Any] | None | list[dict[str, Any]]: ...
    def one(self, value: Any) -> dict[str, Any] | None: ...
    def many(
        self,
        value: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def in_(
        self,
        values: list[Any] | FilterDict,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def like(
        self,
        pattern: str,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
