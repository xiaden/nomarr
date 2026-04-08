"""Read-only queries over file state edges."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import (
    _EDGE_COLLECTION,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_TAGGED,
    STATE_TAGGED,
    STATE_TAGS_STALE,
    STATE_TOO_SHORT,
)
from ._helpers import _scalar_int

if TYPE_CHECKING:
    from arango.cursor import Cursor


class FileStatesQueriesMixin:
    """Read-only queries for the ``file_has_state`` edge graph."""

    db: DatabaseLike

    def discover_next_untagged_file(
        self,
        library_id: str | None = None,
        exclude_claimed: bool = True,
    ) -> dict[str, Any] | None:
        """Find the next file eligible for tagging, optionally restricted to one library, and return the file document or ``None``.

        Exclude files in the ``too_short`` or ``errored`` states and, when requested, files with active worker claims.
        """
        parts: list[str] = []
        bind_vars: dict[str, Any] = {
            "not_tagged": STATE_NOT_TAGGED,
            "too_short": STATE_TOO_SHORT,
            "errored": STATE_ERRORED,
        }

        parts.append("LET too_short_ids = (FOR f IN INBOUND @too_short file_has_state RETURN f._id)")
        parts.append("LET errored_ids = (FOR f IN INBOUND @errored file_has_state RETURN f._id)")

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @not_tagged file_has_state")
        parts.append("    FILTER file._id NOT IN too_short_ids")
        parts.append("    FILTER file._id NOT IN errored_ids")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        if exclude_claimed:
            parts.append(
                "    FILTER LENGTH("
                "FOR c IN worker_claims "
                'FILTER c.file_id == file._id AND c.status == "active" '
                "RETURN 1) == 0"
            )

        parts.append("    SORT file._key")
        parts.append("    LIMIT 1")
        parts.append("    RETURN file")

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                "\n".join(parts),
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        results = list(cursor)
        return results[0] if results else None

    def get_untagged_file_ids(self, library_id: str | None = None, limit: int = 100) -> list[str]:
        """Return up to ``limit`` file IDs in the ``not_tagged`` state, optionally restricted to one library."""
        parts: list[str] = []
        bind_vars: dict[str, Any] = {"not_tagged": STATE_NOT_TAGGED, "limit": limit}

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @not_tagged file_has_state")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        parts.append("    SORT file._key")
        parts.append("    LIMIT @limit")
        parts.append("    RETURN file._id")

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                "\n".join(parts),
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)

    def count_untagged_files(self, library_id: str | None = None) -> int:
        """Count files in the ``not_tagged`` state, optionally restricted to one library."""
        parts: list[str] = []
        bind_vars: dict[str, Any] = {"not_tagged": STATE_NOT_TAGGED}

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        inner = "FOR f IN INBOUND @not_tagged file_has_state"
        if library_id is not None:
            inner += " FILTER f._id IN lib_files"
        inner += " RETURN 1"

        parts.append(f"LET untagged = ({inner})")
        parts.append("RETURN LENGTH(untagged)")
        return _scalar_int(self.db, "\n".join(parts), bind_vars)

    def count_uncalibrated_files(self) -> int:
        """Count files in the ``not_calibrated`` state across all libraries."""

        return _scalar_int(
            self.db,
            "RETURN LENGTH(FOR f IN INBOUND @not_calibrated file_has_state RETURN 1)",
            {"not_calibrated": STATE_NOT_CALIBRATED},
        )

    def get_errored_file_ids(self, library_id: str, limit: int = 500) -> list[str]:
        """Return up to ``limit`` file IDs in the ``errored`` state for the given library."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
                FOR e IN file_has_state
                    FILTER e._to == @errored AND e._from IN lib_files
                    LIMIT @limit
                    RETURN e._from
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": f"libraries/{library_id}",
                        "errored": STATE_ERRORED,
                        "limit": limit,
                    },
                ),
            ),
        )
        return list(cursor)

    def count_errored_files(self, library_id: str) -> int:
        """Count files in the ``errored`` state for the given library."""
        return _scalar_int(
            self.db,
            """
            LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
            LET errored = (FOR e IN file_has_state FILTER e._to == @errored AND e._from IN lib_files RETURN 1)
            RETURN LENGTH(errored)
            """,
            {
                "library_id": f"libraries/{library_id}",
                "errored": STATE_ERRORED,
            },
        )

    def get_uncalibrated_tagged_file_ids(self, library_id: str) -> list[str]:
        """Return file IDs that are both ``tagged`` and ``not_calibrated`` for the given library."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
                LET tagged = (FOR e IN file_has_state FILTER e._to == @tagged AND e._from IN lib_files RETURN e._from)
                LET uncalibrated = (
                    FOR e IN file_has_state
                        FILTER e._to == @not_calibrated AND e._from IN lib_files
                        RETURN e._from
                )
                FOR id IN INTERSECTION(tagged, uncalibrated)
                    RETURN id
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "tagged": STATE_TAGGED,
                        "not_calibrated": STATE_NOT_CALIBRATED,
                        "library_id": library_id,
                    },
                ),
            ),
        )
        return list(cursor)

    def get_stale_file_ids(self, library_id: str | None = None) -> list[str]:
        """Return file IDs in the ``tags_stale`` state, optionally restricted to one library."""
        parts: list[str] = []
        bind_vars: dict[str, Any] = {"tags_stale": STATE_TAGS_STALE}

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @tags_stale file_has_state")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        parts.append("    RETURN file._id")

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                "\n".join(parts),
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)

    def get_calibration_status_by_library(self) -> list[dict[str, Any]]:
        """Return per-library counts for the ``calibrated`` and ``not_calibrated`` states."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR lib IN libraries
                    LET lib_file_ids = (
                        FOR f IN OUTBOUND lib._id library_contains_file RETURN f._id
                    )
                    LET calibrated_count = LENGTH(
                        FOR f IN INBOUND @calibrated file_has_state
                            FILTER f._id IN lib_file_ids
                            RETURN 1
                    )
                    LET not_calibrated_count = LENGTH(
                        FOR f IN INBOUND @not_calibrated file_has_state
                            FILTER f._id IN lib_file_ids
                            RETURN 1
                    )
                    RETURN {
                        library_id: lib._id,
                        calibrated_count: calibrated_count,
                        not_calibrated_count: not_calibrated_count
                    }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "calibrated": STATE_CALIBRATED,
                        "not_calibrated": STATE_NOT_CALIBRATED,
                    },
                ),
            ),
        )
        return list(cursor)

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Return whether the given library contains at least one ``tagged`` file."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR file IN OUTBOUND @library_id library_contains_file
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        LIMIT 1
                        RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "state": STATE_TAGGED,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        return bool(next(cursor, False))

    def get_files_with_incomplete_tags(
        self,
        expected_heads: list[dict[str, Any]],
        namespace_prefix: str,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return tagged files missing one or more expected heads for the given namespace prefix, optionally restricted to one library.

        Include file identifiers plus matched and missing head counts in each result.
        """
        bind_vars: dict[str, Any] = {
            "namespace_prefix": namespace_prefix,
            "expected_heads": expected_heads,
            "tagged": STATE_TAGGED,
        }

        if library_id is not None:
            bind_vars["library_id"] = library_id
            query = """
                LET expected = @expected_heads
                FOR edge IN file_has_state
                    FILTER edge._to == @tagged
                    LET file = DOCUMENT(edge._from)
                    FILTER file != null
                    FILTER LENGTH(
                        FOR lib IN INBOUND file._id library_contains_file
                            FILTER lib._id == @library_id
                            LIMIT 1
                            RETURN 1
                    ) > 0
                    LET matched_heads = UNIQUE(
                        FOR tag_edge IN song_has_tags
                            FILTER tag_edge._from == file._id
                            LET tag = DOCUMENT(tag_edge._to)
                            FILTER tag != null
                            FILTER STARTS_WITH(tag.rel, @namespace_prefix)
                            LET rel_without_prefix = SUBSTRING(tag.rel, 4)
                            LET first_underscore = FIND_FIRST(rel_without_prefix, "_")
                            LET label = first_underscore >= 0
                                ? SUBSTRING(rel_without_prefix, 0, first_underscore)
                                : rel_without_prefix
                            FOR exp IN expected
                                FILTER label IN exp.labels
                                FILTER CONTAINS(rel_without_prefix, exp.model_key_for_tag)
                                RETURN exp.head_key
                    )
                    LET missing_heads = (
                        FOR exp IN expected
                            FILTER exp.head_key NOT IN matched_heads
                            RETURN exp.head_key
                    )
                    RETURN {
                        file_id: file._id,
                        file_key: file._key,
                        library_id: @library_id,
                        matched_count: LENGTH(matched_heads),
                        missing_count: LENGTH(missing_heads),
                        missing_heads: missing_heads
                    }
            """
        else:
            query = """
                LET expected = @expected_heads
                FOR edge IN file_has_state
                    FILTER edge._to == @tagged
                    LET file = DOCUMENT(edge._from)
                    FILTER file != null
                    LET matched_heads = UNIQUE(
                        FOR tag_edge IN song_has_tags
                            FILTER tag_edge._from == file._id
                            LET tag = DOCUMENT(tag_edge._to)
                            FILTER tag != null
                            FILTER STARTS_WITH(tag.rel, @namespace_prefix)
                            LET rel_without_prefix = SUBSTRING(tag.rel, 4)
                            LET first_underscore = FIND_FIRST(rel_without_prefix, "_")
                            LET label = first_underscore >= 0
                                ? SUBSTRING(rel_without_prefix, 0, first_underscore)
                                : rel_without_prefix
                            FOR exp IN expected
                                FILTER label IN exp.labels
                                FILTER CONTAINS(rel_without_prefix, exp.model_key_for_tag)
                                RETURN exp.head_key
                    )
                    LET missing_heads = (
                        FOR exp IN expected
                            FILTER exp.head_key NOT IN matched_heads
                            RETURN exp.head_key
                    )
                    RETURN {
                        file_id: file._id,
                        file_key: file._key,
                        library_id: file.library_id,
                        matched_count: LENGTH(matched_heads),
                        missing_count: LENGTH(missing_heads),
                        missing_heads: missing_heads
                    }
            """

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)
