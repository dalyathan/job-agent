"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").split("#")[0].strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e


@dataclass(frozen=True)
class Config:
    target_score: int
    max_iterations: int
    data_dir: Path
    embed_model: str
    top_k: int
    handshake_max_new: int
    min_fit_score: int

    @property
    def profile_path(self) -> Path:
        return self.data_dir / "profile.json"

    @property
    def bank_path(self) -> Path:
        return self.data_dir / "bank.jsonl"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index.npz"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def tracker_path(self) -> Path:
        return self.data_dir / "tracker.csv"


def load_config() -> Config:
    cfg = Config(
        target_score=_int("TARGET_SCORE", 9),
        max_iterations=_int("MAX_ITERATIONS", 5),
        data_dir=Path(os.environ.get("JOB_AGENT_DATA", "~/Documents/job-agent-data")).expanduser(),
        embed_model=os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        top_k=_int("TOP_K", 14),
        handshake_max_new=_int("HANDSHAKE_MAX_NEW_PER_RUN", 15),
        min_fit_score=_int("MIN_FIT_SCORE", 6),
    )
    if not 1 <= cfg.target_score <= 10:
        raise ValueError("TARGET_SCORE must be between 1 and 10")
    if cfg.max_iterations < 1:
        raise ValueError("MAX_ITERATIONS must be at least 1")
    return cfg
