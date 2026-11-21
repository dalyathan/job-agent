"""Builds the writer's context packet for one job: the most relevant bullets, projects
and past cover-letter paragraphs (vector search), plus the verified profile and
2-3 whole past letters as voice examples."""

from __future__ import annotations

import re
from typing import Any

from .bank import BankItem
from .embed import Embedder
from .profile import Profile
from .store import VectorStore


def _employer_key(s: str) -> str:
    """'Freelancer on Upwork, Remote May 2023' and 'Upwork' -> 'upwork'; first distinctive word."""
    words = [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP]
    return words[0] if words else ""


_STOP = {"freelancer", "freelance", "on", "the", "at", "university", "of", "inc", "llc", "s", "c", "plc"}


def build_context(
    job_text: str,
    bank: list[BankItem],
    store: VectorStore,
    embedder: Embedder,
    profile: Profile,
    top_k: int = 14,
    voice_examples: int = 3,
    per_employer: int = 3,
) -> dict[str, Any]:
    if store.embedder_name != embedder.name:
        raise RuntimeError(f"Index was built with {store.embedder_name}, not {embedder.name}. Run: job-agent build-kb")
    by_id = {b.id: b for b in bank}
    q = embedder.embed([job_text])[0]

    def kind_is(*kinds: str):
        return lambda i: i in by_id and by_id[i].kind in kinds

    def pack(hits):
        return [
            {"id": i, "kind": by_id[i].kind, "section": by_id[i].section, "text": by_id[i].text, "score": round(s, 3)}
            for i, s in hits
        ]

    resume_hits = store.search(q, top_k, keep=kind_is("resume_bullet", "project", "summary"))
    # Every job on the resume needs its own best bullets, even if they rank below the top-k overall;
    # otherwise the writer is left with an employer and only vague lines to put under it.
    have = {i for i, _ in resume_hits}
    all_ranked = store.search(q, len(store.ids), keep=kind_is("resume_bullet"), diversity=0.0)
    for job in profile.data.get("experience", []):
        key = _employer_key(job.get("employer", ""))
        mine = [(i, s) for i, s in all_ranked if key and key in _employer_key(by_id[i].section)]
        resume_hits += [(i, s) for i, s in mine[:per_employer] if i not in have]
        have.update(i for i, _ in mine[:per_employer])
    cover_hits = store.search(q, max(4, top_k // 2), keep=kind_is("cover_paragraph"))
    letters = store.search(q, voice_examples, keep=kind_is("cover_letter"), diversity=0.5)

    return {
        "job": job_text,
        "profile": profile.data,
        "resume_material": pack(resume_hits),
        "cover_letter_material": pack(cover_hits),
        "voice_examples": [by_id[i].text for i, _ in letters],
    }
