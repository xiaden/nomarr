"""Component-owned graph helpers for Navidrome track and playcount storage."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.navidrome_dto import TrackPlayData

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _edge_key(left_id: str, right_id: str) -> str:
    """Return a stable edge-document key for one source/target pair."""
    return hashlib.sha256(f"{left_id}:{right_id}".encode()).hexdigest()[:16]


def _build_edge_namespace(db: Database, name: str) -> Any:
    """Return the runtime-wired edge namespace for an edge collection."""
    return cast("Any", getattr(db, name))


def upsert_navidrome_track(db: Database, nd_id: str) -> None:
    """Ensure one Navidrome track vertex exists."""
    db.navidrome_tracks.upsert(_key=nd_id, fields={})


def bulk_upsert_navidrome_tracks(db: Database, nd_ids: list[str]) -> int:
    """Ensure all provided Navidrome track vertices exist."""
    if not nd_ids:
        return 0

    for nd_id in nd_ids:
        db.navidrome_tracks.upsert(_key=nd_id, fields={})
    return len(nd_ids)


def ensure_navidrome_file_link(db: Database, nd_id: str, file_id: str) -> None:
    """Ensure a single Navidrome track → library file edge exists."""
    bulk_ensure_navidrome_file_links(db, [{"nd_id": nd_id, "file_id": file_id}])


def bulk_ensure_navidrome_file_links(db: Database, mappings: list[dict[str, str]]) -> int:
    """Ensure track → file link edges exist for each mapping entry."""
    if not mappings:
        return 0

    has_nd_id = _build_edge_namespace(db, "has_nd_id")
    edge_count = has_nd_id.count()
    docs_to_insert: list[dict[str, str]] = []

    existing_targets_by_track: dict[str, set[str]] = {}
    for nd_id in {mapping["nd_id"] for mapping in mappings}:
        track_id = f"navidrome_tracks/{nd_id}"
        existing_edges = cast(
            "list[dict[str, Any]]",
            has_nd_id.get(_from=track_id, limit=edge_count or None),
        )
        existing_targets_by_track[track_id] = {str(edge["_to"]) for edge in existing_edges if "_to" in edge}

    for mapping in mappings:
        track_id = f"navidrome_tracks/{mapping['nd_id']}"
        file_id = mapping["file_id"]
        if file_id in existing_targets_by_track[track_id]:
            continue
        docs_to_insert.append(
            {
                "_key": _edge_key(track_id, file_id),
                "_from": track_id,
                "_to": file_id,
            }
        )
        existing_targets_by_track[track_id].add(file_id)

    if docs_to_insert:
        has_nd_id.insert(docs_to_insert)
    return len(docs_to_insert)


def list_navidrome_track_keys(db: Database) -> list[str]:
    """Return all Navidrome track `_key` values."""
    return [
        str(row["value"])
        for row in db.navidrome_tracks.aggregate("_key", limit=db.navidrome_tracks.count())
        if "value" in row
    ]


def delete_navidrome_tracks_cascade(db: Database, nd_ids: list[str]) -> int:
    """Cascade-delete track vertices and their connected edges."""
    if not nd_ids:
        return 0

    return sum(int(db.navidrome_tracks.delete.cascade(_key=nd_id)) for nd_id in nd_ids)


def resolve_navidrome_track_to_file(db: Database, nd_id: str) -> str | None:
    """Resolve one Navidrome track id to a library file `_id`."""
    track_id = f"navidrome_tracks/{nd_id}"
    file_docs = cast("list[dict[str, Any]]", db.navidrome_tracks.has_nd_id(track_id, limit=1))
    if not file_docs:
        return None
    return cast("str | None", file_docs[0].get("_id"))


def resolve_file_to_navidrome_track(db: Database, file_id: str) -> str | None:
    """Resolve one library file `_id` to its Navidrome track key."""
    has_nd_id = _build_edge_namespace(db, "has_nd_id")
    edges = cast("list[dict[str, Any]]", has_nd_id.get(_to=file_id, limit=1))
    if not edges:
        return None
    track_id = cast("str | None", edges[0].get("_from"))
    if track_id is None:
        return None
    return track_id.split("/", 1)[-1]


def bulk_resolve_navidrome_tracks_to_files(db: Database, nd_ids: list[str]) -> dict[str, str]:
    """Resolve multiple Navidrome track ids to library file ids."""
    result: dict[str, str] = {}
    for nd_id in nd_ids:
        file_id = resolve_navidrome_track_to_file(db, nd_id)
        if file_id is not None:
            result[nd_id] = file_id
    return result


def bulk_resolve_files_to_navidrome_ids(db: Database, file_ids: list[str]) -> dict[str, str]:
    """Resolve multiple library file ids to Navidrome track ids."""
    if not file_ids:
        return {}

    has_nd_id = _build_edge_namespace(db, "has_nd_id")
    result: dict[str, str] = {}
    for file_id in file_ids:
        edges = cast("list[dict[str, Any]]", has_nd_id.get(_to=file_id, limit=1))
        if not edges:
            continue
        track_id = cast("str | None", edges[0].get("_from"))
        if track_id is not None:
            result[file_id] = track_id.split("/", 1)[-1]
    return result


def upsert_navidrome_play(
    db: Database,
    user_id: str,
    nd_id: str,
    playcount: int,
    last_played: int,
) -> None:
    """Upsert one bucketed playcount vertex and its track edge."""
    if playcount < 0:
        return

    plays_ns = _build_edge_namespace(db, "has_plays")
    track_id = f"navidrome_tracks/{nd_id}"
    bucket_key = f"{playcount}:{user_id}"
    bucket_id = f"navidrome_playcounts/{bucket_key}"
    edge_count = plays_ns.count()

    existing_edges = cast(
        "list[dict[str, Any]]",
        plays_ns.get(_from=track_id, limit=edge_count or None),
    )
    for edge in existing_edges:
        target_id = cast("str | None", edge.get("_to"))
        if target_id is None:
            continue
        bucket_doc = cast("dict[str, Any] | None", db.navidrome_playcounts.get(_id=target_id))
        if bucket_doc is not None and bucket_doc.get("userid") == user_id:
            plays_ns.delete(_id=cast("str", edge["_id"]))

    db.navidrome_playcounts.upsert(
        _key=bucket_key,
        fields={
            "playcount": playcount,
            "userid": user_id,
        },
    )
    plays_ns.insert(
        [
            {
                "_key": _edge_key(track_id, bucket_id),
                "_from": track_id,
                "_to": bucket_id,
                "last_played": last_played,
            }
        ]
    )


def increment_navidrome_play(db: Database, user_id: str, nd_id: str, timestamp_ms: int) -> None:
    """Move one track to the next playcount bucket for the user."""
    plays_ns = _build_edge_namespace(db, "has_plays")
    track_id = f"navidrome_tracks/{nd_id}"
    edge_count = plays_ns.count()
    existing_edges = cast(
        "list[dict[str, Any]]",
        plays_ns.get(_from=track_id, limit=edge_count or None),
    )

    old_count = 0
    for edge in existing_edges:
        target_id = cast("str | None", edge.get("_to"))
        if target_id is None:
            continue
        bucket_doc = cast("dict[str, Any] | None", db.navidrome_playcounts.get(_id=target_id))
        if bucket_doc is None or bucket_doc.get("userid") != user_id:
            continue
        old_count = int(cast("int", bucket_doc.get("playcount", 0)))
        plays_ns.delete(_id=cast("str", edge["_id"]))
        break

    upsert_navidrome_play(db, user_id, nd_id, old_count + 1, timestamp_ms)


def bulk_upsert_navidrome_plays(db: Database, user_id: str, plays: list[dict[str, Any]]) -> int:
    """Replace the user's existing bucketed play graph with the provided payload."""
    buckets = cast(
        "list[dict[str, Any]]",
        db.navidrome_playcounts.get(userid=user_id, limit=db.navidrome_playcounts.count()),
    )
    plays_ns = _build_edge_namespace(db, "has_plays")
    for bucket in buckets:
        bucket_id = cast("str | None", bucket.get("_id"))
        if bucket_id is not None:
            plays_ns.delete(_to=bucket_id)

    if buckets:
        db.navidrome_playcounts.delete(userid=user_id)

    if not plays:
        return 0

    bucket_docs_by_key: dict[str, dict[str, Any]] = {}
    edge_docs: list[dict[str, Any]] = []
    for play in plays:
        nd_id = cast("str", play["nd_id"])
        playcount = int(cast("int", play["playcount"]))
        last_played = int(cast("int", play["last_played"]))
        bucket_key = f"{playcount}:{user_id}"
        bucket_docs_by_key.setdefault(
            bucket_key,
            {
                "_key": bucket_key,
                "playcount": playcount,
                "userid": user_id,
            },
        )
        track_id = f"navidrome_tracks/{nd_id}"
        bucket_id = f"navidrome_playcounts/{bucket_key}"
        edge_docs.append(
            {
                "_key": _edge_key(track_id, bucket_id),
                "_from": track_id,
                "_to": bucket_id,
                "last_played": last_played,
            }
        )

    for bucket_doc in bucket_docs_by_key.values():
        db.navidrome_playcounts.upsert(
            _key=cast("str", bucket_doc["_key"]),
            fields={key: value for key, value in bucket_doc.items() if key != "_key"},
        )
    plays_ns.insert(edge_docs)
    return len(edge_docs)


def get_top_navidrome_plays(db: Database, user_id: str, top_n: int) -> list[TrackPlayData]:
    """Return the user's most-played tracks, resolving ``file_id`` where a library link exists."""
    if top_n <= 0:
        return []

    buckets = cast(
        "list[dict[str, Any]]",
        db.navidrome_playcounts.get(userid=user_id, limit=db.navidrome_playcounts.count()),
    )
    if not buckets:
        return []

    plays_ns = _build_edge_namespace(db, "has_plays")
    has_nd_id = _build_edge_namespace(db, "has_nd_id")
    results: list[TrackPlayData] = []

    for bucket in sorted(buckets, key=lambda doc: int(cast("int", doc.get("playcount", 0))), reverse=True):
        bucket_id = cast("str | None", bucket.get("_id"))
        if bucket_id is None:
            continue
        remaining = top_n - len(results)
        if remaining <= 0:
            break

        edges = cast("list[dict[str, Any]]", plays_ns.get(_to=bucket_id, limit=remaining))
        for edge in edges:
            track_id = cast("str | None", edge.get("_from"))
            if track_id is None:
                continue
            file_edges = cast("list[dict[str, Any]]", has_nd_id.get(_from=track_id, limit=1))
            file_id = cast("str | None", file_edges[0].get("_to")) if file_edges else None
            results.append(
                TrackPlayData(
                    nd_id=track_id.split("/", 1)[-1],
                    file_id=file_id,
                    playcount=int(cast("int", bucket.get("playcount", 0))),
                    last_played=cast("int | None", edge.get("last_played")),
                )
            )
            if len(results) >= top_n:
                return results

    return results
