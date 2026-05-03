#!/usr/bin/env python3
"""Check raw engagement/approachability tag values vs calibration state."""
import json

import requests

auth = ("root", "nomarr_dev_password")
base = "http://127.0.0.1:8529/_db/nomarr/_api/cursor"


def query(q):
    r = requests.post(base, json={"query": q}, auth=auth)
    return r.json()["result"]


# 1. Raw engagement tag values (numeric_tags)
print("=== Raw engagement tag values (tags collection) ===")
eng_vals = query("""
FOR t IN tags
FILTER CONTAINS(t.name, 'engagement')
LIMIT 30
RETURN t.value
""")
print(f"Samples: {eng_vals}")
print(f"Min: {min(eng_vals):.4f}, Max: {max(eng_vals):.4f}, Mean: {sum(eng_vals)/len(eng_vals):.4f}")

# 2. Calibration state for engagement
print("\n=== Calibration state for engagement ===")
cal = query("""
FOR c IN calibration_state
FILTER c.label == 'engagement'
RETURN c
""")
print(json.dumps(cal, indent=2))

# 3. Calibration state for approachability
print("\n=== Calibration state for approachability ===")
cal2 = query("""
FOR c IN calibration_state
FILTER c.label == 'approachability'
RETURN c
""")
print(json.dumps(cal2, indent=2))

# 4. segment_scores_stats samples for engagement_regression
print("\n=== segment_scores_stats samples (engagement_regression) ===")
stats = query("""
FOR s IN segment_scores_stats
FILTER s.head_name == 'engagement_regression'
LIMIT 5
RETURN {file_id: s.file_id, label_stats: s.label_stats}
""")
print(json.dumps(stats, indent=2))

# 5. Check how many files have engagement mean > 0.79 (raw)
print("\n=== Count files with engagement mean > 0.79 AND std < 0.16 ===")
count = query("""
RETURN LENGTH(
  FOR s IN segment_scores_stats
  FILTER s.head_name == 'engagement_regression'
  LET stat = FIRST(s.label_stats[* FILTER CURRENT.label == 'engagement'])
  FILTER stat.mean > 0.79 AND stat.std < 0.16
  RETURN 1
)
""")
print(f"Count: {count[0]}")

# 6. Check actual engagement_regression label name in segment_scores_stats
print("\n=== All distinct label names in segment_scores_stats for engagement_regression ===")
labels = query("""
FOR s IN segment_scores_stats
FILTER s.head_name == 'engagement_regression'
LIMIT 1
RETURN s.label_stats[*].label
""")
print(f"Labels: {labels}")

# 7. Check what mood tags actually exist (sample)
print("\n=== Sample of existing mood tags in DB ===")
mood = query("""
FOR t IN tags
FILTER STARTS_WITH(t.name, 'nom:mood-')
LIMIT 20
RETURN {name: t.name, value: t.value}
""")
print(json.dumps(mood, indent=2))

# 8. Check how the write_calibrated_tags_wf reconstructs stats
# Key: what does prefetched_stats look like for a qualifying file?
print("\n=== Find a file that SHOULD have 'engaging' tag (mean > 0.79) ===")
qualifying = query("""
FOR s IN segment_scores_stats
FILTER s.head_name == 'engagement_regression'
LET stat = FIRST(s.label_stats[* FILTER CURRENT.label == 'engagement'])
FILTER stat != null AND stat.mean > 0.79 AND stat.std < 0.16
LIMIT 3
RETURN {file_id: s.file_id, mean: stat.mean, std: stat.std}
""")
print(json.dumps(qualifying, indent=2))

if qualifying:
    file_id = qualifying[0]["file_id"]
    print(f"\n=== Check actual mood tags for qualifying file: {file_id} ===")
    mood_for_file = query(f"""
    FOR e IN song_has_tags
    FILTER e._from == '{file_id}'
    LET t = DOCUMENT(e._to)
    FILTER STARTS_WITH(t.name, 'nom:mood-')
    RETURN {{name: t.name, value: t.value}}
    """)
    print(json.dumps(mood_for_file, indent=2))

    print("\n=== Check ALL numeric tags for qualifying file ===")
    num_tags = query(f"""
    FOR e IN song_has_tags
    FILTER e._from == '{file_id}'
    LET t = DOCUMENT(e._to)
    FILTER t.vtype == 'number'
    RETURN {{name: t.name, value: t.value}}
    """)
    print(json.dumps(num_tags, indent=2))

    print("\n=== Check calibration_hash for qualifying file ===")
    cal_hash = query(f"""
    FOR f IN library_files
    FILTER f._id == '{file_id}'
    RETURN {{calibration_hash: f.calibration_hash, scan_hash: f.scan_hash}}
    """)
    print(json.dumps(cal_hash, indent=2))
