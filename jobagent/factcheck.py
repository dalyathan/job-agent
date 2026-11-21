"""Deterministic fact check of a draft against your verified material.

A blind reviewer can't tell whether a claim is true, so the cheapest way to raise
its score is to exaggerate. This check runs before every review and blocks that.

Errors (the draft is rejected):
  - a resume line cites no bank id, or an id that doesn't exist
  - a number that appears in none of the line's cited sources or the profile
  - a skill or technology that appears nowhere in your profile or bank
  - an employer or job title that isn't in the profile
Warnings (shown to you, not blocking):
  - a line that has drifted far from the wording of its sources
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from .bank import BankItem
from .profile import Profile, numbers_in

# Terms that, if they appear in a draft, must also appear somewhere in your own material.
TECH_TERMS = [
    "python", "java", "javascript", "typescript", "c++", "c#", ".net", "go", "golang", "rust", "scala", "kotlin",
    "swift", "ruby", "php", "r", "matlab", "sql", "nosql", "dart", "bash",
    "react", "angular", "vue", "next.js", "node.js", "express", "django", "flask", "fastapi", "spring", "remix",
    "flutter", "graphql", "rest", "grpc", "vendure",
    "aws", "azure", "gcp", "google cloud", "digitalocean", "cloudflare", "kubernetes", "docker", "terraform",
    "ansible", "jenkins", "github actions", "gitlab ci", "ci/cd", "linux",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch", "kafka", "rabbitmq", "snowflake",
    "databricks", "bigquery", "airflow", "dbt", "spark", "hadoop", "mllib",
    "pytorch", "tensorflow", "keras", "jax", "scikit-learn", "sklearn", "xgboost", "hugging face", "transformers",
    "langchain", "llamaindex", "openai", "claude", "llm", "rag", "vector database", "cuda", "opencv",
    "pandas", "numpy", "tableau", "power bi", "excel", "shap", "lime", "lda",
    "splunk", "wireshark", "siem", "penetration testing", "simspace",
    "salesforce", "sap", "appian", "servicenow", "jira", "agile", "scrum",
]
_TERM_RE = {t: re.compile(r"(?<![\w.+#])" + re.escape(t) + r"(?![\w+#])", re.I) for t in TECH_TERMS}
# One-letter or ambiguous terms only count when written exactly like this.
_CASE_SENSITIVE = {"r": re.compile(r"(?<![\w])R(?![\w&])"), "go": re.compile(r"(?<![\w])Go(?![\w-])"),
                   "rest": re.compile(r"(?<![\w])REST(?![\w])"), "lime": re.compile(r"(?<![\w])LIME(?![\w])"),
                   "excel": re.compile(r"(?<![\w])Excel(?![\w])"), "spring": re.compile(r"(?<![\w])Spring(?! (?:20|19)\d\d)(?![\w])")}


# A sentence that admits a gap ("I have not used X", "X is something I want to learn") is honest, not a claim.
_GAP = re.compile(r"\b(have not|haven't|has not|not yet|never (?:used|worked)|no (?:professional )?experience|"
                  r"new to|want to learn|eager to learn|plan to learn|hope to learn|would learn|learning)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def terms_in(text: str) -> set[str]:
    found = set()
    for t, rx in _TERM_RE.items():
        rx = _CASE_SENSITIVE.get(t, rx)
        if rx.search(text):
            found.add(t)
    return found


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _similarity(a: str, b: str) -> float:
    wa, wb = re.findall(r"\w+", a.lower()), re.findall(r"\w+", b.lower())
    return difflib.SequenceMatcher(None, wa, wb).ratio() if wa and wb else 0.0


def _resume_lines(resume: dict[str, Any]):
    if resume.get("summary"):
        yield "summary", resume["summary"], resume.get("summary_sources", [])
    for job in resume.get("experience", []):
        for b in job.get("bullets", []):
            yield f"{job.get('employer', '?')} bullet", b.get("text", ""), b.get("sources", [])
    for p in resume.get("projects", []):
        yield f"project {p.get('name', '?')}", f"{p.get('name', '')}: {p.get('text', '')}", p.get("sources", [])


def check(draft: dict[str, Any], profile: Profile, bank: list[BankItem], job_text: str = "") -> Report:
    r = Report()
    by_id = {b.id: b for b in bank}
    profile_text = profile.text()
    profile_nums = numbers_in(profile_text)
    own_text = profile_text + "\n" + "\n".join(b.text for b in bank)
    own_terms = terms_in(own_text) | profile.skills()
    resume = draft.get("resume", {})

    # Employers and titles must be real.
    allowed = profile.allowed_entities()
    for job in resume.get("experience", []):
        for key in ("employer", "title"):
            v = (job.get(key) or "").strip().lower()
            if v and v not in allowed:
                r.errors.append(f"{key} {job.get(key)!r} is not in your profile")

    # Every resume line must cite real sources, and its numbers must come from them.
    for where, text, sources in _resume_lines(resume):
        if not sources:
            r.errors.append(f"{where}: cites no source bullet: {text[:80]!r}")
            continue
        bad = [s for s in sources if s != "profile" and s not in by_id]
        if bad:
            r.errors.append(f"{where}: unknown source ids {bad}")
            continue
        src_text = " ".join(by_id[s].text for s in sources if s in by_id)
        extra = numbers_in(text) - numbers_in(src_text) - profile_nums
        if extra:
            r.errors.append(f"{where}: numbers not in its sources or profile: {sorted(extra)}")
        if src_text and _similarity(text, src_text) < 0.3:
            r.warnings.append(f"{where}: reworded heavily from its sources; check it says the same thing")

    # Skills section: only skills you have.
    listed = [s for group in resume.get("skills", {}).values() for s in group]
    for s in listed:
        if s.lower() not in own_terms and s.lower() not in own_text.lower():
            r.errors.append(f"skill {s!r} is not in your profile or past material")

    # Technology terms anywhere in the draft must appear in your own material.
    letter = draft.get("cover_letter", {})
    letter_text = "\n".join([letter.get("greeting", "")] + letter.get("paragraphs", []) + [letter.get("closing", "")])
    resume_text = "\n".join(t for _, t, _ in _resume_lines(resume)) + "\n" + "\n".join(listed)
    for t in sorted(terms_in(resume_text) - own_terms):
        hint = " (the job asks for it; mention it as a gap to learn, not a skill)" if t in terms_in(job_text) else ""
        r.errors.append(f"resume claims {t!r}, which appears nowhere in your material{hint}")
    for sentence in _sentences(letter_text):
        for t in sorted(terms_in(sentence) - own_terms):
            if _GAP.search(sentence):
                r.warnings.append(f"cover letter names {t!r} as a gap: {sentence[:100]!r}")
            else:
                hint = " (the job asks for it; mention it as a gap to learn, not a skill)" if t in terms_in(job_text) else ""
                r.errors.append(f"cover letter claims {t!r}, which appears nowhere in your material{hint}")

    # Cover letter numbers: from your material, or quoted from the job posting.
    allowed_nums = profile_nums | numbers_in(own_text) | numbers_in(job_text)
    extra = numbers_in(letter_text) - allowed_nums
    if extra:
        r.errors.append(f"cover letter numbers not in your material or the posting: {sorted(extra)}")

    if not letter.get("paragraphs"):
        r.errors.append("cover letter has no paragraphs")
    return r
