"""Job postings: intake, de-duplication, and per-job folders.

Each job lives in jobs/<job_id>/:
  job.json                 the posting (company, title, location, url, full text)
  iter-N/draft.json        the writer's draft for round N
  iter-N/factcheck.json    the fact-check report
  iter-N/review.json       the blind reviewer's score and critique
  state.json               round counter and best score, for the orchestrator only
  final/                   the .docx files you review
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|the)\b\.?", " ", s)
    s = re.sub(r"\b(sr|senior|jr|junior)\b\.?", lambda m: m.group(1)[0] + "r", s)
    s = re.sub(r"\(.*?\)|[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def job_id(company: str, title: str, location: str = "") -> str:
    """Same company + title + location = same job, whichever site or URL it came from."""
    key = "|".join(_norm(x) for x in (company, title, location.split(",")[0]))
    slug = re.sub(r"[^a-z0-9]+", "-", f"{_norm(company)}-{_norm(title)}")[:48].strip("-")
    return f"{slug}-{hashlib.sha1(key.encode()).hexdigest()[:6]}"


@dataclass
class Job:
    company: str
    title: str
    text: str
    location: str = ""
    url: str = ""
    source: str = "handshake"
    deadline: str = ""
    added: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = job_id(self.company, self.title, self.location)


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def dir(self, jid: str) -> Path:
        return self.root / jid

    def exists(self, jid: str) -> bool:
        return (self.dir(jid) / "job.json").exists()

    def add(self, job: Job) -> bool:
        """Returns False if this job was already seen (de-duplicated)."""
        if len(job.text.strip()) < 200:
            raise ValueError("Job text is too short; capture the full description, not a teaser.")
        if self.exists(job.id):
            return False
        d = self.dir(job.id)
        d.mkdir(parents=True)
        (d / "job.json").write_text(json.dumps(asdict(job), indent=1, ensure_ascii=False), encoding="utf-8")
        return True

    def get(self, jid: str) -> Job:
        return Job(**json.loads((self.dir(jid) / "job.json").read_text(encoding="utf-8")))

    def state(self, jid: str) -> dict[str, Any]:
        p = self.dir(jid) / "state.json"
        return json.loads(p.read_text()) if p.exists() else {"status": "new", "iterations": [], "best": None}

    def save_state(self, jid: str, st: dict[str, Any]) -> None:
        (self.dir(jid) / "state.json").write_text(json.dumps(st, indent=1))

    def iter_dir(self, jid: str, n: int) -> Path:
        d = self.dir(jid) / f"iter-{n}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def pending(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if (p / "job.json").exists() and self.state(p.name)["status"] in {"new", "in_progress"})
