# nomarr.interfaces.api.web.calibration

API reference for `nomarr.interfaces.api.web.calibration`.

---

## Classes

### CalibrationRequest

Request to generate calibration.

---

## Functions

### apply_calibration_to_library() -> dict[str, typing.Any]

Queue all library files for recalibration.

### clear_calibration_queue() -> dict[str, typing.Any]

Clear all pending and completed recalibration jobs.

### generate_calibration(request: nomarr.interfaces.api.web.calibration.CalibrationRequest, db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Generate min-max scale calibration from library tags.

### get_calibration_status() -> dict[str, typing.Any]

Get current recalibration queue status.

---
