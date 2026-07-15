"""FileStateRepository — manages file ↔ state assignments.

Replaces ``file_states_aql.py`` and ``file_state_assignments_aql.py``.
Uses the ``file_state_assignments`` junction table (M:N between files
and states) and the ``file_states`` lookup table.

Method signatures follow the Plan E contracts (downstream intent-facade
expectations), NOT the original plan-step signatures.
"""

from __future__ import annotations

import time

from sqlalchemy import Table, delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.helpers.dto.repo_dto import FileStateAssignmentRow, FileStateRow
from nomarr.persistence.models.file_state import FileState
from nomarr.persistence.models.file_state_assignment import FileStateAssignment
from nomarr.persistence.sql.primitives import insert_one

_A: Table = FileStateAssignment.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = FileState.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _assignment_row_to_dto(row: Row) -> FileStateAssignmentRow:
    """Convert a SQLAlchemy ``Row`` to a ``FileStateAssignmentRow``."""
    m = row._mapping
    return FileStateAssignmentRow(
        id=m["id"],
        file_id=m["file_id"],
        state_id=m["state_id"],
        created_at=m["created_at"],
    )


def _state_row_to_dto(row: Row) -> FileStateRow:
    """Convert a SQLAlchemy ``Row`` to a ``FileStateRow``."""
    m = row._mapping
    return FileStateRow(
        id=m["id"],
        name=m["name"],
        description=m["description"],
    )


class FileStateRepository:
    """Repository for ``file_states`` and ``file_state_assignments``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_file_state(self, file_id: int) -> str | None:
        """Return the state *name* for a file, or ``None``."""
        stmt = select(_S.c.name).join(_A, _S.c.id == _A.c.state_id).where(_A.c.file_id == file_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    async def get_file_states_for_files(self, file_ids: list[int]) -> dict[int, set[str]]:
        """Return ``{file_id: {state_names}}`` for a batch of file ids."""
        if not file_ids:
            return {}
        stmt = select(_A.c.file_id, _S.c.name).join(_S, _S.c.id == _A.c.state_id).where(_A.c.file_id.in_(file_ids))
        result = await self._session.execute(stmt)
        mapping: dict[int, set[str]] = {}
        for r in result.all():
            mapping.setdefault(r[0], set()).add(r[1])
        return mapping

    async def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[int]:
        """Return file ids assigned to *state*."""
        stmt = select(_A.c.file_id).join(_S, _S.c.id == _A.c.state_id).where(_S.c.name == state)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def count_files_in_state(self, state: str) -> int:
        """Count files assigned to *state*."""
        stmt = select(func.count()).select_from(_A).join(_S, _S.c.id == _A.c.state_id).where(_S.c.name == state)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def assign_state(self, file_id: int, state: str) -> None:
        """Assign a state (by name) to a file.

        Resolves the state name to its ``state_id`` via the
        ``file_states`` lookup table, then inserts an assignment.
        """
        # Resolve state name → id
        stmt = select(_S.c.id).where(_S.c.name == state)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Unknown file state: {state!r}")
        state_id = row[0]

        payload = {
            "file_id": file_id,
            "state_id": state_id,
            "created_at": int(time.time() * 1000),
        }
        await insert_one(_A, payload, session=self._session)
        await self._session.commit()

    async def remove_states_for_files(self, file_ids: list[int]) -> None:
        """Delete all state assignments for the given file ids."""
        if not file_ids:
            return
        stmt = delete(_A).where(_A.c.file_id.in_(file_ids))
        await self._session.execute(stmt)
        await self._session.commit()

    async def bootstrap_states(self, file_ids: list[int]) -> None:
        """Ensure canonical state records exist in ``file_states``.

        Inserts the default state names if the lookup table is empty.
        The *file_ids* parameter is accepted for interface compatibility
        but the bootstrap operates on the lookup table only.
        """
        # Check if states already exist
        count_stmt = select(func.count()).select_from(_S)
        result = await self._session.execute(count_stmt)
        if (result.scalar() or 0) > 0:
            return

        canonical_states = [
            {"name": "pending", "description": "Awaiting processing"},
            {"name": "tagged", "description": "Tags have been applied"},
            {"name": "curated", "description": "Tags have been curated"},
            {"name": "written", "description": "Tags written to file metadata"},
            {"name": "error", "description": "Processing error occurred"},
        ]
        for state_data in canonical_states:
            await insert_one(_S, state_data, session=self._session)
        await self._session.commit()

    async def count_for_file_and_state(self, file_id: int, state_tag_id: int) -> int:
        """Count assignments for a specific file + state-id combination."""
        stmt = (
            select(func.count())
            .select_from(_A)
            .where(
                _A.c.file_id == file_id,
                _A.c.state_id == state_tag_id,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def ensure_file_state(self, file_id: int, state: str) -> None:
        """Assign *state* to a file only if it has no state assignment yet.

        Used during file upsert to initialize newly created files with their
        default processing state.  Files that already carry at least one state
        assignment are left untouched.
        """
        stmt = select(func.count()).select_from(_A).where(_A.c.file_id == file_id)
        result = await self._session.execute(stmt)
        if (result.scalar() or 0) > 0:
            return
        await self.assign_state(file_id, state)

    async def truncate_assignments(self) -> None:
        """Delete all rows from ``file_state_assignments``."""
        await self._session.execute(delete(_A))
        await self._session.commit()
