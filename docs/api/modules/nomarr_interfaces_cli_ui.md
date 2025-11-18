# nomarr.interfaces.cli.ui

API reference for `nomarr.interfaces.cli.ui`.

---

## Classes

### InfoPanel

Simple panel for displaying status/info without progress tracking.

**Methods:**

- `show(title: 'str', content: 'str', border_style: 'str' = 'cyan')`
- `show_multiple(panels: 'list[dict[str, str]]')`

### ProgressDisplay

Multi-panel layout with progress bars, recent activity messages, and errors.

**Methods:**

- `__init__(self, total_items: 'int', item_unit: 'str' = 'items')`
- `add_error(self, error: 'str')`
- `add_message(self, message: 'str')`
- `advance_overall_heads(self, amount: 'int' = 1)`
- `clear_tags(self)`
- `mark_file_done(self)`
- `reset_item(self, total: 'int')`
- `set_current_head(self, head_name: 'str')`
- `start_heads(self, total_files: 'int', heads_per_file: 'int')`
- `stop(self)`
- `update_item_progress(self, completed: 'int', total: 'int | None' = None)`
- `update_tags(self, tags: 'dict')`

### TableDisplay

Formatted tables for lists (jobs, tags, etc).

**Methods:**

- `show_jobs(jobs: 'list[Any]', title: 'str' = 'Jobs')`
- `show_summary(title: 'str', data: 'dict[str, Any]', border_style: 'str' = 'cyan')`
- `show_tags(tags: 'dict[str, Any]', file_path: 'str')`

### UILogHandler

Logging handler that forwards WARNING/ERROR records to the active

**Methods:**

- `emit(self, record: 'logging.LogRecord') -> 'None'`

### WorkerPoolDisplay

Display for parallel worker processing with per-worker progress bars.

**Methods:**

- `__init__(self, total_files: 'int', worker_count: 'int' = 4)`
- `mark_file_complete(self, filename: 'str', elapsed: 'float', tags_written: 'int')`
- `mark_file_failed(self, filename: 'str', error: 'str')`
- `start(self)`
- `stop(self)`
- `update_worker(self, worker_id: 'int', status: 'str', progress: 'int' = 0)`

---

## Functions

### attach_display_logger(display: 'ProgressDisplay', level: 'int' = 30) -> 'None'

Attach a logging handler so warnings/errors appear in the CLI panels.

### detach_display_logger() -> 'None'

Detach UI logging handler and clear active display reference.

### print_error(message: 'str')

Print an error message.

### print_info(message: 'str')

Print an info message.

### print_success(message: 'str')

Print a success message.

### print_warning(message: 'str')

Print a warning message.

### show_spinner(message: 'str', task_fn: 'Callable', *args, **kwargs)

Show a spinner while executing a task.

---

## Constants

### COLOR_DONE

```python
COLOR_DONE = 'green'
```

### COLOR_ERROR

```python
COLOR_ERROR = 'red'
```

### COLOR_INFO

```python
COLOR_INFO = 'cyan'
```

### COLOR_PENDING

```python
COLOR_PENDING = 'yellow'
```

### COLOR_RUNNING

```python
COLOR_RUNNING = 'blue'
```

### COLOR_SUCCESS

```python
COLOR_SUCCESS = 'green'
```

### COLOR_WARNING

```python
COLOR_WARNING = 'yellow'
```

---
