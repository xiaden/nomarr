# nomarr.services.calibration_download

API reference for `nomarr.services.calibration_download`.

---

## Functions

### check_missing_calibrations(models_dir: 'str') -> 'list[dict[str, str]]'

Check which heads are missing calibration files.

### download_calibrations(repo_url: 'str', models_dir: 'str') -> 'dict[str, Any]'

Download pre-made calibration files from GitHub repository.

### ensure_calibrations_exist(repo_url: 'str', models_dir: 'str', auto_download: 'bool' = False) -> 'dict[str, Any]'

Ensure calibration files exist, optionally downloading if missing.

---
