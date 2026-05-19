"""AgentWeb two-pass ranking engine.

Pipeline
--------
1. First pass  – bm25s (Numba-backed) for fast candidate selection (top-50)
2. Second pass – FlashRank cross-encoder (ONNX) for precise reranking
3. Recency weighting – exponential decay based on extracted dates
4. Domain diversity – max 2 per domain, max 30 % social sources

Graceful degradation:
- bm25s missing → pure-Python BM25 fallback
- flashrank missing → skip second pass, use bm25s scores only
"""

from __future__ import annotations

import collections
import math
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# ─── Optional library imports with graceful fallbacks ───────────────────────

try:
    import bm25s
except Exception:
    bm25s = None  # type: ignore

try:
    from flashrank import Ranker as FlashRanker
except Exception:
    FlashRanker = None  # type: ignore


# ─── Constants ───────────────────────────────────────────────────────────────

_SOCIAL_DOMAINS: frozenset[str] = frozenset({
    "reddit.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "linkedin.com",
    "tiktok.com",
    "instagram.com",
    "threads.net",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
    "tumblr.com",
    "snapchat.com",
    "discord.com",
    "discord.gg",
})

_RE_SHORT_TOKEN = re.compile(r"[a-zA-Z0-9]{3,}")

# Date regexes
_RE_ISO_DATE = re.compile(
    r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b"
)
_RE_MONTH_NAME = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.I,
)
_RE_YEAR_ONLY = re.compile(r"\b(20[2-9]\d)\b")

# Stopwords for fallback tokenizer
_DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "was", "one", "our", "out", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "way", "who",
    "did", "she", "use", "via", "that", "from", "have", "been",
    "were", "said", "also", "they", "this", "what", "than",
    "with", "their", "about", "into", "over", "after", "some",
    "more", "most", "much", "many", "very", "just", "like",
    "do", "it", "is", "be", "to", "of", "in", "on", "at",
    "by", "as", "an", "or", "if", "so", "up", "no", "we",
    "he", "she", "my", "me", "go", "am", "pm",
})


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class RankResult:
    url: str
    title: str
    snippet: str
    text: str = ""
    source: str = ""
    bm25_score: float = 0.0
    flashrank_score: float = 0.0
    final_score: float = 0.0
    date_str: str | None = None
    domain: str = ""
    source_type: str = ""
    suppression_reason: str | None = None
    recency_boost: float = 0.0
    rank: int = 0


# ─── Pure-Python BM25 fallback ─────────────────────────────────────────────────

class _BM25Fallback:
    """Classic Okapi BM25 (k1=1.5, b=0.75) — used when bm25s is unavailable."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t.lower() for t in _RE_SHORT_TOKEN.findall(text)]

    def score(self, query: str, documents: list[str]) -> list[float]:
        query_terms = self._tokenize(query)
        docs_tok = [self._tokenize(d) for d in documents]
        avgdl = sum(len(d) for d in docs_tok) / max(len(docs_tok), 1)
        N = len(documents)

        # Document frequency across corpus
        df: dict[str, int] = {}
        for doc_tok in docs_tok:
            seen = set(doc_tok)
            for term in seen:
                df[term] = df.get(term, 0) + 1

        scores: list[float] = []
        for doc_tok in docs_tok:
            doc_len = len(doc_tok)
            tf = collections.Counter(doc_tok)
            score = 0.0
            for term in query_terms:
                term_tf = tf.get(term, 0)
                if term_tf == 0:
                    continue
                doc_freq = df.get(term, 1)
                idf = math.log((N - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
                numerator = term_tf * (self.k1 + 1)
                denominator = term_tf + self.k1 * (1 - self.b + self.b * doc_len / (avgdl + 1e-9))
                score += idf * (numerator / (denominator + 1e-9))
            scores.append(score)
        return scores


# ─── Helper functions ────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _is_social_domain(domain: str) -> bool:
    return any(domain.endswith(s) or domain == s for s in _SOCIAL_DOMAINS)


def _classify_source_type(url: str) -> str:
    """Classify a source URL into a type category."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    if any(d in domain for d in ("arxiv.org", "nature.com", "science.org", "sciencedirect.com",
                                  "springer.com", "ieee.org", "acm.org", "pubmed.ncbi.nlm.nih.gov",
                                  "jstor.org", "cambridge.org", "oup.com", "tandfonline.com",
                                  "wiley.com", "sagepub.com")):
        return "academic"
    if "/abs/" in path or "/pdf/" in path:
        return "academic"
    if "doi.org" in domain or "doi" in path:
        return "academic"

    if "wikipedia.org" in domain:
        return "wikipedia"

    if domain.endswith((".gov", ".mil", ".gov.uk", ".gouv.fr", ".europa.eu")):
        return "government"

    if any(d in domain for d in ("news", "reuters.com", "apnews.com", "bbc.", "cnn.com",
                                  "nytimes.com", "wsj.com", "washingtonpost.com", "theguardian.com",
                                  "bloomberg.com", "economist.com", "theverge.com", "wired.com",
                                  "zdnet.com", "arstechnica.com", "techcrunch.com", "thehill.com",
                                  "politico.com", "npr.org", "theatlantic.com")):
        return "news"

    if any(d in domain for d in ("reddit.com", "twitter.com", "x.com", "facebook.com",
                                  "linkedin.com", "tiktok.com", "instagram.com", "threads.net",
                                  "youtube.com", "youtu.be")):
        return "social"

    if any(d in domain for d in ("stackoverflow.com", "stackexchange.com", "quora.com",
                                  "stackapps.com", "serverfault.com", "superuser.com")):
        return "forum"

    if any(d in domain for d in ("github.com", "gitlab.com", "bitbucket.org", "docs.",
                                  "readthedocs.io", "documentation", "api.")):
        return "documentation"

    if any(d in domain for d in ("medium.com", "substack.com", "wordpress.com", "blog.", "ghost.io")):
        return "blog"

    if any(d in domain for d in ("amazon.com", "ebay.com", "shopify.com", "etsy.com", " walmart.com")):
        return "commercial"

    return "general"


def _extract_date_from_text(text: str) -> str | None:
    """Extract a publication/freshness date from text content."""
    # ISO dates: 2024-01-15 or 2024/01/15
    m = _RE_ISO_DATE.search(text)
    if m:
        return m.group(0)

    # "January 15, 2024"
    m = _RE_MONTH_NAME.search(text)
    if m:
        return m.group(0)

    # Standalone year (last resort)
    m = _RE_YEAR_ONLY.search(text)
    if m:
        return m.group(1)

    return None


def _parse_date_to_days(date_str: str | None) -> int | None:
    """Convert extracted date string to days since epoch for decay calc."""
    if not date_str:
        return None

    # ISO
    m = _RE_ISO_DATE.match(date_str)
    if m:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d") if "-" in date_str else datetime.strptime(date_str, "%Y/%m/%d")
            return (dt.date() - date(1970, 1, 1)).days
        except Exception:
            pass

    # Month name
    m = _RE_MONTH_NAME.match(date_str)
    if m:
        try:
            dt = datetime.strptime(date_str, "%B %d, %Y")
            return (dt.date() - date(1970, 1, 1)).days
        except Exception:
            try:
                dt = datetime.strptime(date_str, "%B %d %Y")
                return (dt.date() - date(1970, 1, 1)).days
            except Exception:
                pass

    # Year only
    m = _RE_YEAR_ONLY.match(date_str)
    if m:
        try:
            dt = datetime(int(m.group(1)), 1, 1)
            return (dt.date() - date(1970, 1, 1)).days
        except Exception:
            pass

    return None


def _recency_boost(date_str: str | None, half_life_days: float = 365.0) -> float:
    """Exponential decay recency weight. Newer = higher.

    Returns a boost factor in [0.3, 1.5].
    """
    doc_days = _parse_date_to_days(date_str)
    if doc_days is None:
        return 0.8  # neutral-ish when unknown

    today_days = (date.today() - date(1970, 1, 1)).days
    age_days = max(0, today_days - doc_days)

    # Exponential decay: e^(-age / half_life)
    decay = math.exp(-age_days / half_life_days)

    # Map decay [0, 1] to boost [0.3, 1.5]
    boost = 0.3 + 1.2 * decay
    return round(boost, 4)


# ─── Core ranking pipeline ───────────────────────────────────────────────────

def rank_results(
    query: str,
    results: list[dict],
    prefer: list[str] | None = None,
    exclude: list[str] | None = None,
    *,
    context: str | None = None,
    max_candidates: int = 50,
    top_n: int = 20,
) -> list[dict]:
    """Two-pass rank results with BM25 first pass and FlashRank rerank.

    Parameters
    ----------
    query:
        User query string.
    results:
        Incoming result dicts with keys: title, url, snippet, source, text (optional).
    prefer:
        Optional list of domain substrings to boost (e.g. ["github.com"]).
    exclude:
        Optional list of domain substrings to drop entirely.
    context:
        Optional context string. Augments the query for BM25/FlashRank
        scoring so results semantically relevant to the context rank higher.
    max_candidates:
        How many candidates to keep after the first BM25 pass.
    top_n:
        How many results to return after all filtering / reranking.

    Returns
    -------
    list[dict]
        Enriched result dicts with ranking scores and optional suppression_reason.
    """
    if not results:
        return []

    prefer = [p.lower() for p in (prefer or [])]
    exclude = [e.lower() for e in (exclude or [])]

    # Augment query with context for ranking bias
    effective_query = f"{query} {context}".strip() if context else query

    # ── Build working items ──────────────────────────────────────────────
    items: list[RankResult] = []
    for r in results:
        url = r.get("url", "")
        domain = _extract_domain(url)

        # Exclusion filter
        if any(e in domain for e in exclude):
            continue

        text = r.get("text") or r.get("snippet") or ""
        date_str = _extract_date_from_text(text)
        source_type = _classify_source_type(url)

        items.append(
            RankResult(
                url=url,
                title=r.get("title", "") or "",
                snippet=r.get("snippet", "") or "",
                text=text,
                source=r.get("source", "") or "",
                domain=domain,
                date_str=date_str,
                source_type=source_type,
            )
        )

    if not items:
        return []

    # ── First pass: BM25 scoring ───────────────────────────────────────
    # Build documents from title + snippet + text
    documents = [f"{it.title}\n{it.snippet}\n{it.text}" for it in items]

    bm25_scores: list[float] = []
    if bm25s is not None:
        try:
            # bm25s.tokenize expects a list of strings for the corpus
            corpus_tokens = bm25s.tokenize(documents, stopwords="en")
            query_tokens = bm25s.tokenize([effective_query], stopwords="en")
            retriever = bm25s.BM25()
            retriever.index(corpus_tokens)
            # bm25s returns results, scores; we want scores for all docs
            results_bm = retriever.retrieve(query_tokens, k=len(documents), return_as="tuple")
            # results_bm is a tuple of (doc_indices, scores); doc_indices shape (1, k), scores shape (1, k)
            # We need to map back to original ordering
            indices = results_bm[0][0]  # shape (k,)
            scores = results_bm[1][0]   # shape (k,)
            # Build full score vector
            score_map = {int(idx): float(score) for idx, score in zip(indices, scores)}
            bm25_scores = [score_map.get(i, 0.0) for i in range(len(documents))]
        except Exception:
            # Degrade to fallback on any bm25s runtime error
            bm25_scores = []

    if not bm25_scores:
        fallback = _BM25Fallback()
        bm25_scores = fallback.score(effective_query, documents)

    for it, score in zip(items, bm25_scores):
        it.bm25_score = score

    # ── Candidate selection: top-50 by BM25 ──────────────────────────────
    items.sort(key=lambda x: x.bm25_score, reverse=True)
    candidates = items[:max_candidates]

    # ── Second pass: FlashRank cross-encoder ───────────────────────────
    flashrank_available = FlashRanker is not None
    if flashrank_available:
        try:
            ranker = FlashRanker(model_name="ms-marco-MiniLM-L-12-v2")
            # Build query-doc pairs (use effective_query for context-aware reranking)
            pairs = [
                {"query": effective_query, "text": f"{c.title}\n{c.snippet}\n{c.text}"}
                for c in candidates
            ]
            reranked = ranker.rerank(pairs)
            # reranked is a list of dicts with "score" key
            for cand, rr in zip(candidates, reranked):
                cand.flashrank_score = float(rr.get("score", 0.0))
        except Exception:
            # FlashRank failed; fall back to BM25-only
            for cand in candidates:
                cand.flashrank_score = 0.0
    else:
        for cand in candidates:
            cand.flashrank_score = 0.0

    # ── Recency weighting ──────────────────────────────────────────────
    for cand in candidates:
        cand.recency_boost = _recency_boost(cand.date_str)

    # ── Final score composition ──────────────────────────────────────────
    # Normalise bm25 and flashrank to [0, 1] within candidate set
    max_bm = max((c.bm25_score for c in candidates), default=1.0) or 1.0
    max_fr = max((c.flashrank_score for c in candidates), default=1.0) or 1.0

    for cand in candidates:
        norm_bm = cand.bm25_score / max_bm
        if cand.flashrank_score > 0:
            norm_fr = cand.flashrank_score / max_fr
            # 60 % flashrank + 30 % bm25 + 10 % recency
            cand.final_score = 0.3 * norm_bm + 0.6 * norm_fr + 0.1 * cand.recency_boost
        else:
            # No flashrank: 80 % bm25 + 20 % recency
            cand.final_score = 0.8 * norm_bm + 0.2 * cand.recency_boost

    # Re-sort by final score
    candidates.sort(key=lambda x: x.final_score, reverse=True)

    # ── Domain diversity enforcement ────────────────────────────────────
    # Rules:
    # 1. Max 2 results per domain
    # 2. Max 30 % social sources in final output
    # 3. Prefer-boost: bump final_score by 15 % for preferred domains
    # 4. If everything gets filtered, still return top 5
    domain_counts: dict[str, int] = {}
    social_count = 0
    selected: list[RankResult] = []
    suppressed: list[RankResult] = []

    for cand in candidates:
        # Prefer boost
        if any(p in cand.domain for p in prefer):
            cand.final_score *= 1.15

        # Domain cap
        if domain_counts.get(cand.domain, 0) >= 2:
            cand.suppression_reason = f"domain_cap: {cand.domain}"
            suppressed.append(cand)
            continue

        # Social cap (max 30 % of intended top_n)
        max_social = max(1, int(top_n * 0.30))
        if _is_social_domain(cand.domain):
            if social_count >= max_social:
                cand.suppression_reason = "social_cap"
                suppressed.append(cand)
                continue
            social_count += 1

        domain_counts[cand.domain] = domain_counts.get(cand.domain, 0) + 1
        selected.append(cand)

    # If diversity filtering left us with < 5, append best suppressed
    if len(selected) < 5:
        # Sort suppressed by final_score descending and backfill
        suppressed.sort(key=lambda x: x.final_score, reverse=True)
        for sup in suppressed:
            if len(selected) >= 5:
                break
            if sup not in selected:
                selected.append(sup)

    # Ensure we don't exceed top_n (plus any suppressed we include for backfill)
    final_list = selected[:top_n]

    # ── Assign ranks and return as plain dicts ──────────────────────────
    output: list[dict] = []
    for idx, it in enumerate(final_list, start=1):
        it.rank = idx
        output.append({
            "title": it.title,
            "url": it.url,
            "snippet": it.snippet,
            "source": it.source,
            "rank": it.rank,
            "bm25_score": round(it.bm25_score, 6),
            "flashrank_score": round(it.flashrank_score, 6),
            "final_score": round(it.final_score, 6),
            "recency_boost": it.recency_boost,
            "suppression_reason": it.suppression_reason,
            "date_extracted": it.date_str,
        })

    return output


def compute_bm25_scores(
    query: str,
    documents: list[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Compute BM25 scores for documents against a query.

    Uses bm25s (Numba-accelerated) when available, falls back to pure-Python BM25.

    Args:
        query: The query string.
        documents: List of document texts.
        k1: BM25 k1 parameter (default 1.5).
        b: BM25 b parameter (default 0.75).

    Returns:
        List of BM25 scores, one per document.
    """
    if not documents or not query:
        return [0.0] * len(documents)

    if bm25s is not None:
        try:
            corpus_tokens = bm25s.tokenize(documents, stopwords="en")
            query_tokens = bm25s.tokenize([query], stopwords="en")
            retriever = bm25s.BM25(k1=k1, b=b)
            retriever.index(corpus_tokens)
            results_bm = retriever.retrieve(query_tokens, k=len(documents), return_as="tuple")
            indices = results_bm[0][0]
            scores = results_bm[1][0]
            score_map = {int(idx): float(score) for idx, score in zip(indices, scores)}
            return [score_map.get(i, 0.0) for i in range(len(documents))]
        except Exception:
            pass

    # Fallback to pure-Python BM25
    fallback = _BM25Fallback(k1=k1, b=b)
    return fallback.score(query, documents)


# ─── Novelty scoring (bm25s-based replacement for core.py TF-IDF) ─────────────

def compute_novelty_scores(
    already_knows: list[str],
    result_texts: list[str],
) -> list[float]:
    """Compute novelty scores for each result vs ``already_knows`` texts using bm25s.

    Algorithm
    ---------
    1. Index the ``already_knows`` texts as the BM25 corpus.
    2. Query each ``result_text`` against that corpus.
    3. The BM25 score indicates similarity to already-known content.
    4. Normalise scores to [0, 1] and invert: ``novelty = 1 - similarity``.

    Returns
    -------
    list[float]
        One novelty score per result (0.0 = fully known, 1.0 = completely novel).

    Notes
    -----
    - Falls back to pure-Python TF-IDF if bm25s is unavailable.
    - Empty ``already_knows`` or ``result_texts`` → all scores 1.0.
    """
    if not already_knows or not result_texts:
        return [1.0] * len(result_texts)

    # Clean inputs
    known_docs = [k.strip() for k in already_knows if k.strip()]
    result_docs = [t.strip() for t in result_texts]

    if not known_docs:
        return [1.0] * len(result_docs)

    if bm25s is not None:
        try:
            corpus_tokens = bm25s.tokenize(known_docs, stopwords="en")
            query_tokens = bm25s.tokenize(result_docs, stopwords="en")
            retriever = bm25s.BM25()
            retriever.index(corpus_tokens)
            # Retrieve top-1 for each query (most similar known doc)
            res = retriever.retrieve(query_tokens, k=1, return_as="tuple")
            # res[0] = indices shape (num_queries, 1), res[1] = scores shape (num_queries, 1)
            scores = res[1].flatten()
            max_score = float(scores.max()) if scores.size > 0 else 1.0
            if max_score == 0:
                max_score = 1.0
            # Normalise and invert
            novelties = [1.0 - min(float(s) / max_score, 1.0) for s in scores]
            return novelties
        except Exception:
            pass

    # Fallback: pure-Python cosine similarity over TF-IDF vectors
    return _novelty_tfidf_fallback(known_docs, result_docs)


def _novelty_tfidf_fallback(already_knows: list[str], result_texts: list[str]) -> list[float]:
    """Pure-Python TF-IDF novelty fallback when bm25s is absent."""
    if not already_knows or not result_texts:
        return [1.0] * len(result_texts)

    known_tokens = [t.lower() for t in _RE_SHORT_TOKEN.findall(" ".join(already_knows))]
    if not known_tokens:
        return [1.0] * len(result_texts)

    known_tf: dict[str, int] = {}
    for t in known_tokens:
        known_tf[t] = known_tf.get(t, 0) + 1

    result_tfs: list[dict[str, int]] = []
    for text in result_texts:
        tokens = [t.lower() for t in _RE_SHORT_TOKEN.findall(text)]
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        result_tfs.append(tf)

    all_terms: set[str] = set(known_tf)
    for rt in result_tfs:
        all_terms.update(rt)

    N = len(result_tfs)
    doc_freq: dict[str, int] = {}
    for rt in result_tfs:
        for term in rt:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    def _tfidf_vector(tf: dict[str, int]) -> tuple[dict[str, float], float]:
        vec: dict[str, float] = {}
        sq_sum = 0.0
        for term, raw_tf in tf.items():
            df = doc_freq.get(term, 0)
            w = 1.0 + math.log(N / df) if df > 0 else 0.0
            val = raw_tf * w
            vec[term] = val
            sq_sum += val * val
        return vec, math.sqrt(sq_sum) if sq_sum > 0 else 1.0

    known_vec, known_norm = _tfidf_vector(known_tf)

    scores: list[float] = []
    for rt_tf in result_tfs:
        res_vec, res_norm = _tfidf_vector(rt_tf)
        dot = sum(known_vec.get(t, 0.0) * res_vec.get(t, 0.0) for t in all_terms)
        overlap = dot / (known_norm * res_norm) if known_norm * res_norm > 0 else 0.0
        overlap = max(0.0, min(1.0, overlap))
        scores.append(1.0 - overlap)

    return scores
