# nomarr.services.config

API reference for `nomarr.services.config`.

---

## Classes

### ConfigService

Service for loading and caching application configuration.

**Methods:**

- `__init__(self) -> 'None'`
- `get(self, key_path: 'str', default: 'Any' = None) -> 'Any'`
- `get_config(self, force_reload: 'bool' = False) -> 'dict[str, Any]'`
- `make_processor_config(self) -> 'ProcessorConfig'`
- `reload(self) -> 'dict[str, Any]'`

---

## Constants

### INTERNAL_ALLOW_SHORT

```python
INTERNAL_ALLOW_SHORT = False
```

### INTERNAL_BATCH_SIZE

```python
INTERNAL_BATCH_SIZE = 11
```

### INTERNAL_BLOCKING_MODE

```python
INTERNAL_BLOCKING_MODE = True
```

### INTERNAL_BLOCKING_TIMEOUT

```python
INTERNAL_BLOCKING_TIMEOUT = 3600
```

### INTERNAL_CALIBRATION_APD_THRESHOLD

```python
INTERNAL_CALIBRATION_APD_THRESHOLD = 0.01
```

### INTERNAL_CALIBRATION_AUTO_RUN

```python
INTERNAL_CALIBRATION_AUTO_RUN = False
```

### INTERNAL_CALIBRATION_CHECK_INTERVAL

```python
INTERNAL_CALIBRATION_CHECK_INTERVAL = 604800
```

### INTERNAL_CALIBRATION_IQR_THRESHOLD

```python
INTERNAL_CALIBRATION_IQR_THRESHOLD = 0.1
```

### INTERNAL_CALIBRATION_JSD_THRESHOLD

```python
INTERNAL_CALIBRATION_JSD_THRESHOLD = 0.1
```

### INTERNAL_CALIBRATION_MEDIAN_THRESHOLD

```python
INTERNAL_CALIBRATION_MEDIAN_THRESHOLD = 0.05
```

### INTERNAL_CALIBRATION_MIN_FILES

```python
INTERNAL_CALIBRATION_MIN_FILES = 100
```

### INTERNAL_CALIBRATION_QUALITY_THRESHOLD

```python
INTERNAL_CALIBRATION_QUALITY_THRESHOLD = 0.85
```

### INTERNAL_CALIBRATION_SRD_THRESHOLD

```python
INTERNAL_CALIBRATION_SRD_THRESHOLD = 0.05
```

### INTERNAL_HOST

```python
INTERNAL_HOST = '0.0.0.0'
```

### INTERNAL_LIBRARY_SCAN_POLL_INTERVAL

```python
INTERNAL_LIBRARY_SCAN_POLL_INTERVAL = 10
```

### INTERNAL_MIN_DURATION_S

```python
INTERNAL_MIN_DURATION_S = 60
```

### INTERNAL_NAMESPACE

```python
INTERNAL_NAMESPACE = 'nom'
```

### INTERNAL_POLL_INTERVAL

```python
INTERNAL_POLL_INTERVAL = 2
```

### INTERNAL_PORT

```python
INTERNAL_PORT = 8356
```

### INTERNAL_VERSION_TAG

```python
INTERNAL_VERSION_TAG = 'nom_version'
```

### INTERNAL_WORKER_ENABLED

```python
INTERNAL_WORKER_ENABLED = True
```

### TAGGER_VERSION

```python
TAGGER_VERSION = '0.1.2'
```

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
