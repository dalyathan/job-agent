"""Turns a draft (JSON) into plain text for the blind reviewer and into .docx files for you."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


SECTIONS = ("education", "experience", "projects", "skills")


def section_order(resume: dict[str, Any]) -> list[str]:
    """The writer may reorder sections (e.g. projects first for an AI role); default is SECTIONS."""
    order = [x for x in resume.get("section_order", []) if x in SECTIONS]
    order += [x for x in SECTIONS if x not in order]
    return [x for x in order if resume.get(x)]


def resume_text(resume: dict[str, Any], contact: dict[str, str]) -> str:
    out = [contact.get("name", "").upper()]
    line = " · ".join(v for k, v in contact.items() if k != "name" and v)
    if line:
        out.append(line)
    if resume.get("summary"):
        out += ["", resume["summary"]]
    if resume.get("eligibility"):
        out.append(resume["eligibility"])
    for sec in section_order(resume):
        if sec == "education":
            out += ["", "EDUCATION"]
            for e in resume["education"]:
                out.append(" | ".join(x for x in (e.get("school"), e.get("degree"), e.get("dates")) if x))
        elif sec == "experience":
            out += ["", "EXPERIENCE"]
            for j in resume["experience"]:
                out.append(" | ".join(x for x in (j.get("employer"), j.get("title"), j.get("location"), j.get("dates")) if x))
                out += [f"- {b['text']}" for b in j.get("bullets", [])]
        elif sec == "projects":
            out += ["", "PROJECTS"]
            out += [f"- {p['name']}: {p['text']}" for p in resume["projects"]]
        elif sec == "skills":
            out += ["", "SKILLS"]
            out += [f"{g}: {', '.join(s)}" for g, s in resume["skills"].items()]
    return "\n".join(out).strip()


def letter_text(letter: dict[str, Any]) -> str:
    parts = [letter.get("greeting", "")] + letter.get("paragraphs", []) + [letter.get("closing", ""), letter.get("signature", "")]
    return "\n\n".join(p for p in parts if p).strip()


def _heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(11)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)


def _base(doc: Document) -> None:
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Pt(42)


def resume_docx(resume: dict[str, Any], contact: dict[str, str], path: Path) -> Path:
    """Single column, standard headings, real text: what applicant tracking systems parse best."""
    doc = Document()
    _base(doc)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(contact.get("name", "").upper())
    r.bold = True
    r.font.size = Pt(16)
    info = " · ".join(v for k, v in contact.items() if k != "name" and v)
    if info:
        q = doc.add_paragraph(info)
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if resume.get("summary"):
        doc.add_paragraph(resume["summary"])
    if resume.get("eligibility"):
        doc.add_paragraph().add_run(resume["eligibility"]).italic = True
    for sec in section_order(resume):
        _DOCX_SECTION[sec](doc, resume)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def _docx_education(doc, resume):
    _heading(doc, "Education")
    for e in resume["education"]:
        q = doc.add_paragraph()
        q.add_run(e.get("school", "")).bold = True
        rest = " | ".join(x for x in (e.get("degree"), e.get("dates")) if x)
        if rest:
            q.add_run(f" | {rest}")


def _docx_experience(doc, resume):
    _heading(doc, "Experience")
    for j in resume["experience"]:
        q = doc.add_paragraph()
        q.add_run(j.get("employer", "")).bold = True
        rest = " | ".join(x for x in (j.get("title"), j.get("location"), j.get("dates")) if x)
        if rest:
            q.add_run(f" | {rest}")
        for b in j.get("bullets", []):
            doc.add_paragraph(b["text"], style="List Bullet")


def _docx_projects(doc, resume):
    _heading(doc, "Projects")
    for pr in resume["projects"]:
        q = doc.add_paragraph(style="List Bullet")
        q.add_run(f"{pr['name']}: ").bold = True
        q.add_run(pr["text"])


def _docx_skills(doc, resume):
    _heading(doc, "Skills")
    for g, s in resume["skills"].items():
        q = doc.add_paragraph()
        q.add_run(f"{g}: ").bold = True
        q.add_run(", ".join(s))


_DOCX_SECTION = {"education": _docx_education, "experience": _docx_experience,
                 "projects": _docx_projects, "skills": _docx_skills}


def letter_docx(letter: dict[str, Any], contact: dict[str, str], path: Path) -> Path:
    doc = Document()
    _base(doc)
    doc.styles["Normal"].font.size = Pt(11)
    head = doc.add_paragraph()
    head.add_run(contact.get("name", "")).bold = True
    for k in ("email", "phone", "location"):
        if contact.get(k):
            head.add_run("\n" + contact[k])
    for part in [letter.get("greeting", "")] + letter.get("paragraphs", []) + [letter.get("closing", ""), letter.get("signature", "")]:
        if part:
            doc.add_paragraph(part)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
