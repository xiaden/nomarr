# nomarr.services.file_validation

API reference for `nomarr.services.file_validation`.

---

## Functions

### check_already_tagged(path: 'str', namespace: 'str', version_tag_key: 'str', current_version: 'str') -> 'bool'

Check if file already has the correct version tag.

### make_skip_result(path: 'str', skip_reason: 'str') -> 'dict[str, Any]'

Create a standardized result dict for skipped files.

### should_skip_processing(path: 'str', force: 'bool', namespace: 'str', version_tag_key: 'str', tagger_version: 'str') -> 'tuple[bool, str | None]'

Determine if processing should be skipped for this file.

### validate_file_exists(path: 'str') -> 'None'

Check if file exists and is readable.

---
