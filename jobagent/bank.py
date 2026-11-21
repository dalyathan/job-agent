"""The bullet bank: every reusable piece of your past applications, one JSON object per line.

Kinds:
  resume_bullet    one achievement line under a job
  project          one project entry
  summary          a resume headline/summary
  cover_paragraph  one body paragraph from a past cover letter
  cover_letter     a whole past cover letter, kept as a voice example
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from .embed import Embedder

KINDS = {"resume_bullet", "project", "summary", "cover_paragraph", "cover_letter"}


@dataclass
class BankItem:
    id: str
    kind: str
    text: str
    source: str
    section: str = ""  # e.g. employer for a bullet, project name for a project
    tags: list[str] = field(default_factory=list)
    variants: int = 1  # how many past documents contained (nearly) this text

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def make_id(kind: str, text: str) -> str:
    norm = re.sub(r"\W+", " ", text.lower()).strip()
    prefix = {"resume_bullet": "b", "project": "p", "summary": "s", "cover_paragraph": "c", "cover_letter": "L"}[kind]
    return f"{prefix}-{hashlib.sha1(norm.encode()).hexdigest()[:8]}"


def load_bank(path: Path) -> list[BankItem]:
    if not path.exists():
        return []
    items = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("kind") not in KINDS:
            raise ValueError(f"{path}:{n}: unknown kind {d.get('kind')!r}")
        items.append(BankItem(**d))
    return items


def save_bank(path: Path, items: Iterable[BankItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(i.to_json() + "\n" for i in items), encoding="utf-8")
    tmp.replace(path)


# ---------- parsing raw documents ----------

_MD = re.compile(r"\*\*|\*|__|\\(?=[#~\-*])")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADING = re.compile(r"^[A-Z&/ ]{4,}$")
_SECTION_WORDS = re.compile(r"EDUCATION|EXPERIENCE|PROJECT|SKILL|SUMMARY|CERTIFICATION|AWARD|HONOR|LEADERSHIP|PUBLICATION|ACTIVITIES|EMPLOYMENT|WORK", re.I)
_BULLET =re.compile(r"^\s*(?:[-*•▪◦]|\d+\.)\s+(.*)")
_PROJECT = re.compile(r"^([A-Za-z0-9][^:]{2,80}):\s+(.{30,})$")
_SALUTATION = re.compile(r"^(dear|to whom|hello|hi)\b", re.I)
_SIGNOFF = re.compile(r"^(sincerely|best|regards|thank you for|respectfully|warm regards)\b", re.I)


def clean(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = _MD.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_resume(text: str, source: str) -> list[BankItem]:
    items: list[BankItem] = []
    section, context = "", ""
    for raw in text.splitlines():
        line = clean(raw)
        if not line:
            continue
        if _HEADING.match(line):
            if not _SECTION_WORDS.search(line):
                continue  # the name at the top, not a section
            section, context = line.title(), ""
            continue
        m = _BULLET.match(line)
        if m and len(m.group(1)) >= 30:
            items.append(BankItem(make_id("resume_bullet", m.group(1)), "resume_bullet", m.group(1), source, context))
            continue
        p = _PROJECT.match(line)
        if p and (not section or "project" in section.lower()):
            body = f"{p.group(1)}: {p.group(2)}"
            items.append(BankItem(make_id("project", body), "project", body, source, p.group(1)))
            continue
        if not section and len(line) > 80 and not items:
            items.append(BankItem(make_id("summary", line), "summary", line, source))
        elif section.lower() == "experience" or "|" in line or re.search(r"\b(19|20)\d\d\b", line):
            context = line[:120]  # employer / role line that the next bullets belong to
    return items


def parse_cover_letter(text: str, source: str) -> list[BankItem]:
    paras = [clean(p) for p in re.split(r"\n\s*\n", text)]
    body = [p for p in paras if len(p) > 120 and not _SALUTATION.match(p) and not _SIGNOFF.match(p)]
    items = [BankItem(make_id("cover_paragraph", p), "cover_paragraph", p, source) for p in body]
    if body:
        whole = "\n\n".join(body)
        items.append(BankItem(make_id("cover_letter", whole), "cover_letter", whole, source))
    return items


def parse_document(text: str, source: str, kind: str) -> list[BankItem]:
    if kind == "resume":
        return parse_resume(text, source)
    if kind == "cover_letter":
        return parse_cover_letter(text, source)
    raise ValueError("kind must be 'resume' or 'cover_letter'")


def merge(existing: list[BankItem], new: list[BankItem], embedder: Embedder, threshold: float = 0.93) -> tuple[list[BankItem], int]:
    """Add new items, folding near-duplicates (same kind, cosine >= threshold) into the
    existing entry instead of adding another copy. Returns (bank, number added)."""
    bank = list(existing)
    by_id = {i.id: i for i in bank}
    candidates = [n for n in new if n.id not in by_id]
    for n in new:
        if n.id in by_id:
            by_id[n.id].variants += 1
    if not candidates:
        return bank, 0
    vecs = embedder.embed([i.text for i in bank]) if bank else np.zeros((0, 1))
    added = 0
    for n in candidates:
        v = embedder.embed([n.text])[0]
        same = [j for j, b in enumerate(bank) if b.kind == n.kind]
        if same and len(vecs):
            sims = vecs[same] @ v
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                bank[same[j]].variants += 1
                continue
        bank.append(n)
        by_id[n.id] = n
        vecs = np.vstack([vecs, v[None, :]]) if len(vecs) else v[None, :]
        added += 1
    return bank, added
