"""Focused tests for canonical ``LibraryFilesAqlOperations`` helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations


@pytest.mark.unit
@pytest.mark.mocked
def test_upsert_files_for_library_with_state_init_bootstraps_new_and_tagged_files() -> None:
    db = MagicMock()
    file_states = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payloads: list[dict[str, Any]] = [
        {"path": "C:/music/existing.flac"},
        {"path": "C:/music/new.flac", "last_tagged_at": 1234},
    ]

    with (
        patch.object(ops, "list_existing_file_paths", return_value=["C:/music/existing.flac"]) as list_existing,
        patch.object(
            ops,
            "upsert_files_for_library",
            return_value=["library_files/existing", "library_files/new"],
        ) as upsert_files,
    ):
        result = ops.upsert_files_for_library_with_state_init(
            "libraries/1",
            payloads,
            file_states=file_states,
        )

    assert result == {"file_ids": ["library_files/existing", "library_files/new"], "added": 1}
    list_existing.assert_called_once_with(["C:/music/existing.flac", "C:/music/new.flac"])
    upsert_files.assert_called_once_with("libraries/1", payloads)
    file_states.bootstrap_file_states.assert_called_once_with(["library_files/new"])
    file_states.mark_files_tagged.assert_called_once_with(["library_files/new"])


@pytest.mark.unit
@pytest.mark.mocked
def test_reconcile_library_files_delegates_to_canonical_helpers_and_reports_counts() -> None:
    db = MagicMock()
    file_states = MagicMock()
    streams = MagicMock()
    vectors = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payloads = [{"path": "C:/music/current.flac"}]

    with (
        patch.object(
            ops,
            "list_library_file_ids",
            return_value=["library_files/current", "library_files/stale"],
        ) as list_file_ids,
        patch.object(
            ops,
            "upsert_files_for_library_with_state_init",
            return_value={"file_ids": ["library_files/current"], "added": 0},
        ) as upsert_files,
        patch.object(ops, "remove_files_with_derived_cleanup") as remove_files,
    ):
        result = ops.reconcile_library_files(
            "libraries/1",
            payloads,
            remove_missing=True,
            file_states=file_states,
            streams=streams,
            vectors=vectors,
        )

    assert result == {"added": 0, "updated": 1, "removed": 1}
    list_file_ids.assert_called_once_with("libraries/1")
    upsert_files.assert_called_once_with("libraries/1", payloads, file_states=file_states)
    remove_files.assert_called_once_with(["library_files/stale"], streams=streams, vectors=vectors)


@pytest.mark.unit
@pytest.mark.mocked
def test_remove_files_with_derived_cleanup_deletes_streams_vectors_then_files() -> None:
    db = MagicMock()
    streams = MagicMock()
    vectors = MagicMock()
    vectors.list_registered_vector_collection_names.return_value = ["vectors_a", "vectors_b"]
    ops = LibraryFilesAqlOperations(db)

    with patch.object(ops, "remove_files") as remove_files:
        ops.remove_files_with_derived_cleanup(
            ["library_files/1", "library_files/1", "library_files/2"],
            streams=streams,
            vectors=vectors,
        )

    assert streams.delete_output_streams_for_file.call_args_list == [
        call("library_files/1"),
        call("library_files/2"),
    ]
    assert vectors.delete_vectors_for_file.call_args_list == [
        call("vectors_a", "library_files/1"),
        call("vectors_a", "library_files/2"),
        call("vectors_b", "library_files/1"),
        call("vectors_b", "library_files/2"),
    ]
    remove_files.assert_called_once_with(["library_files/1", "library_files/2"])


@pytest.mark.unit
@pytest.mark.mocked
def test_add_library_folder_adds_folder_links_it_and_returns_folder_id() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payload: dict[str, Any] = {"path": "C:/music"}
    events: list[tuple[str, str]] = []

    def add_folder_side_effect(folder_payload: dict[str, Any]) -> str:
        events.append(("add_folder", folder_payload["path"]))
        return "library_folders/f1"

    def link_side_effect(library_id: str, folder_id: str) -> None:
        events.append(("link_folder", f"{library_id}->{folder_id}"))

    with (
        patch.object(ops, "add_folder", side_effect=add_folder_side_effect) as add_folder,
        patch.object(ops, "_link_folder_to_library", side_effect=link_side_effect) as link_folder,
    ):
        result = ops.add_library_folder("libraries/1", payload)

    assert result == "library_folders/f1"
    add_folder.assert_called_once_with(payload)
    link_folder.assert_called_once_with("libraries/1", "library_folders/f1")
    assert events == [
        ("add_folder", "C:/music"),
        ("link_folder", "libraries/1->library_folders/f1"),
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_remove_library_folder_deletes_link_then_folder() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    events: list[str] = []

    def delete_link_side_effect(library_id: str, folder_id: str) -> None:
        events.append(f"link:{library_id}->{folder_id}")

    def delete_folder_side_effect(folder_id: str) -> None:
        events.append(f"folder:{folder_id}")

    with (
        patch.object(ops, "_delete_folder_link", side_effect=delete_link_side_effect) as delete_link,
        patch.object(ops, "_delete_folder", side_effect=delete_folder_side_effect) as delete_folder,
    ):
        ops.remove_library_folder("libraries/1", "library_folders/f1")

    delete_link.assert_called_once_with("libraries/1", "library_folders/f1")
    delete_folder.assert_called_once_with("library_folders/f1")
    assert events == [
        "link:libraries/1->library_folders/f1",
        "folder:library_folders/f1",
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_library_folders_replaces_existing_folders_with_new_payloads() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payloads: list[dict[str, Any]] = [
        {"path": "C:/music/new-a"},
        {"path": "C:/music/new-b"},
    ]
    existing_folders = [
        {"_id": "library_folders/1"},
        {"_id": "library_folders/2"},
    ]

    with (
        patch.object(ops, "list_folders_for_library", return_value=existing_folders) as list_folders,
        patch.object(ops, "remove_library_folder") as remove_folder,
        patch.object(ops, "add_library_folder") as add_folder,
    ):
        ops.replace_library_folders("libraries/1", payloads)

    list_folders.assert_called_once_with("libraries/1")
    assert remove_folder.call_args_list == [
        call("libraries/1", "library_folders/1"),
        call("libraries/1", "library_folders/2"),
    ]
    assert add_folder.call_args_list == [
        call("libraries/1", {"path": "C:/music/new-a"}),
        call("libraries/1", {"path": "C:/music/new-b"}),
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_library_folders_removes_existing_folders_without_adding_when_payloads_empty() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    existing_folders = [
        {"_id": "library_folders/1"},
        {"_id": "library_folders/2"},
    ]

    with (
        patch.object(ops, "list_folders_for_library", return_value=existing_folders) as list_folders,
        patch.object(ops, "remove_library_folder") as remove_folder,
        patch.object(ops, "add_library_folder") as add_folder,
    ):
        ops.replace_library_folders("libraries/1", [])

    list_folders.assert_called_once_with("libraries/1")
    assert remove_folder.call_args_list == [
        call("libraries/1", "library_folders/1"),
        call("libraries/1", "library_folders/2"),
    ]
    add_folder.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_delete_folders_for_library_delegates_to_delete_many_by_field() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)

    with (
        patch(
            "nomarr.persistence.database.library_files_aql.primitives.delete_many_by_field", return_value=5
        ) as delete_many,
        patch("nomarr.persistence.database.library_files_aql.primitives.get_many_by_field") as get_many,
        patch("nomarr.persistence.database.library_files_aql.primitives.delete_many_by_keys") as delete_keys,
    ):
        result = ops._delete_folders_for_library("lib123")

    assert result == 5
    delete_many.assert_called_once_with(
        db,
        ops.FOLDER_COLLECTION,
        "library_key",
        "lib123",
        allowed_fields=ops.ALLOWED_FOLDER_FIELDS,
    )
    get_many.assert_not_called()
    delete_keys.assert_not_called()
    db.aql.execute.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_upsert_files_batch_uses_internal_upsert_many_by_field() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payloads: list[dict[str, Any]] = [
        {"path": "C:/music/one.flac"},
        {"path": "C:/music/two.flac"},
    ]

    with patch.object(ops, "_upsert_many_by_field", return_value=["library_files/1", "library_files/2"]) as upsert_many:
        result = ops._upsert_files_batch(payloads)

    assert result == ["library_files/1", "library_files/2"]
    upsert_many.assert_called_once_with(ops.FILE_COLLECTION, "path", payloads)


@pytest.mark.unit
@pytest.mark.mocked
def test_upsert_many_by_field_returns_empty_list_for_empty_payloads() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)

    result = ops._upsert_many_by_field(ops.FILE_COLLECTION, "path", [])

    assert result == []
    db.aql.execute.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_upsert_many_by_field_rejects_invalid_field_name_before_query_execution() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)
    payloads: list[dict[str, Any]] = [{"path": "C:/music/one.flac"}]

    with pytest.raises(ValueError, match="field"):
        ops._upsert_many_by_field(ops.FILE_COLLECTION, "bad-field", payloads)

    db.aql.execute.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_upsert_many_by_field_builds_upsert_query_and_returns_ids() -> None:
    db = MagicMock()
    db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
    ops = LibraryFilesAqlOperations(db)
    payloads: list[dict[str, Any]] = [
        {"path": "C:/music/one.flac", "size": 123},
        {"path": "C:/music/two.flac", "size": 456},
    ]

    result = ops._upsert_many_by_field(ops.FILE_COLLECTION, "path", payloads)

    assert result == ["library_files/1", "library_files/2"]
    call = db.aql.execute.call_args
    assert call is not None
    query = call.args[0]
    assert "UPSERT" in query
    assert "INSERT doc" in query
    assert "UPDATE doc" in query
    assert "IN @@collection" in query
    assert "RETURN NEW._id" in query
    assert call.kwargs["bind_vars"] == {"@collection": ops.FILE_COLLECTION, "docs": payloads}


@pytest.mark.unit
@pytest.mark.mocked
def test_remove_files_orphaned_tag_cleanup_only_queries_song_edges() -> None:
    db = MagicMock()
    ops = LibraryFilesAqlOperations(db)

    ops.remove_files(["library_files/1", "library_files/2"])

    executed_queries = [call.args[0] for call in db.aql.execute.call_args_list]

    assert executed_queries
    assert all("tag_model_output" not in query for query in executed_queries)
    assert "song_has_tags" in executed_queries[-1]
