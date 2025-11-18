# nomarr.workflows.process_file

API reference for `nomarr.workflows.process_file`.

---

## Functions

### process_file_workflow(path: 'str', config: 'ProcessorConfig', db: 'Database | None' = None) -> 'dict[str, Any]'

Process an audio file through the complete tagging pipeline.

### select_tags_for_file(all_tags: 'dict[str, Any]', file_write_mode: 'str') -> 'dict[str, Any]'

Filter tags for file writing based on file_write_mode.

---

## Constants

### ESSENTIA_VERSION

```python
ESSENTIA_VERSION = 'unknown'
```

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
