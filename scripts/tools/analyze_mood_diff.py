"""Analyze mood_compare_full.txt to count +db / -db label occurrences."""

import re
from collections import defaultdict

path = r"d:\Github\nomarr\scripts\outputs\mood_compare_full.txt"

db_counts: dict[str, int] = defaultdict(int)
file_counts: dict[str, int] = defaultdict(int)

with open(path, encoding="utf-8") as f:
    for line in f:
        plus = re.search(r"\+db: ([^|]+)", line)
        minus = re.search(r"-db: ([^|]+)", line)
        if plus:
            for label in [l.strip() for l in plus.group(1).split(",") if l.strip()]:
                db_counts[label] += 1
        if minus:
            for label in [l.strip() for l in minus.group(1).split(",") if l.strip()]:
                file_counts[label] += 1

all_labels = sorted(set(db_counts) | set(file_counts))

print("=== Labels ONLY in +db (new ONNX heads, never in TF on-disk) ===")
only_db = sorted([(db_counts[l], l) for l in all_labels if l not in file_counts], reverse=True)
for count, label in only_db:
    print(f"  {count:6d}  {label}")

print()
print("=== Labels ONLY in -db (old TF on-disk, dropped/absent in ONNX) ===")
only_file = sorted([(file_counts[l], l) for l in all_labels if l not in db_counts], reverse=True)
for count, label in only_file:
    print(f"  {count:6d}  {label}")

print()
print("=== Labels in BOTH sides (present in both pipelines, threshold-shifted) ===")
both = sorted(
    [(db_counts[l], file_counts[l], l) for l in all_labels if l in db_counts and l in file_counts],
    reverse=True,
)
print(f"  {'Label':<35} {'in DB (+db)':>12} {'on disk (-db)':>14}")
for db_c, f_c, label in both:
    print(f"  {label:<35} {db_c:>12} {f_c:>14}")
