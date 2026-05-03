"""Diagnose whether apply_calibration_wf actually updated the DB."""

# mypy: ignore-errors

import sys

sys.path.insert(0, "/app")
from nomarr.helpers.config_helper import load_config
from nomarr.persistence.db import Database

cfg = load_config("/app/config/config.yaml")
db = Database(cfg)

# Count files with calibration_hash
total = db.conn.aql.execute("RETURN LENGTH(library_files)").next()
calibrated = db.conn.aql.execute(
    "RETURN LENGTH(FOR f IN library_files FILTER f.calibration_hash != null RETURN 1)"
).next()
print(f"Total files:            {total}")
print(f"With calibration_hash:  {calibrated}")

# Check calibration version
ver_doc = db.meta.key.get("calibration_version")
last_run_doc = db.meta.key.get("calibration_last_run")
ver = None if ver_doc is None else ver_doc.get("value")
last_run = None if last_run_doc is None else last_run_doc.get("value")
print(f"calibration_version:    {ver}")
print(f"calibration_last_run:   {last_run}")

# Print calibration_state summary
states = list(
    db.conn.aql.execute("FOR c IN calibration_state RETURN {label: c.label, p5: c.p5, p95: c.p95, n: c.sample_count}")
)
print(f"\ncalibration_state entries: {len(states)}")
for s in sorted(states, key=lambda x: x["label"]):
    print(f"  {s['label']:<25} p5={s['p5']:.4f}  p95={s['p95']:.4f}  n={s['n']}")

# Sample a file with calibration_hash and check its mood tags AND segment_scores_stats
print("\n--- Sample calibrated file ---")
sample = list(db.conn.aql.execute("FOR f IN library_files FILTER f.calibration_hash != null LIMIT 1 RETURN f"))
if sample:
    f = sample[0]
    fid = f["_id"]
    print(f"path: {f.get('path', '?')}")
    print(f"calibration_hash: {f.get('calibration_hash', '?')}")

    mood_tags = list(
        db.conn.aql.execute(
            "FOR e IN song_has_tags FILTER e._from == @fid "
            "LET t = DOCUMENT(e._to) "
            'FILTER STARTS_WITH(t.name, "nom:mood-") '
            "RETURN {name: t.name, val: t.value}",
            bind_vars={"fid": fid},
        )
    )
    print(f"Mood tags ({len(mood_tags)}):")
    for t in sorted(mood_tags, key=lambda x: x["rel"]):
        print(f"  {t['rel']}: {t['val']}")

    # Check segment_scores_stats
    stats = list(
        db.conn.aql.execute(
            "FOR s IN segment_scores_stats FILTER s.file_id == @fid RETURN {head: s.head_name, labels: s.label_stats[*].label}",
            bind_vars={"fid": fid},
        )
    )
    print(f"\nsegment_scores_stats heads ({len(stats)}):")
    for s in sorted(stats, key=lambda x: x["head"]):
        print(f"  {s['head']}: {s['labels']}")
else:
    print("No calibrated files found!")

# Also check a file WITHOUT calibration_hash
print("\n--- Sample UN-calibrated file ---")
sample2 = list(
    db.conn.aql.execute(
        "FOR f IN library_files FILTER f.calibration_hash == null "
        "LET has_mood = (FOR e IN song_has_tags FILTER e._from == f._id "
        '  LET t = DOCUMENT(e._to) FILTER STARTS_WITH(t.name, "nom:mood-") LIMIT 1 RETURN 1) '
        "FILTER LENGTH(has_mood) > 0 LIMIT 1 RETURN f"
    )
)
if sample2:
    f2 = sample2[0]
    fid2 = f2["_id"]
    print(f"path: {f2.get('path', '?')}")
    mood_tags2 = list(
        db.conn.aql.execute(
            "FOR e IN song_has_tags FILTER e._from == @fid "
            "LET t = DOCUMENT(e._to) "
            'FILTER STARTS_WITH(t.name, "nom:mood-") '
            "RETURN {name: t.name, val: t.value}",
            bind_vars={"fid": fid2},
        )
    )
    print(f"Mood tags ({len(mood_tags2)}):")
    for t in sorted(mood_tags2, key=lambda x: x["rel"]):
        print(f"  {t['rel']}: {t['val']}")
else:
    print("All files have calibration_hash (or no untagged files found)")
