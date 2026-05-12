"""
AgentWeb Deep Research — NO LLM ARCHITECTURE
==============================================
Inspired by: Claude (orchestrator-worker), ChatGPT (plan-then-execute), Perplexity (iterative refine).
Constraint: Zero LLM API calls inside AgentWeb. All reasoning is classical NLP + graph algorithms.

This module lives at agentweb/deep_research.py and is imported by cli.py as a new command.
"""

from __future__ import annotations

import collections
import concurrent.futures
import email.utils
import hashlib
import html
import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple

# AgentWeb's own imports
from agentweb.core import fetch_url, search_web, FetchResult, SearchResult
from agentweb.safety import InputGuard

# ─── Shared regexes ──────────────────────────────────────────────────────────
_RE_TERM_TOKEN = re.compile(r"[a-zA-Z0-9]{3,}")
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_RE_ENTITY_CAPTURE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b"
)  # Capitalized phrases
_RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_RE_URL = re.compile(r"https?://[^\s\"'<>()]+")
_RE_INT_QUESTION = re.compile(
    r"\b(how\s+many|how\s+much|how\s+long|how\s+far|how\s+old|"
    r"which\s+year|list\s+all|name\s+all|find\s+all|identify\s+all)\b",
    re.I,
)
_RE_COMPARISON = re.compile(
    r"\b(compare|versus|vs|difference\s+between|better\s+than|"
    r"pros\s+and\s+cons|advantages\s+and\s+disadvantages)\b",
    re.I,
)
_RE_LIST_QUERY = re.compile(
    r"\b(list|catalog|compile|gather|collect|find\s+every|all\s+the)\b", re.I
)
_RE_FACTUAL = re.compile(
    r"\b(what\s+is|what\s+are|who\s+is|who\s+was|when\s+did|where\s+is|"
    r"why\s+does|define|explain\s+how)\b",
    re.I,
)

# ── Query normalization (strip question words, extract keywords) ────────────
_RE_QUESTION_PREFIX = re.compile(
    r"^("
    r"what\s+(is|are|does|do|was|were)|"
    r"how\s+(does|do|is|are|can|would|could|should|did)|"
    r"why\s+(does|do|is|are|did)|"
    r"when\s+(does|do|is|are|did)|"
    r"where\s+(does|do|is|are|did)|"
    r"who\s+(is|are|was|were)|"
    r"which\s+|"
    r"explain\s+|"
    r"define\s+|"
    r"describe\s+|"
    r"tell\s+(us|me)\s+"
    r")\s*",
    re.I,
)
_RE_QUESTION_TRAILING = re.compile(r"\s*\?\s*$")
_RE_STOP_WORDS = re.compile(
    r"\b("
    r"the|a|an|in|on|at|to|for|of|by|with|from|"
    r"is|are|was|were|be|been|has|have|had|"
    r"do|does|did|will|would|could|should|may|might|can|"
    r"this|that|these|those|it|its|they|them|their|we|our|you|your"
    r")\b",
    re.I,
)
_RE_WHITESPACE = re.compile(r"\s+")


def _simplify_query(query: str) -> str:
    """Strip leading question words and trailing '?' from a query.

    "What is the boiling point of water at sea level?" →
    "the boiling point of water at sea level"
    """
    q = query.strip()
    q = _RE_QUESTION_TRAILING.sub("", q)
    if _RE_QUESTION_PREFIX.match(q):
        q = _RE_QUESTION_PREFIX.sub("", q, count=1)
    # If simplification left an empty string, fall back to original
    stripped = q.strip()
    return stripped if stripped else query.strip()


def _extract_keywords(query: str) -> str:
    """Strip question words AND stopwords, returning only core keywords.

    "What is the boiling point of water at sea level?" →
    "boiling point water sea level"
    """
    q = _simplify_query(query)
    q = _RE_STOP_WORDS.sub("", q)
    q = _RE_WHITESPACE.sub(" ", q).strip()
    return q if q else _simplify_query(query)


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — QUERY DECOMPOSITION  (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

# Named tuple for a decomposed sub-query
class SubQuery(NamedTuple):
    id: str
    text: str
    intent: str  # "factual" | "comparison" | "list" | "interrogative" | "general"
    weight: float  # importance relative to other sub-queries (0–1)
    parent_terms: set[str]  # terms carried from parent query


@dataclass
class QueryPlan:
    original: str
    intent: str  # dominant intent of the whole query
    sub_queries: list[SubQuery]
    is_complex: bool  # True if should trigger multi-branch pipeline
    estimated_effort: str  # "low" | "medium" | "high"

    @property
    def branch_count(self) -> int:
        return max(1, len(self.sub_queries))


def decompose_query(query: str) -> QueryPlan:
    """
    Algorithmic decomposition WITHOUT LLM. Uses regex pattern matching,
    POS-adjacent heuristics, and query-type classification.
    """
    query = query.strip()
    q_lower = query.lower()
    terms = {t.lower() for t in _RE_TERM_TOKEN.findall(query)}
    q_words = q_lower.split()

    # ── Normalize: strip question words for sub-query generation ────────
    simplified = _simplify_query(query)
    keywords = _extract_keywords(query)

    # ── Classify dominant intent ──────────────────────────────────────────
    if _RE_INT_QUESTION.search(query):
        intent = "interrogative"  # needs enumeration, counting, precise answers
    elif _RE_COMPARISON.search(query):
        intent = "comparison"  # needs multi-perspective fetching
    elif _RE_LIST_QUERY.search(query):
        intent = "list"  # needs breadth-first coverage
    elif _RE_FACTUAL.search(query):
        intent = "factual"
    else:
        intent = "general"

    # ── Complexity heuristics ─────────────────────────────────────────────
    # Count query "density" signals
    signals = 0
    signals += len(terms) >= 8  # long query = complex
    signals += intent in ("interrogative", "comparison", "list")
    signals += bool(_RE_YEAR.findall(query))  # temporal = specific
    signals += 3 in [len(q) for q in q_words if len(q) > 5]  # multiple long words
    is_complex = signals >= 2

    # Comparison queries always benefit from multi-branch
    if intent == "comparison":
        is_complex = True

    # ── Generate sub-queries ──────────────────────────────────────────────
    sub_queries: list[SubQuery] = []

    if is_complex:
        # Strategy: decompose into 3–5 parallel sub-branches
        branch_count = 3 if intent == "factual" else 5
        for i in range(branch_count):
            branch_intent = ["factual", "background", "current_status", "details", "examples"][
                i
            ]
            weight = 1.0 / branch_count

            if intent == "comparison":
                # Comparison queries: split into per-side branches
                # Extract named entities (products/platforms) from the query
                entities = _RE_ENTITY_CAPTURE.findall(query)
                unique_entities = []
                seen = set()
                for e in entities:
                    key = e.lower()
                    if key not in seen and len(key) > 2:
                        seen.add(key)
                        unique_entities.append(e)
                if i == 0 and unique_entities:
                    branch_q = f"{unique_entities[0]} deep research features how it works"
                elif i == 1 and len(unique_entities) > 1:
                    branch_q = f"{unique_entities[1]} deep research features how it works"
                elif i == 2 and len(unique_entities) > 2:
                    branch_q = f"{unique_entities[2]} deep research features how it works"
                else:
                    # Remaining branches: cross-comparison and benchmarks
                    cross_suffixes = [
                        "comparison benchmarks performance accuracy",
                        "pricing availability free paid",
                        "use cases best for when to use",
                    ]
                    branch_q = f"{simplified or query} {cross_suffixes[i % len(cross_suffixes)]}"
            elif i == 0:
                # Branch 0: core definition / primary answer
                branch_q = simplified or query
            elif i == 1:
                # Branch 1: background / history / context
                if intent == "factual":
                    branch_q = f"{simplified or query} history background origin"
                elif intent == "list":
                    branch_q = f"{simplified or query} overview categories types"
                else:
                    branch_q = f"{simplified or query} background context overview"
            elif i == 2:
                # Branch 2: current state / recent developments
                branch_q = f"{simplified or query} 2024 2025 2026 current recent latest"
            elif i == 3:
                # Branch 3: specific details / edge cases
                branch_q = f"{simplified or query} details examples use cases"
            else:
                # Branch 4: related topics / broader context
                branch_q = f"{simplified or query} related topics compared alternative"

            branch_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(branch_q)}
            sub_queries.append(
                SubQuery(
                    id=f"q{i}",
                    text=branch_q,
                    intent=branch_intent,
                    weight=weight,
                    parent_terms=terms & branch_terms,
                )
            )
    else:
        # Simple query: one branch with query expansion
        expansion_suffixes = []
        if intent == "factual":
            expansion_suffixes = ["definition explanation"]
        elif intent == "interrogative":
            expansion_suffixes = ["statistics data numbers"]
        elif intent == "comparison":
            expansion_suffixes = ["pros cons comparison review"]
        elif intent == "list":
            expansion_suffixes = ["all list complete comprehensive"]

        expanded = simplified or query
        if expansion_suffixes:
            expanded = f"{expanded} {' '.join(expansion_suffixes)}"

        sub_queries.append(
            SubQuery(
                id="q0",
                text=expanded,
                intent=intent,
                weight=1.0,
                parent_terms=terms,
            )
        )

    # ── Estimate effort ───────────────────────────────────────────────────
    effort = "high" if is_complex else ("medium" if intent in ("comparison", "list") else "low")

    return QueryPlan(
        original=query,
        intent=intent,
        sub_queries=sub_queries,
        is_complex=is_complex,
        estimated_effort=effort,
    )


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — SEARCH PROVIDER ROUTING  (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

# Known provider specializations (no LLM needed — just a domain map)
PROVIDER_TAGS: dict[str, list[str]] = {
    "duckduckgo": ["general", "news", "products", "factual", "interrogative", "list"],
    "hackernews": ["technology", "startups", "product", "discussion", "general"],
    "wikipedia": ["factual", "background", "history", "definition", "overview"],
    "arxiv": ["research", "academic", "technical", "paper", "science", "algorithm"],
    "arxiv_": ["research", "academic", "technical", "paper", "science", "algorithm"],
    "reddit": ["discussion", "opinion", "experience", "review", "comparison"],
    "google": ["general", "news", "products", "factual"],
}

# Domain → canonical name mapping for known high-authority sources
AUTHORITATIVE_DOMAINS: dict[str, float] = {
    "arxiv.org": 1.5,
    "nature.com": 1.5,
    "science.org": 1.5,
    "wikipedia.org": 1.2,
    "github.com": 1.3,
    "stackoverflow.com": 1.2,
    "medium.com": 1.0,
    "zdnet.com": 1.0,
    "theverge.com": 1.0,
    "wired.com": 1.0,
    "reuters.com": 1.2,
    "apnews.com": 1.2,
    "bbc.com": 1.1,
    "nytimes.com": 1.1,
    "economist.com": 1.3,
}


def route_providers(query: str, intent: str) -> list[str]:
    """Pick the 2–4 best providers for this query intent."""
    # Base provider always included
    providers = ["duckduckgo"]

    # Add intent-specific providers
    if intent in ("factual", "interrogative"):
        providers.append("wikipedia")
        providers.append("hackernews")  # HN matches tech-focused factual queries well
    if intent in ("list", "comparison"):
        providers.append("reddit")
    if any(t in query.lower() for t in ["research", "paper", "study", "academic", "science"]):
        providers.extend(["arxiv", "arxiv_"])
    if any(t in query.lower() for t in ["startup", "product", "launch", "tech", "hacker"]):
        providers.append("hackernews")
    if intent == "comparison":
        providers.append("reddit")

    return list(dict.fromkeys(providers))  # deduplicate preserving order


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — PARALLEL SUBAGENTS  (zero LLM, threads instead of LLMs)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SubAgentResult:
    sub_query_id: str
    search_results: list[SearchResult]
    fetched_results: list[FetchResult]
    entity_facts: list[dict]  # extracted name/date/number triples
    coverage_score: float  # 0–1: how well this branch covered its topic
    warnings: list[str]


def _extract_entities(text: str) -> list[dict]:
    """
    Extract named entities and structured facts without LLM.
    Uses regex patterns + capitalization heuristics + numeric extraction.
    """
    facts = []

    # Extract capitalized phrases (potential entities)
    for match in _RE_ENTITY_CAPTURE.finditer(text):
        phrase = match.group(1).strip()
        if len(phrase) > 3 and phrase.lower() not in {
            "the",
            "this",
            "that",
            "they",
            "there",
        }:
            facts.append({"type": "entity", "value": phrase, "context": text[max(0, match.start() - 40) : match.end() + 40]})

    # Extract years/dates
    for match in _RE_YEAR.finditer(text):
        ctx_start = max(0, match.start() - 30)
        ctx_end = min(len(text), match.end() + 30)
        facts.append({"type": "date", "value": match.group(), "context": text[ctx_start:ctx_end]})

    # Extract numbers with units
    number_pattern = re.compile(
        r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|billion|million|thousand|"
        r"dollars?|users?|customers?|times|daily|monthly|yearly|years?)\b",
        re.I,
    )
    for match in number_pattern.finditer(text):
        facts.append({"type": "stat", "value": match.group(), "context": text[max(0, match.start() - 20) : min(len(text), match.end() + 20)]})

    return facts


def _coverage_score(query: SubQuery, fetched: list[FetchResult]) -> float:
    """Score how well a set of results covers the sub-query topic."""
    if not fetched:
        return 0.0
    query_terms = query.parent_terms or {t.lower() for t in _RE_TERM_TOKEN.findall(query.text)}

    scores = []
    for r in fetched:
        if not r.text:
            continue
        result_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(r.text)}
        overlap = len(query_terms & result_terms)
        max_possible = len(query_terms)
        scores.append(overlap / max_possible if max_possible else 0)

    return min(1.0, sum(scores) / len(scores) * 1.5)


def run_subagent(
    sub_query: SubQuery,
    providers: list[str],
    timeout: int = 20,
    max_chars: int = 4000,
) -> SubAgentResult:
    """
    A 'sub-agent' is just a thread. It searches, fetches, and extracts
    structured facts — all without any LLM.
    """
    warnings = []

    # 1. Search via routed providers
    all_results: list[SearchResult] = []
    for provider in providers[:3]:  # cap at 3 providers per sub-agent
        try:
            results = search_web(sub_query.text, max_results=5, timeout=timeout)
            all_results.extend(results)
        except Exception as exc:
            warnings.append(f"provider_{provider}_error:{exc}")

    # ── Zero-result fallback: retry with extracted keywords ──────────────
    if not all_results:
        keyword_q = _extract_keywords(sub_query.text)
        if keyword_q and keyword_q != sub_query.text:
            try:
                kw_results = search_web(keyword_q, max_results=5, timeout=timeout)
                if kw_results:
                    all_results.extend(kw_results)
                    warnings.append(f"keyword_fallback:used '{keyword_q}'")
            except Exception as exc:
                warnings.append(f"keyword_fallback_error:{exc}")

    # ── Second fallback for factual intent: bare-minimum keywords ────────
    if not all_results and sub_query.intent == "factual":
        # Extract only the most meaningful terms (3+ chars, not stopwords)
        min_keywords = _extract_keywords(sub_query.text)
        # Fall back to just the first 4 meaningful words
        kw_parts = min_keywords.split()
        if len(kw_parts) > 3:
            short_q = " ".join(kw_parts[:4])
            try:
                hn_results = search_web(short_q, max_results=5, timeout=timeout)
                if hn_results:
                    all_results.extend(hn_results)
                    warnings.append(f"hn_factual_fallback:used '{short_q}'")
            except Exception as exc:
                warnings.append(f"hn_factual_fallback_error:{exc}")

    # 2. Deduplicate by canonical URL
    seen_urls: set[str] = set()
    unique_results: list[SearchResult] = []
    for r in all_results:
        url_key = r.url.split("?")[0].rstrip("/")
        if url_key not in seen_urls:
            seen_urls.add(url_key)
            unique_results.append(r)
    all_results = unique_results

    # 3. Fetch top results in parallel
    fetched: list[FetchResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        fut_map = {
            pool.submit(fetch_url, r.url, timeout=timeout, max_chars=max_chars, use_jina=True): r
            for r in all_results[:6]
        }
        for fut in concurrent.futures.as_completed(fut_map):
            try:
                fetched.append(fut.result())
            except Exception as exc:
                sr = fut_map[fut]
                warnings.append(f"fetch_error:{sr.url[:50]}:{exc}")

    # 4. Extract entities and structured facts
    all_facts: list[dict] = []
    for r in fetched:
        if r.text:
            all_facts.extend(_extract_entities(r.text))

    coverage = _coverage_score(sub_query, fetched)

    return SubAgentResult(
        sub_query_id=sub_query.id,
        search_results=all_results,
        fetched_results=fetched,
        entity_facts=all_facts,
        coverage_score=coverage,
        warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4 — BM25 FUSION + CROSS-SOURCE RANKING  (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ScoredSource:
    result: FetchResult
    bm25_score: float
    authority_boost: float
    coverage_boost: float
    total_score: float


class BM25Scorer:
    """
    Classic BM25 ranking — no LLM needed.
    Standard: Okapi BM25 with k1=1.5, b=0.75.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def _tokenize(self, text: str) -> list[str]:
        return [t.lower() for t in _RE_TERM_TOKEN.findall(text)]

    def _avgdl(self, corpus: list[list[str]]) -> float:
        total = sum(len(doc) for doc in corpus)
        return total / len(corpus) if corpus else 0

    def score(self, query: str, documents: list[str]) -> list[float]:
        """
        Returns BM25 scores for each document relative to the query.
        """
        query_terms = self._tokenize(query)
        docs_tok = [self._tokenize(d) for d in documents]
        avgdl = self._avgdl(docs_tok)
        N = len(documents)

        scores = []
        for doc_tok in docs_tok:
            score = 0.0
            doc_len = len(doc_tok)
            term_freq: dict[str, int] = collections.Counter(doc_tok)
            doc_freq: dict[str, int] = {}
            for term in set(doc_tok):
                doc_freq[term] = 1  # simplified: treat as appearing in this doc only

            for term in query_terms:
                tf = term_freq.get(term, 0)
                if tf == 0:
                    continue
                # df: number of docs containing term (simplified single-doc version)
                df = 1
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / (avgdl + 1e-6))
                score += idf * (numerator / (denominator + 1e-6))
            scores.append(score)
        return scores


def _authority_boost(url: str) -> float:
    """Boost scores for known high-authority domains."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    return AUTHORITATIVE_DOMAINS.get(domain, 1.0)


def rank_sources(
    results: list[SubAgentResult],
    query: str,
    intent: str,
) -> list[ScoredSource]:
    """
    Rank all fetched sources across all sub-agents using:
    1. BM25 score against original query + intent terms
    2. Authority boost from known domains
    3. Coverage boost from the sub-agent that fetched them
    """
    all_fetched: list[tuple[FetchResult, float, SubAgentResult]] = []
    for sub_result in results:
        for fr in sub_result.fetched_results:
            if not fr.text:
                continue
            all_fetched.append((fr, sub_result.coverage_score, sub_result))

    if not all_fetched:
        return []

    documents = [fr.text or "" for fr, _, _ in all_fetched]
    enrich_query = f"{query} {intent}"
    bm25 = BM25Scorer()
    bm25_scores = bm25.score(enrich_query, documents)

    scored: list[ScoredSource] = []
    for (fr, coverage, sub_result), bm25_score in zip(all_fetched, bm25_scores):
        authority = _authority_boost(fr.url or "")
        # Normalize bm25 score to 0–1 range
        max_bm = max(bm25_scores) if max(bm25_scores) > 0 else 1
        norm_bm = bm25_score / max_bm
        total = 0.4 * norm_bm + 0.3 * authority + 0.3 * coverage
        scored.append(
            ScoredSource(
                result=fr,
                bm25_score=bm25_score,
                authority_boost=authority,
                coverage_boost=coverage,
                total_score=total,
            )
        )

    scored.sort(key=lambda x: x.total_score, reverse=True)
    return scored


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5 — EVIDENCE EXTRACTION  (zero LLM, extractive summarization)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceClaim:
    sentence: str
    source_url: str
    source_title: str
    claim_type: str  # "fact" | "stat" | "date" | "entity" | "quote"
    relevance_score: float
    is_contradictory: bool = False  # set by contradiction detector


def extract_evidence(
    scored_sources: list[ScoredSource],
    query: str,
    intent: str,
    max_claims: int = 20,
) -> list[EvidenceClaim]:
    """
    Extractive summarization without LLM:
    1. Score every sentence in every source using BM25 overlap with query
    2. Deduplicate near-identical sentences (hash-based)
    3. Boost sentences with entities, statistics, dates
    4. Select top-N by composite score
    """
    q_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(query)}
    intent_terms = {"factual": ["report", "found", "discovered", "announced", "revealed"],
                    "comparison": ["better", "worse", "advantage", "disadvantage", "pros", "cons", "differ"],
                    "list": ["include", "such as", "example", "type", "category"],
                    "interrogative": ["percent", "%", "million", "billion", "number", "total", "average"],
                    "general": ["important", "key", "main", "significant"]}
    boost_terms = set(intent_terms.get(intent, []))

    all_sentences: list[tuple[str, FetchResult, float]] = []
    seen_hashes: set[str] = set()

    for scored in scored_sources:
        fr = scored.result
        if not fr.text:
            continue
        for sent in _RE_SENTENCE_SPLIT.split(fr.text):
            sent = sent.strip()
            if len(sent) < 30 or len(sent) > 600:
                continue
            # Deduplicate by sentence hash
            h = hashlib.md5(sent.lower().encode()).hexdigest()[:12]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            s_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(sent)}
            overlap = len(q_terms & s_terms)
            boost = len(boost_terms & s_terms)
            entity_count = len(_RE_ENTITY_CAPTURE.findall(sent))
            stat_count = len(re.findall(r"\d+(?:\.\d+)?%", sent))

            # Composite relevance score
            relevance = (overlap * 1.0) + (boost * 0.5) + (entity_count * 0.3) + (stat_count * 0.4)
            relevance = relevance / max(1, len(s_terms))

            if overlap > 0:
                all_sentences.append((sent, fr, relevance))

    # Sort by relevance and pick top-N
    all_sentences.sort(key=lambda x: x[2], reverse=True)

    claims: list[EvidenceClaim] = []
    for sent, fr, relevance in all_sentences[:max_claims]:
        # Classify claim type
        if re.search(r"\d+(?:\.\d+)?%", sent) or re.search(r"\d+ (million|billion|thousand)", sent, re.I):
            claim_type = "stat"
        elif _RE_YEAR.search(sent):
            claim_type = "date"
        elif _RE_ENTITY_CAPTURE.findall(sent):
            claim_type = "entity"
        elif '"' in sent:
            claim_type = "quote"
        else:
            claim_type = "fact"

        claims.append(
            EvidenceClaim(
                sentence=sent,
                source_url=fr.final_url or fr.url,
                source_title=fr.title,
                claim_type=claim_type,
                relevance_score=relevance,
            )
        )

    return claims


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 6 — CONTRADICTION DETECTION  (zero LLM, statistical)
# ═══════════════════════════════════════════════════════════════════════════

def detect_contradictions(claims: list[EvidenceClaim]) -> list[tuple[EvidenceClaim, EvidenceClaim]]:
    """
    Find pairs of claims that likely contradict each other.
    Zero LLM: uses numeric divergence + opposing keyword detection.
    """
    OPPOSING_PAIRS = [
        ("increase", "decrease"),
        ("more", "less"),
        ("better", "worse"),
        ("higher", "lower"),
        ("up", "down"),
        ("positive", "negative"),
        ("supports", "opposes"),
        ("agree", "disagree"),
        ("yes", "no"),
    ]

    contradictions = []
    for i, c1 in enumerate(claims):
        for c2 in claims[i + 1 :]:
            s1, s2 = c1.sentence.lower(), c2.sentence.lower()
            # Check for numeric divergence on same stat
            nums1 = re.findall(r"\d+(?:\.\d+)?%", s1)
            nums2 = re.findall(r"\d+(?:\.\d+)?%", s2)
            if nums1 and nums2:
                # Numeric divergence: same stat type (percentage or raw number) diverging > 30pp
                # nums1/nums2 are already extracted WITH the % sign intact
                has_pct1 = "%" in nums1[0]
                has_pct2 = "%" in nums2[0]
                if has_pct1 == has_pct2:
                    try:
                        v1 = float(nums1[0].replace("%", ""))
                        v2 = float(nums2[0].replace("%", ""))
                        diff = abs(v1 - v2)
                        if has_pct1 and diff > 30:
                            # Compute semantic overlap: strip stopwords and compare content words
                            STOPWORDS = {"the","and","for","are","but","not","you","all","can","her",
                                         "was","one","our","out","day","get","has","him","his","how",
                                         "its","may","new","now","old","see","two","way","who","boy",
                                         "did","she","use","via","com","net","org","http","https","www",
                                         "that","from","have","been","were","said","also","they","this",
                                         "what","than","has","with","their","about","into","over","after"}
                            s1_words = {w for w in s1.split() if w not in STOPWORDS and len(w) > 2}
                            s2_words = {w for w in s2.split() if w not in STOPWORDS and len(w) > 2}
                            overlap = len(s1_words & s2_words) / max(1, min(len(s1_words), len(s2_words)))
                            if overlap > 0.25:
                                contradictions.append((c1, c2))
                                c1.is_contradictory = True
                                c2.is_contradictory = True
                                continue
                    except ValueError:
                        pass
            # Check for opposing keywords
            for pos, neg in OPPOSING_PAIRS:
                if pos in s1 and neg in s2:
                    contradictions.append((c1, c2))
                    c1.is_contradictory = True
                    c2.is_contradictory = True
                    break

    return contradictions


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 7 — REPORT GENERATION  (zero LLM, templated + extractive)
# ═══════════════════════════════════════════════════════════════════════════

INTENT_TEMPLATES = {
    "factual": {
        "header": "## Key Facts\n",
        "bullet": "• **{claim}** — [{source}]({url})\n",
        "section_max": 6,
    },
    "comparison": {
        "header": "## Comparison Findings\n",
        "bullet": "• **{claim}** — [{source}]({url})\n",
        "section_max": 8,
    },
    "list": {
        "header": "## Comprehensive Findings\n",
        "bullet": "• **{claim}** — [{source}]({url})\n",
        "section_max": 10,
    },
    "interrogative": {
        "header": "## Answers\n",
        "bullet": "• **{claim}** — [{source}]({url})\n",
        "section_max": 8,
    },
    "general": {
        "header": "## Key Findings\n",
        "bullet": "• **{claim}** — [{source}]({url})\n",
        "section_max": 8,
    },
}


def build_report(
    query: str,
    plan: QueryPlan,
    sub_results: list[SubAgentResult],
    scored_sources: list[ScoredSource],
    claims: list[EvidenceClaim],
    contradictions: list[tuple[EvidenceClaim, EvidenceClaim]],
) -> dict[str, Any]:
    """
    Build the final research report without any LLM.
    Structure:
    1. Executive Summary (keyword-extracted from top sentences)
    2. Key Findings (extracted claims grouped by type)
    3. Evidence (all claims with citations)
    4. Contradictions (flagged conflicts)
    5. Sources (full source list ranked)
    6. Research Metadata (plan, effort, coverage)
    """

    template = INTENT_TEMPLATES.get(plan.intent, INTENT_TEMPLATES["general"])

    # ── 1. Executive Summary ──────────────────────────────────────────────
    # Extract summary from top 3 ranked sentences (no LLM paraphrasing)
    exec_sents = [c.sentence for c in claims[:5] if c.relevance_score > 0]
    exec_summary = " ".join(exec_sents[:3]) if exec_sents else "No high-confidence findings retrieved."
    if len(exec_summary) > 600:
        exec_summary = exec_summary[:597].rsplit(" ", 1)[0] + "..."

    # ── 2. Key Findings ──────────────────────────────────────────────────
    # Group claims by type, pick highest-scored per type
    by_type: dict[str, list[EvidenceClaim]] = {}
    for c in claims:
        by_type.setdefault(c.claim_type, []).append(c)

    findings_lines = [template["header"]]
    for claim_type, type_claims in by_type.items():
        type_claims.sort(key=lambda x: x.relevance_score, reverse=True)
        for c in type_claims[:3]:
            findings_lines.append(
                template["bullet"].format(
                    claim=_truncate(c.sentence, 200),
                    source=c.source_title or c.source_url,
                    url=c.source_url,
                )
            )
        if len(findings_lines) > template["section_max"] + 2:
            break

    # ── 3. Contradictions ────────────────────────────────────────────────
    contradiction_lines = []
    if contradictions:
        contradiction_lines.append("## ⚠ Contradictions Detected\n")
        contradiction_lines.append(
            "_Multiple sources disagree. Verify independently._\n"
        )
        for c1, c2 in contradictions[:5]:
            contradiction_lines.append(
                f"- **Conflict**: \"{_truncate(c1.sentence, 150)}\" vs "
                f"\"{_truncate(c2.sentence, 150)}\"\n"
            )
            contradiction_lines.append(
                f"  Sources: [{c1.source_title}]({c1.source_url}) | "
                f"[{c2.source_title}]({c2.source_url})\n"
            )

    # ── 4. All Evidence ───────────────────────────────────────────────────
    evidence_lines = ["## All Evidence\n"]
    for i, c in enumerate(claims, 1):
        flag = " ⚠️" if c.is_contradictory else ""
        evidence_lines.append(
            f"{i}. [{c.claim_type.upper()}{flag}] {c.sentence}\n"
            f"   Source: [{c.source_title}]({c.source_url})\n"
        )

    # ── 5. Sources ────────────────────────────────────────────────────────
    source_lines = ["## Sources\n"]
    for i, scored in enumerate(scored_sources[:15], 1):
        fr = scored.result
        source_lines.append(
            f"{i}. [{fr.title}]({fr.final_url or fr.url})  \n"
            f"   Quality: {fr.quality_score():.1f} | "
            f"BM25: {scored.bm25_score:.2f} | "
            f"Authority: {scored.authority_boost:.1f}x\n"
        )

    # ── 6. Metadata ───────────────────────────────────────────────────────
    total_sources = sum(len(sr.fetched_results) for sr in sub_results)
    total_warnings = sum(len(sr.warnings) for sr in sub_results)
    avg_coverage = sum(sr.coverage_score for sr in sub_results) / len(sub_results) if sub_results else 0

    metadata_lines = [
        "## Research Metadata\n",
        f"- **Plan**: {plan.branch_count} branches, effort={plan.estimated_effort}\n",
        f"- **Intent**: {plan.intent}\n",
        f"- **Sub-queries**: {', '.join(q.text[:60] for q in plan.sub_queries)}\n",
        f"- **Total sources fetched**: {total_sources}\n",
        f"- **Average coverage**: {avg_coverage:.0%}\n",
        f"- **Contradictions found**: {len(contradictions)}\n",
        f"- **Fetch warnings**: {total_warnings}\n",
    ]

    # ── Assemble final report ────────────────────────────────────────────
    report_sections = [
        f"# Deep Research: {query}",
        f"_Generated: {email.utils.formatdate(usegmt=True)}_",
        "",
        "## Executive Summary\n",
        exec_summary,
        "",
        *findings_lines,
        "",
        *contradiction_lines,
        "" if contradiction_lines else "\n",
        *evidence_lines,
        "",
        *source_lines,
        "",
        *metadata_lines,
    ]

    return {
        "report_markdown": "\n".join(report_sections),
        "report_json": {
            "query": query,
            "generated_at": email.utils.formatdate(usegmt=True),
            "plan": {
                "original": plan.original,
                "intent": plan.intent,
                "is_complex": plan.is_complex,
                "effort": plan.estimated_effort,
                "branches": [_subquery_to_dict(q) for q in plan.sub_queries],
            },
            "executive_summary": exec_summary,
            "findings": [
                {
                    "type": c.claim_type,
                    "claim": c.sentence,
                    "source": c.source_url,
                    "source_title": c.source_title,
                    "relevance": round(c.relevance_score, 3),
                    "contradiction": c.is_contradictory,
                }
                for c in claims[:20]
            ],
            "contradictions": [
                {
                    "claim_a": c1.sentence,
                    "claim_b": c2.sentence,
                    "source_a": c1.source_url,
                    "source_b": c2.source_url,
                }
                for c1, c2 in contradictions
            ],
            "sources": [
                {
                    "title": s.result.title,
                    "url": s.result.final_url or s.result.url,
                    "quality_score": s.result.quality_score(),
                    "total_score": round(s.total_score, 3),
                    "bm25_score": round(s.bm25_score, 3),
                    "authority_boost": s.authority_boost,
                }
                for s in scored_sources[:15]
            ],
            "metadata": {
                "total_sources_fetched": total_sources,
                "average_coverage": round(avg_coverage, 3),
                "contradictions_found": len(contradictions),
                "total_warnings": total_warnings,
            },
        },
    }


def _subquery_to_dict(sq: SubQuery) -> dict[str, Any]:
    """Convert SubQuery NamedTuple to JSON-safe dict (parent_terms is a set)."""
    return {
        "id": sq.id,
        "text": sq.text,
        "intent": sq.intent,
        "weight": sq.weight,
        "parent_terms": list(sq.parent_terms),
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rsplit(" ", 1)[0] + "..."


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 8 — ITERATIVE REFINEMENT LOOP  (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

def expand_query_terms(original_query: str, sub_results: list[SubAgentResult]) -> list[str]:
    """
    Expand the search space by extracting co-occurring terms from
    top-performing sub-agent results. Zero LLM.
    Algorithm: TF-IDF on fetched text → pick top terms not in original query.
    """
    from collections import Counter

    original_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(original_query)}

    # Collect all text from top sub-agents (by coverage score)
    sub_results_sorted = sorted(sub_results, key=lambda x: x.coverage_score, reverse=True)
    top_texts = []
    for sr in sub_results_sorted[:2]:
        for fr in sr.fetched_results:
            if fr.text:
                top_texts.append(fr.text)

    if not top_texts:
        return []

    # Compute term frequencies
    all_text = " ".join(top_texts)
    all_tokens = [t.lower() for t in _RE_TERM_TOKEN.findall(all_text)]

    # Filter: not in original query, not a stopword
    STOPWORDS = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
        "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
        "its", "may", "new", "now", "old", "see", "two", "way", "who", "boy",
        "did", "she", "use", "via", "com", "net", "org", "http", "https", "www",
    }
    candidate_terms = [t for t in all_tokens if t not in original_terms and t not in STOPWORDS and len(t) > 4]
    term_freq = Counter(candidate_terms)

    # Pick top 5 emerging terms by frequency
    top_terms = [t for t, _ in term_freq.most_common(5)]

    # Generate expanded queries
    expanded_queries = [f"{original_query} {term}" for term in top_terms]
    return expanded_queries


def refine_with_additional_search(
    plan: QueryPlan,
    initial_sub_results: list[SubAgentResult],
    scored_sources: list[ScoredSource],
    max_refinement_loops: int = 1,
    timeout: int = 20,
) -> list[SubAgentResult]:
    """
    If coverage is low, do one refinement loop with expanded queries.
    Zero LLM.
    """
    avg_coverage = sum(sr.coverage_score for sr in initial_sub_results) / len(initial_sub_results) if initial_sub_results else 0

    if avg_coverage > 0.5 or max_refinement_loops <= 0:
        return initial_sub_results

    expanded = expand_query_terms(plan.original, initial_sub_results)
    extra_results: list[SubAgentResult] = []

    for eq in expanded[:2]:  # max 2 extra branches
        providers = route_providers(eq, plan.intent)
        sq = SubQuery(
            id=f"refine_{len(initial_sub_results) + len(extra_results)}",
            text=eq,
            intent=plan.intent,
            weight=0.3,
            parent_terms={t.lower() for t in _RE_TERM_TOKEN.findall(eq)},
        )
        extra_results.append(run_subagent(sq, providers, timeout=timeout))

    return initial_sub_results + extra_results


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT — deep_research()
# ═══════════════════════════════════════════════════════════════════════════

def deep_research(
    query: str,
    *,
    max_results: int = 8,
    timeout: int = 20,
    max_chars: int = 6000,
    refinement_loops: int = 1,
    guard: InputGuard | None = None,
) -> dict[str, Any]:
    """
    AgentWeb's deep research pipeline. Zero LLM calls.

    Pipeline:
      Query Plan → Sub-Agent Dispatch → Parallel Search/Fetch →
      BM25 Ranking → Evidence Extraction → Contradiction Detection →
      (Optional) Refinement Loop → Report Generation

    Returns a dict with both 'report_markdown' (human-readable) and
    'report_json' (structured).
    """
    start_time = time.time()

    # 0. Safety guard
    if guard is None:
        guard = InputGuard()
    guard.validate_text(query)

    # 1. Query decomposition
    plan = decompose_query(query)
    providers = route_providers(query, plan.intent)

    # 2. Dispatch sub-agents in parallel (one per sub-query)
    branch_count = plan.branch_count
    with concurrent.futures.ThreadPoolExecutor(max_workers=branch_count) as pool:
        fut_map = {
            pool.submit(run_subagent, sq, providers, timeout, max_chars): sq
            for sq in plan.sub_queries
        }
        sub_results: list[SubAgentResult] = []
        for fut in concurrent.futures.as_completed(fut_map):
            try:
                sub_results.append(fut.result())
            except Exception as exc:
                sq = fut_map[fut]
                sub_results.append(
                    SubAgentResult(
                        sub_query_id=sq.id,
                        search_results=[],
                        fetched_results=[],
                        entity_facts=[],
                        coverage_score=0.0,
                        warnings=[f"subagent_failed:{exc}"],
                    )
                )

    # 3. Refinement loop (if needed)
    sub_results = refine_with_additional_search(
        plan, sub_results, [], max_refinement_loops=refinement_loops, timeout=timeout
    )

    # 4. Rank all sources
    scored_sources = rank_sources(sub_results, query, plan.intent)

    # 5. Extract evidence
    claims = extract_evidence(scored_sources, query, plan.intent, max_claims=20)

    # 6. Detect contradictions
    contradictions = detect_contradictions(claims)

    # 7. Build report
    report = build_report(query, plan, sub_results, scored_sources, claims, contradictions)

    elapsed = time.time() - start_time

    return {
        "query": query,
        "elapsed_seconds": round(elapsed, 1),
        "report_markdown": report["report_markdown"],
        "report_json": report["report_json"],
    }
