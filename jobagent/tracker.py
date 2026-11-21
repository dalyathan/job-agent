"""A CSV tracker, one row per job. Opens in Excel, Numbers or Google Sheets."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

FIELDS = ["job_id", "company", "title", "location", "url", "source", "added", "status",
          "best_score", "rounds", "resume_file", "letter_file", "applied_on", "response", "notes"]


def upsert(path: Path, row: dict[str, str]) -> None:
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    for r in rows:
        if r["job_id"] == row["job_id"]:
            r.update({k: v for k, v in row.items() if v not in (None, "")})
            break
    else:
        rows.append({k: row.get(k, "") for k in FIELDS} | {"added": row.get("added") or date.today().isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
