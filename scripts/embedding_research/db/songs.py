"""Songs table operations and song-level read helpers."""

from __future__ import annotations


def upsert_song(con, song_id: str, path: str, artist: str, album: str, title: str, genre: str = "unknown") -> None:
    con.execute(
        """
        INSERT INTO songs (song_id, path, artist, album, title, genre) VALUES (?,?,?,?,?,?)
        ON CONFLICT (song_id) DO UPDATE SET
            path   = EXCLUDED.path,
            artist = EXCLUDED.artist,
            album  = EXCLUDED.album,
            title  = EXCLUDED.title,
            genre  = EXCLUDED.genre
        """,
        [song_id, path, artist, album, title, genre],
    )


def song_exists(con, song_id: str) -> bool:
    return con.execute("SELECT 1 FROM songs WHERE song_id=?", [song_id]).fetchone() is not None


def load_all_songs(con) -> list[dict]:
    rows = con.execute("SELECT song_id, path, artist, album, title, genre FROM songs").fetchall()
    return [dict(zip(("song_id", "path", "artist", "album", "title", "genre"), r, strict=False)) for r in rows]
