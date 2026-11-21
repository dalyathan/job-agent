"""A small persistent vector store: one .npz file with normalized embeddings and ids.

A few hundred bullets need nothing heavier, and a single file is easy to keep
in a private folder and back up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .embed import Embedder


class VectorStore:
    def __init__(self, ids: list[str], vectors: np.ndarray, embedder_name: str):
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors differ in length")
        self.ids = ids
        self.vectors = vectors.astype(np.float32)
        self.embedder_name = embedder_name

    @classmethod
    def build(cls, ids: Sequence[str], texts: Sequence[str], embedder: Embedder) -> "VectorStore":
        return cls(list(ids), embedder.embed(list(texts)), embedder.name)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, ids=np.array(self.ids, dtype=object), vectors=self.vectors,
                 embedder=np.array(self.embedder_name))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
        if not path.exists():
            raise FileNotFoundError(f"No index at {path}. Run: job-agent build-kb")
        d = np.load(path, allow_pickle=True)
        return cls([str(i) for i in d["ids"]], d["vectors"], str(d["embedder"]))

    def search(
        self,
        query_vec: np.ndarray,
        k: int,
        keep: Callable[[str], bool] | None = None,
        diversity: float = 0.3,
    ) -> list[tuple[str, float]]:
        """Top-k by cosine similarity, re-ranked with maximal marginal relevance
        so near-duplicate bullets from different resume versions don't crowd out the rest."""
        if not self.ids:
            return []
        q = query_vec.reshape(-1)
        sims = self.vectors @ q
        cand = [i for i in np.argsort(-sims) if keep is None or keep(self.ids[i])]
        cand = cand[: max(k * 4, k)]
        chosen: list[int] = []
        while cand and len(chosen) < k:
            if not chosen:
                best = cand[0]
            else:
                sel = self.vectors[chosen]
                best = max(cand, key=lambda i: (1 - diversity) * sims[i] - diversity * float(np.max(sel @ self.vectors[i])))
            chosen.append(best)
            cand.remove(best)
        return [(self.ids[i], float(sims[i])) for i in chosen]
