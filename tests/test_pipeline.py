import json

import pytest

from jobagent import bank as bankmod
from jobagent import factcheck, loop
from jobagent.config import Config
from jobagent.embed import HashingEmbedder
from jobagent.jobs import Job, JobStore, job_id
from jobagent.profile import Profile, ProfileNotVerified, numbers_in
from jobagent.retrieve import build_context
from jobagent.store import VectorStore

RESUME = """ALEX RIVERA
Software engineer (MS, Dec 2027) building data pipelines and payment systems, with 3 years of experience shipping them.

EXPERIENCE
Example Corp | Software Engineer | Jan 2023 - Aug 2025
- Automated CI/CD pipelines with GitHub Actions, cutting deploy time from 10 to 2.4 min.
- Integrated a mobile-money API handling 15K+ payments and cutting checkout failures by 12%.

PROJECTS
Basket Mining: mined ~1M transactions with a distributed SON algorithm in Spark, ~1.4x faster than Apriori.
mHealth Reviews: topic modeling with LDA on 6,000+ app reviews to find the biggest user complaints.
Risk Stress Testing: backtested VaR and Expected Shortfall models on a portfolio from 2010 to 2025.
"""

LETTER = """Dear Team,

Your posting says data work here is embedded in fraud prevention. That is the kind of system I want to build, with the controls that make it trustworthy in production.

Before graduate school I spent years shipping payment integrations, including one that handled more than 15,000 payments for a ticketing app, and it taught me how small failures add up.

Sincerely,
Alex"""

PROFILE = {
    "verified": True,
    "contact": {"name": "Alex Rivera", "email": "alex@example.edu"},
    "experience": [{"employer": "Example Corp", "title": "Software Engineer", "dates": "Jan 2023 - Aug 2025"}],
    "education": [{"school": "Example University", "degree": "MS Computer Science", "dates": "Dec 2027"}],
    "projects": [{"name": "Basket Mining"}],
    "skills": {"Languages": ["Python", "SQL"], "Data": ["Spark"], "Cloud": ["GitHub Actions"]},
}

JD = ("Data Engineer Intern at Acme. We need Python, SQL and Spark to build pipelines for fraud analytics. "
      "Experience with Kubernetes is a plus. You will work with payments data at scale and ship weekly. ") * 2


@pytest.fixture
def kb():
    emb = HashingEmbedder()
    items = bankmod.parse_document(RESUME, "resume1", "resume") + bankmod.parse_document(LETTER, "letter1", "cover_letter")
    bank, _ = bankmod.merge([], items, emb)
    store = VectorStore.build([b.id for b in bank], [b.text for b in bank], emb)
    return emb, bank, store


def test_parse_resume_finds_bullets_and_projects(kb):
    _, bank, _ = kb
    kinds = [b.kind for b in bank]
    assert kinds.count("resume_bullet") == 2
    assert kinds.count("project") == 3  # including one starting lowercase ("mHealth ...")
    assert kinds.count("summary") == 1
    assert kinds.count("cover_paragraph") == 2 and kinds.count("cover_letter") == 1
    bullet = next(b for b in bank if b.kind == "resume_bullet")
    assert "Example Corp" in bullet.section


def test_merge_folds_near_duplicates():
    emb = HashingEmbedder()
    a = bankmod.parse_document(RESUME, "v1", "resume")
    tweaked = RESUME.replace("cutting deploy time", "cutting the deploy time")
    bank, added = bankmod.merge([], a, emb)
    bank2, added2 = bankmod.merge(bank, bankmod.parse_document(tweaked, "v2", "resume"), emb)
    assert added2 == 0 and len(bank2) == len(bank)
    assert max(b.variants for b in bank2) == 2


def test_store_roundtrip_and_search(tmp_path, kb):
    emb, bank, store = kb
    p = tmp_path / "index.npz"
    store.save(p)
    s2 = VectorStore.load(p)
    hits = s2.search(emb.embed(["Spark transactions mining"])[0], 2)
    top = next(b for b in bank if b.id == hits[0][0])
    assert "Spark" in top.text


def test_context_packet(kb):
    emb, bank, store = kb
    ctx = build_context(JD, bank, store, emb, Profile(PROFILE), top_k=1)
    # top-1 overall, plus each employer's own bullets so no job is left with nothing to say
    ids = [m["id"] for m in ctx["resume_material"]]
    assert len(ids) == len(set(ids)) >= 3
    assert sum(m["kind"] == "resume_bullet" for m in ctx["resume_material"]) == 2
    assert all(m["kind"] in {"resume_bullet", "project", "summary"} for m in ctx["resume_material"])
    assert ctx["voice_examples"]


def _draft(bank, bullet_text=None, extra_skill=None, letter_extra=""):
    b = next(x for x in bank if x.kind == "resume_bullet" and "CI/CD" in x.text)
    p = next(x for x in bank if x.kind == "project" and "Spark" in x.text)
    skills = {"Languages": ["Python", "SQL"], "Data": ["Spark"]}
    if extra_skill:
        skills["Data"].append(extra_skill)
    return {
        "resume": {
            "experience": [{"employer": "Example Corp", "title": "Software Engineer",
                            "bullets": [{"text": bullet_text or "Automated CI/CD with GitHub Actions, cutting deploy time from 10 to 2.4 min.", "sources": [b.id]}]}],
            "projects": [{"name": "Basket Mining", "text": "Mined ~1M transactions with SON in Spark, ~1.4x faster than Apriori.", "sources": [p.id]}],
            "skills": skills,
        },
        "cover_letter": {"greeting": "Dear Acme Team,", "paragraphs": ["I built payment integrations that handled 15,000 payments." + letter_extra]},
    }


def test_factcheck_passes_faithful_draft(kb):
    _, bank, _ = kb
    rep = factcheck.check(_draft(bank), Profile(PROFILE), bank, JD)
    assert rep.ok, rep.errors


def test_factcheck_blocks_inflated_number(kb):
    _, bank, _ = kb
    rep = factcheck.check(_draft(bank, "Automated CI/CD with GitHub Actions, cutting deploy time from 10 to 1.5 min."), Profile(PROFILE), bank, JD)
    assert any("1.5" in e for e in rep.errors)


def test_factcheck_blocks_skill_from_job_posting(kb):
    _, bank, _ = kb
    rep = factcheck.check(_draft(bank, extra_skill="Kubernetes"), Profile(PROFILE), bank, JD)
    assert any("kubernetes" in e.lower() for e in rep.errors)
    rep2 = factcheck.check(_draft(bank, letter_extra=" I also run Kubernetes clusters."), Profile(PROFILE), bank, JD)
    assert any("kubernetes" in e.lower() and "gap" in e for e in rep2.errors)
    rep3 = factcheck.check(_draft(bank, letter_extra=" I have not used Kubernetes yet and want to learn it."), Profile(PROFILE), bank, JD)
    assert rep3.ok and any("kubernetes" in w.lower() for w in rep3.warnings)


def test_factcheck_blocks_fake_employer_and_missing_sources(kb):
    _, bank, _ = kb
    d = _draft(bank)
    d["resume"]["experience"][0]["employer"] = "Google"
    d["resume"]["projects"][0]["sources"] = []
    rep = factcheck.check(d, Profile(PROFILE), bank, JD)
    assert any("Google" in e for e in rep.errors)
    assert any("cites no source" in e for e in rep.errors)


def test_profile_must_be_verified(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"verified": False}))
    with pytest.raises(ProfileNotVerified):
        Profile.load(p)


def test_numbers_normalized():
    assert {"5k", "99.9%", "2.4min", "1m", "1.4x", "15000"} <= numbers_in("5K+ users, 99.9% uptime, 2.4 min, ~1M rows, ~1.4x, 15,000")


def test_job_dedupe_across_sources(tmp_path):
    a = job_id("Acme, Inc.", "Data Engineer Intern (Summer 2027)", "Tulsa, OK")
    b = job_id("ACME", "Data Engineer Intern", "Tulsa")
    assert a == b
    store = JobStore(tmp_path)
    assert store.add(Job("Acme, Inc.", "Data Engineer Intern", JD, "Tulsa, OK"))
    assert not store.add(Job("ACME", "Data Engineer Intern", JD, "Tulsa", source="linkedin"))
    with pytest.raises(ValueError):
        store.add(Job("Other", "Role", "too short"))


def _cfg(tmp_path, target=9, max_it=3):
    return Config(target, max_it, tmp_path, "hashing", 10, 15, 6)


def test_loop_decisions(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = Job("Acme", "Data Engineer Intern", JD)
    store.add(job)
    cfg = _cfg(tmp_path)
    r1 = loop.record(store, job.id, 1, {"score": 6, "critique": "Vague."}, cfg)
    assert r1["decision"] == "revise"
    r2 = loop.record(store, job.id, 2, {"score": 8, "critique": "Better."}, cfg)
    assert r2["decision"] == "revise" and r2["best_iteration"] == 2
    r3 = loop.record(store, job.id, 3, {"score": 7, "critique": "Weak letter. Too long."}, cfg)
    assert r3["decision"] == "give_up" and r3["best_iteration"] == 2 and r3["best_score"] == 8
    assert store.state(job.id)["status"] == "needs_you"
    assert "8/10 after 3 rounds" in loop.notification_text(job.title, job.company, r3, "Weak letter. Too long.")


def test_loop_pass_and_parse_review(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = Job("Acme", "Data Engineer Intern", JD)
    store.add(job)
    rev = loop.parse_review('Here you go:\n```json\n{"score": 9, "would_interview": true, "critique": "Strong."}\n```')
    assert loop.record(store, job.id, 1, rev, _cfg(tmp_path))["decision"] == "pass"
    with pytest.raises(ValueError):
        loop.parse_review('{"score": 11}')


def test_env_config(monkeypatch, tmp_path):
    from jobagent.config import load_config
    monkeypatch.setenv("TARGET_SCORE", "8  # comment")
    monkeypatch.setenv("MAX_ITERATIONS", "3")
    monkeypatch.setenv("JOB_AGENT_DATA", str(tmp_path))
    c = load_config()
    assert (c.target_score, c.max_iterations, c.data_dir) == (8, 3, tmp_path)
    monkeypatch.setenv("TARGET_SCORE", "12")
    with pytest.raises(ValueError):
        load_config()
