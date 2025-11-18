# nomarr.interfaces.api.web.config

API reference for `nomarr.interfaces.api.web.config`.

---

## Classes

### ConfigUpdateRequest

Request model for updating configuration values.

---

## Functions

### get_config(_session: dict = Depends(verify_session), db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get current configuration values (user-editable subset).

### update_config(request: nomarr.interfaces.api.web.config.ConfigUpdateRequest, _session: dict = Depends(verify_session), db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Update a configuration value in the database.

---
