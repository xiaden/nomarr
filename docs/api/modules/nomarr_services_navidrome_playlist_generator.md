# nomarr.services.navidrome.playlist_generator

API reference for `nomarr.services.navidrome.playlist_generator`.

---

## Classes

### PlaylistGenerator

Generates Navidrome Smart Playlists (.nsp) from query syntax.

**Methods:**

- `__init__(self, db_path: str, namespace: str = 'nom')`
- `generate_nsp(self, query: str, playlist_name: str = 'Playlist', comment: str = '', sort: str | None = None, limit: int | None = None) -> str`
- `generate_playlist(self, query: str, limit: int | None = None, order_by: str | None = None) -> list[dict[str, typing.Any]]`
- `parse_query_to_nsp(self, query: str) -> dict[str, typing.Any]`
- `parse_query_to_sql(self, query: str) -> tuple[str, list[typing.Any]]`
- `preview_playlist(self, query: str, preview_limit: int = 10) -> dict[str, typing.Any]`

### PlaylistQueryError

Raised when a playlist query is invalid.

---

## Functions

### generate_nsp_playlist(db_path: str, query: str, playlist_name: str = 'Playlist', comment: str = '', namespace: str = 'nom', sort: str | None = None, limit: int | None = None) -> str

Generate Navidrome Smart Playlist (.nsp) from query.

### preview_playlist_query(db_path: str, query: str, namespace: str = 'nom', preview_limit: int = 10) -> dict[str, typing.Any]

Preview a Smart Playlist query.

---
