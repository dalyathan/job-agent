"""Turns a draft (JSON) into plain text for the blind reviewer and into .docx files for you."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


# The owner's layout: profile (summary + eligibility), then these sections in this order.
SECTIONS = ("education", "experience", "projects", "skills")
SECTION_TITLES = {"education": "EDUCATION", "experience": "EXPERIENCE", "projects": "PROJECTS", "skills": "SKILLS"}


def section_order(resume: dict[str, Any]) -> list[str]:
    if resume.get("research"):  # older drafts kept research separately; it belongs under Projects
        resume["projects"] = list(resume.pop("research")) + list(resume.get("projects", []))
    return [x for x in SECTIONS if resume.get(x)]


def _job_head(j: dict[str, Any]) -> tuple[str, str]:
    where = ", ".join(x for x in (j.get("employer"), j.get("location")) if x)
    title = j.get("title", "")
    if j.get("type"):
        title = f"{title}, ({j['type']})"
    return f"{where} {j.get('dates', '')}".strip(), title


def resume_text(resume: dict[str, Any], contact: dict[str, str]) -> str:
    out = [contact.get("name", "").upper()]
    line = " · ".join(v for k, v in contact.items() if k != "name" and v)
    if line:
        out.append(line)
    if resume.get("summary"):
        out += [resume["summary"]]
    if resume.get("eligibility"):
        out.append(resume["eligibility"])
    for sec in section_order(resume):
        out += ["", SECTION_TITLES[sec]]
        if sec == "education":
            for e in resume["education"]:
                out.append(" | ".join(x for x in (e.get("school"), e.get("degree"), e.get("dates")) if x))
        elif sec == "experience":
            for j in resume["experience"]:
                head, title = _job_head(j)
                out += [head, title] + [f"- {b['text']}" for b in j.get("bullets", [])]
        elif sec == "projects":
            out += [f"{p['name']}: {p['text']}" for p in resume[sec]]
        elif sec == "skills":
            out += [f"{g}: {', '.join(s)}" for g, s in resume["skills"].items()]
    return "\n".join(out).strip()


def letter_text(letter: dict[str, Any]) -> str:
    parts = [letter.get("greeting", "")] + letter.get("paragraphs", []) + [letter.get("closing", ""), letter.get("signature", "")]
    return "\n\n".join(p for p in parts if p).strip()


def _rule_heading(doc: Document, text: str) -> None:
    """Centered bold heading between two thin horizontal lines."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.bold = True
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    for edge in ("top", "bottom"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "6")
        el.set(qn("w:space"), "1")
        el.set(qn("w:color"), "000000")
        bdr.append(el)
    pPr.append(bdr)


def _para(doc: Document, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    if align is not None:
        p.alignment = align
    return p


def _bullet(doc: Document, text: str) -> None:
    p = _para(doc)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.first_line_indent = Inches(-0.2)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(0.25))
    p.add_run("●\t" + text)


def _base(doc: Document) -> None:
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    st.font.size = Pt(10.5)
    st.paragraph_format.space_after = Pt(0)
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(0.55)
        s.top_margin = s.bottom_margin = Inches(0.45)


def resume_docx(resume: dict[str, Any], contact: dict[str, str], path: Path) -> Path:
    """Single column with real text (what applicant tracking systems parse best), laid out like the
    owner's own resume: centered header, profile summary, ruled section headings, then
    Education, Experience, Projects, Skills."""
    doc = Document()
    _base(doc)
    _para(doc, WD_ALIGN_PARAGRAPH.CENTER).add_run(contact.get("name", "").upper()).font.size = Pt(12)
    labels = {"linkedin": "LinkedIn: ", "github": "GitHub: ", "upwork": "Upwork: "}
    info = " · ".join(labels.get(k, "") + v for k, v in contact.items() if k != "name" and v)
    if info:
        _para(doc, WD_ALIGN_PARAGRAPH.CENTER).add_run(info)
    if resume.get("summary"):
        _para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY).add_run(resume["summary"])
    if resume.get("eligibility"):
        _para(doc, WD_ALIGN_PARAGRAPH.CENTER).add_run(resume["eligibility"])
    for sec in section_order(resume):
        _rule_heading(doc, SECTION_TITLES[sec])
        _DOCX_SECTION[sec](doc, resume)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def _docx_education(doc, resume):
    for e in resume["education"]:
        p = _para(doc)
        p.add_run(" | ".join(x for x in (e.get("school"), e.get("degree")) if x)).bold = True
        if e.get("dates"):
            p.add_run(" | ").bold = True
            d = p.add_run(e["dates"])
            d.bold = d.italic = True


def _docx_experience(doc, resume):
    for j in resume["experience"]:
        head, title = _job_head(j)
        p = _para(doc)
        p.paragraph_format.space_before = Pt(3)
        p.add_run(head).bold = True
        _para(doc).add_run(title).bold = True
        for b in j.get("bullets", []):
            _bullet(doc, b["text"])


def _docx_named(key):
    def render(doc, resume):
        for pr in resume[key]:
            p = _para(doc)
            p.add_run(f"{pr['name']}: ").bold = True
            p.add_run(pr["text"])
    return render


def _docx_skills(doc, resume):
    for g, s in resume["skills"].items():
        p = _para(doc)
        p.add_run(f"{g}: ").bold = True
        p.add_run(", ".join(s))


_DOCX_SECTION = {"education": _docx_education, "experience": _docx_experience, "projects": _docx_named("projects"), "skills": _docx_skills}


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
