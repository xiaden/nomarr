"""ModelRepo — CRUD and domain queries for the ``ml_models`` table.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.model_repo_dto import ModelRecord
from nomarr.persistence.exceptions import PersistenceError
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.sql.primitives import delete_by_key, select_by_key

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

_T = cast("Table", MlModel.__table__)


def _row_to_dto(row: Row[Any]) -> ModelRecord:
    """Convert a SQLAlchemy ``Row`` to a ``ModelRecord`` TypedDict."""
    m = row._mapping
    return ModelRecord(
        id=m["id"],
        model_type=m["model_type"],
        backbone_id=m["backbone_id"],
        enabled=m["enabled"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        # Extended fields from the ml_models table
        path=m.get("path") or "",
        backbone=m.get("backbone") or "",
        head_type=m.get("head_type") or "",
        model_stem=m.get("model_stem") or "",
        output_count=m.get("output_count") or 0,
        fully_configured=m.get("fully_configured") or 0,
        is_known=m.get("is_known") or 0,
        source=m.get("source") or "discovered",
        head_release_date=m.get("head_release_date") or "",
        embedder_release_date=m.get("embedder_release_date") or "",
        registered_at=m.get("registered_at"),
    )


class ModelRepo:
    """Repository for the ``ml_models`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── reads ───────────────────────────────────────────────────

    async def get_model(self, model_id: str) -> ModelRecord | None:
        """Fetch a single model by its string primary key."""
        row = await select_by_key(_T, model_id, session=self._session)
        return _row_to_dto(row) if row else None

    async def get_model_by_type(self, model_type: str) -> ModelRecord | None:
        """Fetch a model by its ``model_type`` column.

        ``MlModel`` has no ``path`` column; this searches by ``model_type``
        which identifies the model architecture (e.g. ``'onnx_genre_v2'``).
        """
        stmt = select(_T).where(_T.c.model_type == model_type)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def list_models(self) -> list[ModelRecord]:
        """Return all model rows."""
        stmt = select(_T)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def count_models(self) -> int:
        """Return the total number of model rows."""
        stmt = select(func.count()).select_from(_T)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_models_by_ids(self, model_ids: list[str]) -> list[ModelRecord]:
        """Return models whose ``id`` is in *model_ids*."""
        if not model_ids:
            return []
        stmt = select(_T).where(_T.c.id.in_(model_ids))
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def get_enabled_models(self) -> list[ModelRecord]:
        """Return models where ``enabled = 1``."""
        stmt = select(_T).where(_T.c.enabled == 1)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def get_by_backbone(self, backbone_id: str) -> list[ModelRecord]:
        """Return models for a given backbone."""
        stmt = select(_T).where(_T.c.backbone_id == backbone_id)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    # ── writes ──────────────────────────────────────────────────

    async def upsert_model(self, data: dict[str, Any]) -> ModelRecord:
        """Insert or update a model row keyed on ``id`` PK.

        Uses PostgreSQL ``ON CONFLICT (id) DO UPDATE``.  The ``updated_at``
        timestamp is refreshed automatically.

        The *data* dict may include any of the extended fields added in
        Phase 2 (path, backbone, head_type, model_stem, output_count,
        fully_configured, is_known, source, head_release_date,
        embedder_release_date, registered_at).  Unknown keys are passed
        through to the database verbatim.
        """
        now = int(time.time())
        data.setdefault("created_at", now)
        data["updated_at"] = now

        set_clause = {k: v for k, v in data.items() if k != "id"}
        stmt = (
            pg_insert(_T)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_=set_clause,
            )
            .returning(_T)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        row = result.fetchone()
        assert row is not None
        return _row_to_dto(row)

    async def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a model row.

        Raises ``PersistenceError`` if no model with *model_id* exists.
        """
        fields["updated_at"] = int(time.time())
        stmt = select(_T).where(_T.c.id == model_id)
        result = await self._session.execute(stmt)
        existing = result.fetchone()
        if existing is None:
            msg = f"Model {model_id!r} not found for update"
            raise PersistenceError(msg)

        update_stmt = update(_T).where(_T.c.id == model_id).values(**fields)
        await self._session.execute(update_stmt)
        await self._session.commit()

    async def delete_model(self, model_id: str) -> None:
        """Delete a model row by primary key.

        CASCADE handles outputs, calibration, and streams.
        """
        await delete_by_key(_T, model_id, session=self._session)
        await self._session.commit()
