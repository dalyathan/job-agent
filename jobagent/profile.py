"""The profile: your verified facts. Everything the writer says must trace back here or to the bank.

profile.json carries "verified": false until you have checked it. The pipeline refuses
to generate anything from an unverified profile.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProfileNotVerified(RuntimeError):
    pass


@dataclass
class Profile:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path, require_verified: bool = True) -> "Profile":
        if not path.exists():
            raise FileNotFoundError(f"No profile at {path}. Copy examples/profile.example.json and fill it in.")
        p = cls(json.loads(path.read_text(encoding="utf-8")))
        if require_verified and not p.data.get("verified"):
            raise ProfileNotVerified(
                f"{path} is not verified. Check every fact, resolve 'needs_review', then set \"verified\": true."
            )
        return p

    @property
    def needs_review(self) -> list[str]:
        return list(self.data.get("needs_review", []))

    def skills(self) -> set[str]:
        out: set[str] = set()
        for group in self.data.get("skills", {}).values():
            out.update(s.lower() for s in group)
        return out

    def allowed_entities(self) -> set[str]:
        """Employers, schools, titles, certifications and project names, lower-cased."""
        out: set[str] = set()
        for e in self.data.get("experience", []):
            out.update(x.lower() for x in (e.get("employer", ""), e.get("title", ""), e.get("location", "")) if x)
        for e in self.data.get("education", []):
            out.update(x.lower() for x in (e.get("school", ""), e.get("degree", "")) if x)
        for p in self.data.get("projects", []):
            out.add(p.get("name", "").lower())
        out.update(c.lower() for c in self.data.get("certifications", []))
        return {x for x in out if x}

    def text(self) -> str:
        """Every fact as plain text, used as an allowed source for numbers and terms."""
        return json.dumps(self.data, ensure_ascii=False)

    def contact_block(self) -> dict[str, str]:
        return dict(self.data.get("contact", {}))


def numbers_in(text: str) -> set[str]:
    """Normalized numeric claims: 1M, 5K+, 99.9%, 0.76s, 2010, 4+ ..."""
    out = set()
    for m in re.finditer(r"(?<![\w.])~?\$?(\d+(?:[.,]\d+)?)\s*(min\b|s\b|[kKmMbBx](?![a-zA-Z])|%)?\+?", text):
        num = m.group(1).replace(",", "")
        unit = (m.group(2) or "").lower()
        out.add(num + unit)
    return out
