"""Builds a subreddit's 'normal vocabulary fingerprint' from a corpus of
live posts (TF-IDF word/phrase frequency) plus semantic topic embeddings
(sentence-transformers), and scores arbitrary text against it.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

logger = logging.getLogger("subfit.fingerprint")

_EMBEDDER = None
_EMBEDDER_LOAD_FAILED = False
EMBEDDING_DIM = 384

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


class EmbedderUnavailable(RuntimeError):
    pass


def get_embedder():
    global _EMBEDDER, _EMBEDDER_LOAD_FAILED
    if _EMBEDDER_LOAD_FAILED:
        # Don't retry a slow network call (e.g. HF Hub download) on every
        # single request once we know it fails in this process; the next
        # process restart will try again.
        raise EmbedderUnavailable("sentence-transformers model failed to load earlier in this process.")
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer

        from .config import settings

        logger.info(
            "Loading sentence-transformers model '%s' (first run downloads it)...",
            settings.embedding_model_name,
        )
        try:
            _EMBEDDER = SentenceTransformer(settings.embedding_model_name)
        except Exception:
            _EMBEDDER_LOAD_FAILED = True
            raise
    return _EMBEDDER


def embed_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    embedder = get_embedder()
    vecs = embedder.encode(texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True)
    return vecs.astype(np.float32)


def embedding_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


@dataclass
class SubredditFingerprint:
    vectorizer: TfidfVectorizer
    vocab: dict[str, int]
    idf: np.ndarray
    idf_p85: float
    corpus_embeddings: np.ndarray  # (n_docs, dim), L2-normalized
    num_docs: int


def build_fingerprint(posts: list[dict]) -> Optional[SubredditFingerprint]:
    """Fits a TF-IDF vectorizer and collects normalized post embeddings from
    a subreddit's cached posts. Returns None if there isn't enough usable
    text to build a meaningful fingerprint (e.g. an empty/near-empty corpus).
    """
    texts: list[str] = []
    embeddings: list[np.ndarray] = []
    for p in posts:
        text = f"{p.get('title') or ''} {p.get('selftext') or ''}".strip()
        if not text:
            continue
        texts.append(text)
        blob = p.get("embedding")
        if blob:
            embeddings.append(blob_to_embedding(blob))

    if len(texts) < 5:
        return None

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        stop_words="english",
        min_df=2,
        max_df=0.9,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z'-]*\b",
    )
    try:
        vectorizer.fit(texts)
    except ValueError:
        # e.g. vocabulary is empty after min_df/stopword filtering
        return None

    idf = vectorizer.idf_
    idf_p85 = float(np.percentile(idf, 85))

    corpus_embeddings = (
        _normalize_rows(np.stack(embeddings)) if embeddings else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    )

    return SubredditFingerprint(
        vectorizer=vectorizer,
        vocab=vectorizer.vocabulary_,
        idf=idf,
        idf_p85=idf_p85,
        corpus_embeddings=corpus_embeddings,
        num_docs=len(texts),
    )


def extract_candidate_spans(text: str, max_ngram: int = 2) -> list[tuple[str, int, int]]:
    """Returns (phrase, start, end) candidates: every non-trivial word, plus
    contiguous word pairs (bigrams), skipping pure-stopword phrases."""
    tokens = [(m.group(0), m.start(), m.end()) for m in WORD_RE.finditer(text)]
    spans: list[tuple[str, int, int]] = []

    for word, start, end in tokens:
        if len(word) < 2 or word.lower() in ENGLISH_STOP_WORDS:
            continue
        spans.append((word, start, end))

    n = len(tokens)
    for size in range(2, max_ngram + 1):
        for i in range(n - size + 1):
            group = tokens[i : i + size]
            words = [g[0] for g in group]
            if all(w.lower() in ENGLISH_STOP_WORDS for w in words):
                continue
            # require the tokens to be adjacent in the source text (only
            # whitespace between them) so the highlighted span is a real
            # contiguous phrase, not a skip-gram.
            if any(group[j + 1][1] - group[j][2] > 1 for j in range(size - 1)):
                continue
            start, end = group[0][1], group[-1][2]
            spans.append((" ".join(words), start, end))

    return spans


@dataclass
class TermVerdict:
    phrase: str
    start: int
    end: int
    status: str  # "oov" | "rare" | "normal"
    idf: Optional[float]
    percentile: Optional[float]


def classify_terms(fp: SubredditFingerprint, spans: list[tuple[str, int, int]]) -> list[TermVerdict]:
    results: list[TermVerdict] = []
    for phrase, start, end in spans:
        idx = fp.vocab.get(phrase.lower())
        if idx is None:
            results.append(TermVerdict(phrase, start, end, "oov", None, None))
            continue
        idf_val = float(fp.idf[idx])
        percentile = float((fp.idf <= idf_val).mean() * 100)
        status = "rare" if idf_val >= fp.idf_p85 else "normal"
        results.append(TermVerdict(phrase, start, end, status, idf_val, percentile))
    return results


def semantic_fit(draft_text: str, fp: SubredditFingerprint, top_k: int = 20) -> Optional[float]:
    """Mean cosine similarity of the draft to its top_k nearest posts in the
    corpus. Returns None if no embeddings are available for this corpus."""
    if fp.corpus_embeddings.shape[0] == 0 or not draft_text.strip():
        return None
    try:
        draft_vec = embed_texts([draft_text])[0]
    except Exception:
        logger.warning("Embedding model unavailable; skipping semantic similarity for this check.", exc_info=True)
        return None
    norm = np.linalg.norm(draft_vec)
    if norm > 0:
        draft_vec = draft_vec / norm
    sims = fp.corpus_embeddings @ draft_vec
    k = min(top_k, sims.shape[0])
    top = np.sort(sims)[-k:]
    return float(np.mean(top))
