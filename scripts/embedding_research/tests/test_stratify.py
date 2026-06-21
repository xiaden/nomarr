from __future__ import annotations

import pytest

from scripts.embedding_research.common.stratify import _budget_tolerance, run_stratify


def _insert_songs(con, songs: list[dict]) -> None:
    """Insert rows into songs table. Each dict must have song_id; artist/genre are optional."""
    con.executemany(
        "INSERT INTO songs (song_id, path, artist, genre) VALUES (?, ?, ?, ?)",
        [
            (
                s["song_id"],
                s.get("path", "/fake/path"),
                s.get("artist", "unknown"),
                s.get("genre", "unknown"),
            )
            for s in songs
        ],
    )


def test_budget_guardrail(con) -> None:
    songs = [{"song_id": f"s{i:03d}", "artist": f"a{(i // 10) + 1}", "genre": "rock"} for i in range(30)]
    _insert_songs(con, songs)

    result = run_stratify(con, {"limit": 9, "song_ids": None}, "aabbccdd00000000")
    tol = _budget_tolerance(9, {})
    assert 1 <= len(result) <= (9 + round(tol * 3))


def test_genre_pass(con) -> None:
    songs = [{"song_id": f"r{i:03d}", "artist": f"rock-{i:03d}", "genre": "rock"} for i in range(20)] + [
        {"song_id": f"p{i:03d}", "artist": f"pop-{i:03d}", "genre": "pop"} for i in range(10)
    ]
    _insert_songs(con, songs)

    result = run_stratify(con, {"limit": 20, "song_ids": None}, "beef0000cafe0000")

    genre_by_sid = {song["song_id"]: song["genre"] for song in songs}
    rock_count = sum(1 for sid in result if genre_by_sid[sid] == "rock")
    pop_count = sum(1 for sid in result if genre_by_sid[sid] == "pop")

    assert rock_count > 0
    assert pop_count > 0
    assert 15 <= len(result) <= 50


def test_genre_pass_preserves_large_genres(con) -> None:
    songs = [{"song_id": f"r{i:03d}", "artist": f"rock-{i:03d}", "genre": "rock"} for i in range(100)] + [
        {"song_id": f"j{i:03d}", "artist": f"jazz-{i:03d}", "genre": "jazz"} for i in range(20)
    ] + [
        {"song_id": f"p{i:03d}", "artist": f"pop-{i:03d}", "genre": "pop"} for i in range(3)
    ]
    _insert_songs(con, songs)

    result = run_stratify(con, {"limit": 80, "song_ids": None}, "c0ffee0000000001")

    genre_by_sid = {song["song_id"]: song["genre"] for song in songs}
    rock_count = sum(1 for sid in result if genre_by_sid[sid] == "rock")
    jazz_count = sum(1 for sid in result if genre_by_sid[sid] == "jazz")
    pop_count = sum(1 for sid in result if genre_by_sid[sid] == "pop")

    assert rock_count >= jazz_count
    assert jazz_count > 0
    assert pop_count >= 0
    assert 60 <= len(result) <= 123


def test_head_score_pass_active(con, tmp_flat_head_cache, monkeypatch) -> None:
    import numpy as np

    import scripts.embedding_research.config as _cfg
    from scripts.embedding_research.cache import flat_heads

    songs = [
        {
            "song_id": f"h{i:03d}",
            "artist": f"artist{i % 5}",
            "genre": f"genre{i % 5}",
        }
        for i in range(50)
    ]
    _insert_songs(con, songs)

    monkeypatch.setattr(_cfg, "HEADS", {"effnet": {"mood_happy": {}}})
    for i in range(50):
        score = i / 50.0
        act = np.array([1.0 - score, score], dtype=np.float32)
        flat_heads.save("effnet", "mood_happy", "mean", "ptc", f"h{i:03d}", act)

    result = run_stratify(con, {"limit": 50, "song_ids": None}, "1234567890abcdef")

    score_by_sid = {f"h{i:03d}": i / 50.0 for i in range(50)}
    represented_deciles = {min(int(score_by_sid[sid] * 10), 9) for sid in result}

    assert len(represented_deciles) >= 8


def test_head_score_pass_absent(con) -> None:
    songs = [{"song_id": f"n{i:03d}", "artist": f"artist{i // 5}", "genre": "unknown"} for i in range(10)]
    _insert_songs(con, songs)

    try:
        result = run_stratify(con, {"limit": 10, "song_ids": None}, "dead0000ffffffff")
    except Exception as exc:  # pragma: no cover - failure path aid
        pytest.fail(f"run_stratify unexpectedly raised {exc!r}")

    inserted_song_ids = {song["song_id"] for song in songs}
    assert isinstance(result, frozenset)
    assert result
    assert result <= inserted_song_ids


def test_determinism(con) -> None:
    songs = [
        {
            "song_id": f"d{i:03d}",
            "artist": f"da{i % 4}",
            "genre": f"dg{i % 4}",
        }
        for i in range(40)
    ]
    _insert_songs(con, songs)

    config_hash = "deadbeef01234567"
    result1 = run_stratify(con, {"limit": 30, "song_ids": None}, config_hash)

    con.execute("DELETE FROM stratified_corpus")

    result2 = run_stratify(con, {"limit": 30, "song_ids": None}, config_hash)

    assert result1 == result2


def test_cache_hit(con) -> None:
    config_hash = "cachetest0000000"
    pre_ids = {f"pre{i}" for i in range(5)}
    con.executemany(
        "INSERT INTO stratified_corpus (config_hash, song_id) VALUES (?, ?)",
        [(config_hash, sid) for sid in pre_ids],
    )

    songs = [{"song_id": f"oth{i:03d}", "artist": "other", "genre": "other"} for i in range(20)]
    _insert_songs(con, songs)

    result = run_stratify(con, {"limit": 20, "song_ids": None}, config_hash)

    assert result == frozenset(pre_ids)


def test_run_stratify_filters_to_requested_song_ids(con) -> None:
    songs = [
        {"song_id": "s001", "artist": "artist-a", "genre": "rock"},
        {"song_id": "s002", "artist": "artist-b", "genre": "pop"},
        {"song_id": "s003", "artist": "artist-c", "genre": "jazz"},
        {"song_id": "s004", "artist": "artist-d", "genre": "rock"},
        {"song_id": "s005", "artist": "artist-e", "genre": "pop"},
        {"song_id": "s006", "artist": "artist-f", "genre": "jazz"},
    ]
    _insert_songs(con, songs)

    requested_song_ids = ["s001", "s002", "s003"]

    result = run_stratify(con, {"limit": 100, "song_ids": requested_song_ids}, "feedface00000001")

    assert result == frozenset(requested_song_ids)
