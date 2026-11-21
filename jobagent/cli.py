"""Command line for each pipeline step. The hourly agent (see prompts/runbook.md) calls these;
you can run them by hand too. Every command prints JSON."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import bank as bankmod
from . import factcheck, loop, render, tracker
from .config import load_config
from .embed import get_embedder
from .jobs import Job, JobStore
from .profile import Profile, ProfileNotVerified
from .retrieve import build_context
from .store import VectorStore


def out(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def cmd_check_profile(cfg, a):
    p = Profile.load(cfg.profile_path, require_verified=False)
    out({"verified": bool(p.data.get("verified")), "needs_review": p.needs_review})
    return 0 if p.data.get("verified") else 2


def cmd_ingest(cfg, a):
    emb = get_embedder(cfg.embed_model)
    items = bankmod.load_bank(cfg.bank_path)
    total = 0
    for f in a.files:
        f = Path(f)
        text = f.read_text(encoding="utf-8")
        new = bankmod.parse_document(text, a.source or f.stem, a.kind)
        items, added = bankmod.merge(items, new, emb)
        total += added
        dest = cfg.raw_dir / a.kind / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.resolve() != dest.resolve():
            shutil.copyfile(f, dest)
    bankmod.save_bank(cfg.bank_path, items)
    out({"added": total, "bank_size": len(items)})
    return 0


def cmd_build_kb(cfg, a):
    items = bankmod.load_bank(cfg.bank_path)
    if not items:
        out({"error": f"bank is empty: {cfg.bank_path}"})
        return 1
    emb = get_embedder(cfg.embed_model)
    VectorStore.build([i.id for i in items], [i.text for i in items], emb).save(cfg.index_path)
    kinds = {}
    for i in items:
        kinds[i.kind] = kinds.get(i.kind, 0) + 1
    out({"indexed": len(items), "by_kind": kinds, "embedder": emb.name, "index": str(cfg.index_path)})
    return 0


def cmd_add_job(cfg, a):
    text = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
    job = Job(company=a.company, title=a.title, location=a.location or "", url=a.url or "",
              source=a.source, deadline=a.deadline or "", text=text)
    store = JobStore(cfg.jobs_dir)
    added = store.add(job)
    if added:
        tracker.upsert(cfg.tracker_path, {"job_id": job.id, "company": job.company, "title": job.title,
                                          "location": job.location, "url": job.url, "source": job.source,
                                          "status": "new"})
    out({"id": job.id, "added": added, "duplicate": not added})
    return 0


def cmd_seen(cfg, a):
    from .jobs import job_id
    jid = job_id(a.company, a.title, a.location or "")
    out({"id": jid, "seen": JobStore(cfg.jobs_dir).exists(jid)})
    return 0


def cmd_pending(cfg, a):
    out({"pending": JobStore(cfg.jobs_dir).pending()})
    return 0


def cmd_skip(cfg, a):
    store = JobStore(cfg.jobs_dir)
    st = store.state(a.job_id)
    st.update({"status": a.status, "reason": a.reason})
    store.save_state(a.job_id, st)
    tracker.upsert(cfg.tracker_path, {"job_id": a.job_id, "status": a.status, "notes": a.reason})
    out({"id": a.job_id, "status": a.status})
    return 0


def cmd_context(cfg, a):
    profile = Profile.load(cfg.profile_path)
    store = JobStore(cfg.jobs_dir)
    job = store.get(a.job_id)
    emb = get_embedder(cfg.embed_model)
    ctx = build_context(f"{job.title} at {job.company}\n{job.text}", bankmod.load_bank(cfg.bank_path),
                        VectorStore.load(cfg.index_path), emb, profile, top_k=cfg.top_k)
    path = store.dir(a.job_id) / "context.json"
    path.write_text(json.dumps(ctx, indent=1, ensure_ascii=False), encoding="utf-8")
    out({"context": str(path), "resume_material": len(ctx["resume_material"]),
         "cover_letter_material": len(ctx["cover_letter_material"]), "voice_examples": len(ctx["voice_examples"])})
    return 0


def _draft(store, jid, n):
    p = store.iter_dir(jid, n) / "draft.json"
    if not p.exists():
        raise SystemExit(f"missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_factcheck(cfg, a):
    store = JobStore(cfg.jobs_dir)
    rep = factcheck.check(_draft(store, a.job_id, a.n), Profile.load(cfg.profile_path),
                          bankmod.load_bank(cfg.bank_path), store.get(a.job_id).text)
    (store.iter_dir(a.job_id, a.n) / "factcheck.json").write_text(json.dumps(rep.as_dict(), indent=1))
    out(rep.as_dict())
    return 0 if rep.ok else 1


def cmd_blind_packet(cfg, a):
    """Exactly what a blind reviewer may see: the posting and the two documents. Nothing else."""
    store = JobStore(cfg.jobs_dir)
    job = store.get(a.job_id)
    d = _draft(store, a.job_id, a.n)
    contact = Profile.load(cfg.profile_path).contact_block()
    print(f"=== JOB DESCRIPTION ===\n{job.title} — {job.company}\n{job.location}\n\n{job.text.strip()}\n\n"
          f"=== RESUME ===\n{render.resume_text(d['resume'], contact)}\n\n"
          f"=== COVER LETTER ===\n{render.letter_text(d['cover_letter'])}")
    return 0


def cmd_record_review(cfg, a):
    store = JobStore(cfg.jobs_dir)
    raw = Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
    result = loop.record(store, a.job_id, a.n, loop.parse_review(raw), cfg)
    job = store.get(a.job_id)
    tracker.upsert(cfg.tracker_path, {"job_id": job.id, "status": store.state(job.id)["status"],
                                      "best_score": str(result["best_score"]), "rounds": str(result["round"])})
    if result["decision"] == "give_up":
        crit = json.loads((store.iter_dir(a.job_id, a.n) / "review.json").read_text())["critique"]
        result["notification"] = loop.notification_text(job.title, job.company, result, crit)
    out(result)
    return 0


def cmd_finalize(cfg, a):
    store = JobStore(cfg.jobs_dir)
    st = store.state(a.job_id)
    if not st.get("best"):
        out({"error": "no reviewed iterations yet"})
        return 1
    n = st["best"]["n"]
    d = _draft(store, a.job_id, n)
    job = store.get(a.job_id)
    contact = Profile.load(cfg.profile_path).contact_block()
    name = contact.get("name", "Resume").replace(" ", "_")
    co = "".join(c for c in job.company if c.isalnum())
    final = store.dir(a.job_id) / "final"
    r = render.resume_docx(d["resume"], contact, final / f"{name}_Resume_{co}.docx")
    l = render.letter_docx(d["cover_letter"], contact, final / f"{name}_Cover_Letter_{co}.docx")
    fc = store.iter_dir(a.job_id, n) / "factcheck.json"
    tracker.upsert(cfg.tracker_path, {"job_id": job.id, "status": st["status"], "best_score": str(st["best"]["score"]),
                                      "resume_file": str(r), "letter_file": str(l)})
    out({"resume": str(r), "cover_letter": str(l), "iteration": n, "score": st["best"]["score"],
         "status": st["status"], "warnings": json.loads(fc.read_text())["warnings"] if fc.exists() else []})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="job-agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-profile")
    p = sub.add_parser("ingest", help="add past resumes/cover letters (plain text) to the bank")
    p.add_argument("--kind", choices=["resume", "cover_letter"], required=True)
    p.add_argument("--source")
    p.add_argument("files", nargs="+")
    sub.add_parser("build-kb", help="embed the bank into the vector index")
    p = sub.add_parser("add-job", help="add a posting (full description on stdin or --file)")
    for f in ("company", "title"):
        p.add_argument(f"--{f}", required=True)
    for f in ("location", "url", "deadline", "file"):
        p.add_argument(f"--{f}")
    p.add_argument("--source", default="handshake")
    p = sub.add_parser("seen", help="has this posting been processed before?")
    p.add_argument("--company", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--location")
    sub.add_parser("pending")
    p = sub.add_parser("skip", help="mark a job skipped (poor fit) or needing you")
    p.add_argument("job_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--status", default="skipped", choices=["skipped", "needs_you"])
    for name in ("context", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("job_id")
    for name in ("factcheck", "blind-packet", "record-review"):
        p = sub.add_parser(name)
        p.add_argument("job_id")
        p.add_argument("n", type=int)
        if name == "record-review":
            p.add_argument("--file")
    a = ap.parse_args(argv)
    cfg = load_config()
    handler = globals()["cmd_" + a.cmd.replace("-", "_")]
    try:
        return handler(cfg, a)
    except ProfileNotVerified as e:
        out({"error": "profile_not_verified", "detail": str(e)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
