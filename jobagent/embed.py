"""Text embedders.

FastEmbedder runs a small ONNX model locally (no API key, no bill).
HashingEmbedder is a deterministic offline fallback used in tests.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, Sequence

import numpy as np


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class FastEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:  # pragma: no cover
            raise SystemExit("fastembed is not installed: pip install 'job-agent[embed]'") from e
        self.name = f"fastembed:{model}"
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return _normalize(np.array(list(self._model.embed(list(texts))), dtype=np.float32))


class HashingEmbedder:
    """Bag of word and word-pair hashes. Crude, but offline and deterministic."""

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hashing:{dim}"

    def _features(self, text: str) -> list[str]:
        words = re.findall(r"[a-z0-9+#.]+", text.lower())
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for f in self._features(t):
                h = int.from_bytes(hashlib.md5(f.encode()).digest()[:4], "little")
                m[i, h % self.dim] += 1.0 if h & (1 << 31) else -1.0
        return _normalize(m)


def get_embedder(model: str) -> Embedder:
    if model.startswith("hashing"):
        return HashingEmbedder()
    return FastEmbedder(model)
