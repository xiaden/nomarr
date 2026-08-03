"""Integration tests for pg_trgm fuzzy matching and FK index verification.

Tests that:
1. pg_trgm extension is installed and similarity() works.
2. Fuzzy match via pg_trgm ``%`` operator finds typo-tolerant results.
3. Every FK column in the schema has a supporting B-tree index.
4. FK cascade enforcement works correctly across the library→file→embedding chain.

Covers plan steps P5-S1 (pg_trgm) and P5-S2 (FK indexes).
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.exc import IntegrityError

from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "test_backbone"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_library(session, name: str = "Test Lib") -> int:
    """Insert a library row and return its id."""
    r = session.execute(
        insert(Library).values(
            name=name,
            path=f"/music/{name.lower().replace(' ', '_')}",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return int(r.inserted_primary_key[0])


def _create_file(session, library_id: int, path: str) -> int:
    """Insert a library file row and return its id."""
    r = session.execute(
        insert(LibraryFile).values(
            library_id=library_id,
            path=path,
            normalized_path=path,
            file_size=1000,
            modified_time=1000,
            duration_seconds=180,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    return int(r.inserted_primary_key[0])


def _random_vector(dim: int = _EMBED_DIM, seed: int = 42) -> list[float]:
    """Generate a deterministic random L2-normalized vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()  # type: ignore[no-any-return]


# ── pg_trgm fuzzy matching ──────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestPgTrgm:
    """pg_trgm extension availability and fuzzy matching tests."""

    def test_pg_trgm_extension_available(self, pg_engine: Engine) -> None:
        """pg_trgm extension should be installable and similarity() should return > 0."""
        with pg_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            result = conn.execute(text("SELECT similarity('foo', 'foobar')"))
            sim = result.scalar()
            assert sim is not None
            assert sim > 0

    def test_fuzzy_match_typo_query(self, pg_engine: Engine) -> None:
        """pg_trgm ``%`` operator should match paths with typos (e.g. 'Abby Road' → 'Abbey Road')."""
        with pg_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

            # Insert test data via raw SQL
            r = conn.execute(
                text(
                    "INSERT INTO libraries (name, path, library_type, auto_tag, auto_curate, "
                    "created_at, updated_at) VALUES ('Beatles Lib', '/music/beatles', 'music', "
                    "0, 0, 1000, 1000) RETURNING id"
                )
            )
            lib_id = r.scalar()

            paths = [
                "/music/beatles/Abbey Road/01-come_together.flac",
                "/music/beatles/Dark Side of the Moon/01-speak_to_me.flac",
                "/music/beatles/Led Zeppelin IV/01-black_mountain_side.flac",
            ]
            for path in paths:
                conn.execute(
                    text(
                        "INSERT INTO songs (library_id, path, normalized_path, file_size, "
                        "modified_time, duration_seconds, needs_tagging, is_valid, tagged, created_at) "
                        "VALUES (:lib_id, :path, :path, 1000, 1000, 180, 0, 1, 0, 1000)"
                    ),
                    {"lib_id": lib_id, "path": path},
                )
            conn.commit()

            # Query with pg_trgm similarity — 'Abby Road' should match 'Abbey Road'
            result = conn.execute(
                text("SELECT path, similarity(path, 'Abby Road') AS sim FROM songs WHERE path % 'Abby Road'")
            )
            rows = result.fetchall()
            assert len(rows) >= 1, "pg_trgm should find at least one fuzzy match for 'Abby Road'"

            # The Abbey Road path should be among the matches
            abbey_matches = [r for r in rows if "Abbey" in r[0]]
            assert len(abbey_matches) >= 1
            assert abbey_matches[0][1] >= 0.10, "Similarity should be non-trivial"

    def test_similarity_scores_for_typo_queries(self, pg_engine: Engine) -> None:
        """Verify similarity() returns expected scores for common typo patterns."""
        with pg_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

            # Direct similarity tests
            cases = [
                ("Abbey Road", "Abby Road"),
                ("Dark Side of the Moon", "Dark Side of Moon"),
                ("Led Zeppelin IV", "Led Zepplin IV"),
            ]
            for correct, typo in cases:
                result = conn.execute(text(f"SELECT similarity('{correct}', '{typo}')"))
                sim = result.scalar()
                assert sim is not None
                assert sim > 0, f"similarity('{correct}', '{typo}') should be > 0"


# ── FK index verification ───────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestFkIndexes:
    """Verify every FK column has a supporting B-tree index."""

    def test_all_fk_columns_have_supporting_indexes(self, pg_engine: Engine) -> None:
        """Query pg_catalog to verify every FK column has a supporting index.

        This enforces the DD §6/§7 requirement that every FK column must have
        a supporting index to prevent FK CASCADE deadlock during
        ``remove_library()`` and other cascade operations.
        """
        with pg_engine.connect() as conn:
            # Find all FK columns
            fk_result = conn.execute(
                text(
                    "SELECT tc.table_schema, tc.table_name, kcu.column_name "
                    "FROM information_schema.table_constraints AS tc "
                    "JOIN information_schema.key_column_usage AS kcu "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    "  AND tc.table_schema = kcu.table_schema "
                    "WHERE tc.constraint_type = 'FOREIGN KEY' "
                    "ORDER BY tc.table_name, kcu.column_name"
                )
            )
            fk_columns = fk_result.fetchall()
            assert len(fk_columns) > 0, "Schema should have FK constraints"

            missing_indexes: list[str] = []
            for schema, table, column in fk_columns:
                # Check if this FK column is the leading column of any index
                idx_result = conn.execute(
                    text(
                        "SELECT 1 FROM pg_indexes "
                        "WHERE schemaname = :schema AND tablename = :table "
                        "AND (indexdef LIKE :pat1 OR indexdef LIKE :pat2) "
                        "LIMIT 1"
                    ),
                    {
                        "schema": schema,
                        "table": table,
                        "pat1": f"%({column},%)",  # leading column in composite
                        "pat2": f"%({column})%",  # single-column or trailing
                    },
                )
                if idx_result.scalar() is None:
                    missing_indexes.append(f"{table}.{column}")

            assert not missing_indexes, f"FK columns missing supporting indexes: {', '.join(missing_indexes)}"

    def test_critical_cascade_indexes_exist(self, pg_engine: Engine) -> None:
        """Verify specific critical indexes exist for cascade delete performance."""
        with pg_engine.connect() as conn:
            result = conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY indexname")
            )
            index_names = {row[0] for row in result.fetchall()}

            # These are the auto-generated B-tree indexes from index=True on FK columns
            expected_indexes = [
                "embeddings_file_id_idx",
                "file_tags_file_id_idx",
                "file_tags_tag_id_idx",
                "songs_library_id_idx",
                "library_folders_library_id_idx",
                "ml_output_streams_file_id_idx",
                "ml_output_streams_model_id_idx",
            ]

            missing = [idx for idx in expected_indexes if idx not in index_names]
            assert not missing, f"Critical cascade indexes missing: {', '.join(missing)}"


# ── FK cascade enforcement ──────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestFkEnforcement:
    """Verify FK constraints and cascade behavior."""

    def test_cascade_delete_library_removes_embeddings(self, pg_session) -> None:
        """Deleting a library should cascade through files to embeddings.

        The FK chain is: libraries → songs → embeddings (all CASCADE).
        Verifies zero orphaned rows after remove_library().
        """
        lib_id = _create_library(pg_session, "FK Cascade Lib")
        file_id = _create_file(pg_session, lib_id, "/music/fk_test/test.mp3")

        # Insert an embedding
        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            file_id=file_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=42),
        )

        # Verify embedding exists
        embeddings = repo.get_embeddings_for_file(file_id)
        assert len(embeddings) == 1

        # Delete the library — should cascade through files to embeddings
        lib_repo = LibraryRepository(pg_session)
        lib_repo.remove_library(lib_id)

        # Verify library is gone
        result = pg_session.execute(text("SELECT COUNT(*) FROM libraries WHERE id = :id"), {"id": lib_id})
        assert result.scalar() == 0

        # Verify file is gone (cascaded)
        result = pg_session.execute(text("SELECT COUNT(*) FROM songs WHERE id = :id"), {"id": file_id})
        assert result.scalar() == 0

        # Verify embedding is gone (cascaded)
        embeddings = repo.get_embeddings_for_file(file_id)
        assert len(embeddings) == 0

    def test_insert_embedding_with_invalid_file_id_fails(self, pg_session) -> None:
        """Inserting an embedding with a non-existent file_id should raise FK violation."""
        repo = VectorRepo(pg_session)
        with pytest.raises(IntegrityError) as exc_info:
            repo.insert_embedding(
                file_id=999999,  # non-existent
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=77),
            )
        # Should be a foreign key violation
        assert "foreign key" in str(exc_info.value).lower() or "violates" in str(exc_info.value).lower()
