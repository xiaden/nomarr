# nomarr.ml.calibration

API reference for `nomarr.ml.calibration`.

---

## Functions

### apply_minmax_calibration(raw_score: 'float', calibration: 'dict[str, Any]') -> 'float'

Apply min-max scale calibration to a raw model score.

### generate_minmax_calibration(db: 'Database', namespace: 'str' = 'nom') -> 'dict[str, Any]'

Generate min-max scale calibration from library tags.

### save_calibration_sidecars(calibration_data: 'dict[str, Any]', models_dir: 'str', version: 'int' = 1) -> 'dict[str, Any]'

Save calibration data as JSON sidecars next to model files.

---
