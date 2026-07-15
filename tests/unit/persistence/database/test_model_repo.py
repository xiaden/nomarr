"""Unit tests for ModelRepo."""

from __future__ import annotations

import pytest

from nomarr.persistence.database.model_repo import ModelRepo
from nomarr.persistence.exceptions import PersistenceError


@pytest.mark.unit
@pytest.mark.integration
class TestModelRepo:
    """Tests for ModelRepo CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_upsert_model_insert(self, pg_session) -> None:
        """upsert_model should insert a new model and return it."""
        repo = ModelRepo(pg_session)
        record = await repo.upsert_model(
            {
                "id": "model_a",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        assert record["id"] == "model_a"
        assert record["model_type"] == "genre"
        assert record["backbone_id"] == "bb_1"
        assert record["enabled"] == 1
        assert record["created_at"] > 0
        assert record["updated_at"] > 0

    @pytest.mark.asyncio
    async def test_upsert_model_update(self, pg_session) -> None:
        """upsert_model should update an existing model on conflict."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "model_b",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        updated = await repo.upsert_model(
            {
                "id": "model_b",
                "model_type": "mood",
                "backbone_id": "bb_2",
                "enabled": 0,
            }
        )
        assert updated["id"] == "model_b"
        assert updated["model_type"] == "mood"
        assert updated["backbone_id"] == "bb_2"
        assert updated["enabled"] == 0

    @pytest.mark.asyncio
    async def test_get_model_existing(self, pg_session) -> None:
        """get_model should return the model record for an existing id."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "model_get",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        result = await repo.get_model("model_get")
        assert result is not None
        assert result["id"] == "model_get"
        assert result["model_type"] == "genre"

    @pytest.mark.asyncio
    async def test_get_model_nonexistent(self, pg_session) -> None:
        """get_model should return None for a missing id."""
        repo = ModelRepo(pg_session)
        result = await repo.get_model("nonexistent_model")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_model_by_type_existing(self, pg_session) -> None:
        """get_model_by_type should find a model by model_type field."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "model_path",
                "model_type": "unique_type",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        result = await repo.get_model_by_type("unique_type")
        assert result is not None
        assert result["id"] == "model_path"
        assert result["model_type"] == "unique_type"

    @pytest.mark.asyncio
    async def test_get_model_by_type_nonexistent(self, pg_session) -> None:
        """get_model_by_type should return None for a missing model_type."""
        repo = ModelRepo(pg_session)
        result = await repo.get_model_by_type("no_such_type")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_model_extended_fields(self, pg_session) -> None:
        """upsert_model should persist and round-trip all 11 extended fields."""
        repo = ModelRepo(pg_session)
        record = await repo.upsert_model(
            {
                "id": "model_ext",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
                "path": "/models/effnet/heads/sigmoid/mood_happy.onnx",
                "backbone": "effnet",
                "head_type": "sigmoid",
                "model_stem": "mood_happy",
                "output_count": 3,
                "fully_configured": 1,
                "is_known": 1,
                "source": "discovered",
                "head_release_date": "2026-01-15",
                "embedder_release_date": "2026-01-01",
                "registered_at": 1700000000,
            }
        )
        assert record["id"] == "model_ext"
        assert record["path"] == "/models/effnet/heads/sigmoid/mood_happy.onnx"
        assert record["backbone"] == "effnet"
        assert record["head_type"] == "sigmoid"
        assert record["model_stem"] == "mood_happy"
        assert record["output_count"] == 3
        assert record["fully_configured"] == 1
        assert record["is_known"] == 1
        assert record["source"] == "discovered"
        assert record["head_release_date"] == "2026-01-15"
        assert record["embedder_release_date"] == "2026-01-01"
        assert record["registered_at"] == 1700000000

    @pytest.mark.asyncio
    async def test_update_model(self, pg_session) -> None:
        """update_model should modify specified fields."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "model_upd",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.update_model("model_upd", {"enabled": 0, "backbone_id": "bb_2"})
        result = await repo.get_model("model_upd")
        assert result is not None
        assert result["enabled"] == 0
        assert result["backbone_id"] == "bb_2"
        assert result["model_type"] == "genre"  # unchanged

    @pytest.mark.asyncio
    async def test_update_model_not_found(self, pg_session) -> None:
        """update_model should raise PersistenceError for a missing model."""
        repo = ModelRepo(pg_session)
        with pytest.raises(PersistenceError, match="not found"):
            await repo.update_model("missing_model", {"enabled": 0})

    @pytest.mark.asyncio
    async def test_delete_model(self, pg_session) -> None:
        """delete_model should remove the model row."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "model_del",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.delete_model("model_del")
        result = await repo.get_model("model_del")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_models(self, pg_session) -> None:
        """list_models should return all model rows."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "list_1",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "list_2",
                "model_type": "mood",
                "backbone_id": "bb_2",
                "enabled": 0,
            }
        )
        result = await repo.list_models()
        ids = [r["id"] for r in result]
        assert "list_1" in ids
        assert "list_2" in ids

    @pytest.mark.asyncio
    async def test_count_models(self, pg_session) -> None:
        """count_models should return the total number of models."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "count_1",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "count_2",
                "model_type": "mood",
                "backbone_id": "bb_2",
                "enabled": 1,
            }
        )
        count = await repo.count_models()
        assert count >= 2

    @pytest.mark.asyncio
    async def test_get_models_by_ids(self, pg_session) -> None:
        """get_models_by_ids should return only the requested models."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "by_id_1",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "by_id_2",
                "model_type": "mood",
                "backbone_id": "bb_2",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "by_id_3",
                "model_type": "tempo",
                "backbone_id": "bb_3",
                "enabled": 1,
            }
        )
        result = await repo.get_models_by_ids(["by_id_1", "by_id_3"])
        ids = [r["id"] for r in result]
        assert "by_id_1" in ids
        assert "by_id_3" in ids
        assert "by_id_2" not in ids

    @pytest.mark.asyncio
    async def test_get_models_by_ids_empty(self, pg_session) -> None:
        """get_models_by_ids should return empty list for empty input."""
        repo = ModelRepo(pg_session)
        result = await repo.get_models_by_ids([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_enabled_models(self, pg_session) -> None:
        """get_enabled_models should return only models with enabled=1."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "enabled_1",
                "model_type": "genre",
                "backbone_id": "bb_1",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "disabled_1",
                "model_type": "mood",
                "backbone_id": "bb_2",
                "enabled": 0,
            }
        )
        result = await repo.get_enabled_models()
        ids = [r["id"] for r in result]
        assert "enabled_1" in ids
        assert "disabled_1" not in ids

    @pytest.mark.asyncio
    async def test_get_by_backbone(self, pg_session) -> None:
        """get_by_backbone should return models for a given backbone."""
        repo = ModelRepo(pg_session)
        await repo.upsert_model(
            {
                "id": "bb_model_1",
                "model_type": "genre",
                "backbone_id": "bb_target",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "bb_model_2",
                "model_type": "mood",
                "backbone_id": "bb_target",
                "enabled": 1,
            }
        )
        await repo.upsert_model(
            {
                "id": "bb_model_3",
                "model_type": "tempo",
                "backbone_id": "bb_other",
                "enabled": 1,
            }
        )
        result = await repo.get_by_backbone("bb_target")
        ids = [r["id"] for r in result]
        assert "bb_model_1" in ids
        assert "bb_model_2" in ids
        assert "bb_model_3" not in ids
