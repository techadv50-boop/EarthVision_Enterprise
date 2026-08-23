"""Local text embeddings (hashing vectorizer — no external model download)."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from sklearn.feature_extraction.text import HashingVectorizer

EMBED_DIM = 384

_vectorizer = HashingVectorizer(
    n_features=EMBED_DIM,
    alternate_sign=False,
    norm="l2",
    ngram_range=(1, 2),
    stop_words="english",
)


def embed_text(text: str) -> list[float]:
    if not (text or "").strip():
        return [0.0] * EMBED_DIM
    vec = _vectorizer.transform([text]).toarray()[0]
    return [float(x) for x in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def top_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = [
        t.lower()
        for t in __import__("re").findall(r"[A-Za-z][A-Za-z\-]{3,}", text or "")
    ]
    stop = {
        "this",
        "that",
        "with",
        "from",
        "were",
        "have",
        "been",
        "which",
        "their",
        "using",
        "into",
        "also",
        "such",
        "these",
        "those",
        "about",
        "other",
        "more",
        "than",
        "paper",
        "study",
        "results",
        "based",
        "used",
        "between",
        "among",
        "however",
        "therefore",
        "proposed",
    }
    counts: dict[str, int] = {}
    for t in tokens:
        if t in stop:
            continue
        counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts, key=lambda k: (-counts[k], k))
    return ranked[:limit]


def overlap_terms(a: str, b: str, limit: int = 6) -> list[str]:
    ka = set(top_keywords(a, 20))
    kb = set(top_keywords(b, 20))
    return sorted(ka & kb)[:limit]
