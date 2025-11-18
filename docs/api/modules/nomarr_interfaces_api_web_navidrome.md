# nomarr.interfaces.api.web.navidrome

API reference for `nomarr.interfaces.api.web.navidrome`.

---

## Functions

### web_navidrome_config(db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Generate Navidrome TOML configuration (web UI proxy).

### web_navidrome_playlist_generate(request: dict) -> dict[str, typing.Any]

Generate Navidrome Smart Playlist (.nsp) from query.

### web_navidrome_playlist_preview(request: dict) -> dict[str, typing.Any]

Preview Smart Playlist query results.

### web_navidrome_preview(db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get preview of tags for Navidrome config generation (web UI proxy).

### web_navidrome_templates_generate() -> dict[str, typing.Any]

Generate all playlist templates as a batch.

### web_navidrome_templates_list() -> dict[str, typing.Any]

Get list of all available playlist templates.

---
