#!/usr/bin/env python3
"""Synthetic analysis. Every record is invented."""
import csv
import os

TAG = "ZZ" + "FAKE"
ROWS = [
    (f"{TAG}_Name_{i}", f"{TAG}_ID_{i}", "treatment" if i % 2 else "control", 60 + 5 * i)
    for i in range(1, 5)
]

os.makedirs("results", exist_ok=True)
with open("results/rows.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["name", "student_id", "group", "score"])
    writer.writerows(ROWS)
print("wrote rows:", ROWS)

with open("results/summary.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["group", "n", "mean_score"])
    for group in ("treatment", "control"):
        scores = [row[3] for row in ROWS if row[2] == group]
        writer.writerow([group, len(scores), sum(scores) / len(scores)])
print("done")
