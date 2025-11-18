# nomarr.helpers.dataclasses

API reference for `nomarr.helpers.dataclasses`.

---

## Classes

### ProcessorConfig

Configuration for the audio processing pipeline.

**Methods:**

- `__init__(self, models_dir: 'str', min_duration_s: 'int', allow_short: 'bool', batch_size: 'int', overwrite_tags: 'bool', namespace: 'str', version_tag_key: 'str', tagger_version: 'str', calibrate_heads: 'bool', file_write_mode: "Literal['none', 'minimal', 'full']" = 'minimal') -> None`

### TagWriteProfile

Controls what tags are written to media files vs stored only in DB.

**Methods:**

- `__init__(self, file_write_mode: "Literal['none', 'minimal', 'full']" = 'minimal') -> None`

---
