#!/usr/bin/env python3
"""Score summary by group."""
import csv
import os

with open("data/responses.csv", newline="") as handle:
    rows = list(csv.DictReader(handle))

os.makedirs("results", exist_ok=True)
with open("results/scored.csv", "w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

for row in rows:
    print(row)

with open("results/summary.csv", "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["group", "n", "mean_score"])
    for group in ("treatment", "control"):
        scores = [int(row["score"]) for row in rows if row["group"] == group]
        writer.writerow([group, len(scores), sum(scores) / len(scores)])
