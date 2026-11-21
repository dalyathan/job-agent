"""Review-loop bookkeeping. Only the orchestrator uses this; neither the writer nor
the blind reviewers ever see scores, round numbers, or earlier critiques."""

from __future__ import annotations

import json
import re
from typing import Any

from .config import Config
from .jobs import JobStore


def parse_review(raw: str) -> dict[str, Any]:
    """Accepts the reviewer's reply and pulls out {"score": int, "would_interview": bool, "critique": str}."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("Reviewer reply has no JSON object")
    d = json.loads(m.group(0))
    score = int(d["score"])
    if not 1 <= score <= 10:
        raise ValueError(f"score out of range: {score}")
    return {
        "score": score,
        "would_interview": bool(d.get("would_interview", score >= 7)),
        "critique": str(d.get("critique", "")).strip(),
        "top_fixes": [str(x) for x in d.get("top_fixes", [])][:5],
    }


def record(store: JobStore, jid: str, n: int, review: dict[str, Any], cfg: Config) -> dict[str, Any]:
    """Store round n's review and decide what happens next.

    Returns {"decision": "pass" | "revise" | "give_up", "best_iteration": k, "best_score": s, ...}.
    """
    (store.iter_dir(jid, n) / "review.json").write_text(json.dumps(review, indent=1))
    st = store.state(jid)
    st["iterations"] = [i for i in st["iterations"] if i["n"] != n] + [{"n": n, "score": review["score"]}]
    best = max(st["iterations"], key=lambda i: (i["score"], -i["n"]))
    st["best"] = best
    if review["score"] >= cfg.target_score:
        decision = "pass"
    elif n >= cfg.max_iterations:
        decision = "give_up"
    else:
        decision = "revise"
    st["status"] = {"pass": "ready", "give_up": "needs_you", "revise": "in_progress"}[decision]
    store.save_state(jid, st)
    return {
        "decision": decision,
        "round": n,
        "score": review["score"],
        "best_iteration": best["n"],
        "best_score": best["score"],
        "target_score": cfg.target_score,
        "max_iterations": cfg.max_iterations,
        "scores": [i["score"] for i in sorted(st["iterations"], key=lambda i: i["n"])],
    }


def notification_text(job_title: str, company: str, result: dict[str, Any], last_critique: str) -> str:
    objection = last_critique.split(". ")[0][:140]
    return (f"{company} – {job_title}: best {result['best_score']}/10 after {result['round']} rounds "
            f"(target {result['target_score']}). Reviewer: {objection}")
