"""
AgentWeb Deep Research — NO LLM ARCHITECTURE
==============================================
Inspired by: Claude (orchestrator-worker), ChatGPT (plan-then-execute), Perplexity (iterative refine).
Constraint: Zero LLM API calls inside AgentWeb. All reasoning is classical NLP + graph algorithms.

Semantic Routing (new in 0.1.7):
  Uses SemanticRouter to classify queries into provider categories (arXiv, HN,
  Wikipedia, Reddit) via term-overlap scoring with multi-word phrase bonuses.
  Falls back to general web search (Jina Search API + DuckDuckGo) when no
  category scores above the 0.10 threshold — fixing the "H1 centro americano
  coffee" class of failures where keyword-only routing returned nothing.

This module lives at agentweb/deep_research.py and is imported by cli.py.
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
import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple

# AgentWeb's own imports
from agentweb.core import fetch_url, search_by_provider, search_web, FetchResult, SearchResult, compute_novelty_scores
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

# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC ROUTER — classify queries into provider categories
# ═══════════════════════════════════════════════════════════════════════════


class SemanticRouter:
    """Classify queries into search provider categories using term-overlap scoring.

    Zero external dependencies — uses token overlap + phrase matching between the
    query and each category's seed profile.  If no category scores above the
    fallback threshold, routes to ``"general"`` web search.

    Design:
    - **Single-word seeds** matched against query tokens (2+ chars, no stopwords)
    - **Multi-word seeds** matched as exact substrings against the query
    - Short meaningful tokens (``hn``, ``ai``, ``yc``) are captured by the 2-char
      minimum — common English 2-letter words are in the stopword list.
    """

    # Custom short-token regex: 2+ chars (3+ is too restrictive for HN, AI, YC, etc.)
    _RE_TOKEN = re.compile(r"[a-zA-Z0-9]{2,}")

    # Seed terms per provider category.
    # Single words: matched against query tokens (2+ chars, filtered).
    # Multi-word phrases: matched exactly against query (substring check).
    CATEGORY_SEEDS: dict[str, set[str]] = {
        "arxiv": {
            "paper", "research", "study", "academic", "preprint",
            "publication", "scientific", "scholar", "doi", "proceedings",
            "conference", "journal", "experiment", "methodology",
            "benchmark", "dataset", "novel", "theory", "algorithm",
            "sota", "pretrained", "fine", "tune", "architecture", "corpus",
            "llm", "transformer", "nlp",
            "state of the art", "we propose", "results show",
            "empirical", "evaluation", "neural network",
            "deep learning", "computer vision", "reinforcement learning",
            "machine learning",
        },
        "hackernews": {
            "hackernews", "startup", "founder", "venture", "launch",
            "bootstrapped", "indie", "postmortem", "pivot",
            "ycombinator",
            "hacker news", "y combinator",
            "series a", "side project", "build in public",
            "tech crunch", "startup school", "seed round",
            "show hn", "ask hn", "hn",
        },
        "wikipedia": {
            "history", "definition", "overview", "background",
            "meaning", "explain", "define", "origin", "etymology",
            "biography", "geography", "capital", "population",
            "timeline", "concept", "terminology", "located", "born",
            "founded", "demographics", "country", "continent",
            "what is", "who is", "where is", "also known as",
        },
        "reddit": {
            "reddit", "subreddit", "opinion", "opinions",
            "review", "reviews", "recommendation", "recommendations",
            "recommend", "discussion", "discussions", "advice",
            "troubleshooting", "suggestion", "suggestions",
            "ama", "eli5", "tifu", "aita",
            "anyone else", "thoughts on", "what do you think",
            "does anyone", "has anyone", "experience with",
            "worth it", "is it good", "should i buy",
            "worth", "buy", "rating",
        },
        "twitter": {
            "twitter", "xcom", "tweet", "announcement", "breaking",
            "trending", "viral", "elon", "musk",
            "just announced", "as of", "thread:",
            "https://x.com/", "https://twitter.com/",
            "whats happening", "latest news",
        },
        "github": {
            "github", "repository", "repo", "open source",
            "library", "framework", "tool", "package",
            "implementation", "pypi", "npm", "crates",
            "source code", "api wrapper", "cli tool",
            "docker image", "plugin", "extension",
            "github repo", "github project",
        },
    }

    # Common English words that shouldn't count as meaningful matches
    _STOPWORDS: frozenset[str] = frozenset({
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

    _GENERAL_FALLBACK_THRESHOLD = 0.10

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        """Extract meaningful tokens (2+ chars, no stopwords)."""
        return {m.group().lower() for m in cls._RE_TOKEN.finditer(text)
                if m.group().lower() not in cls._STOPWORDS}

    def classify(self, query: str) -> list[tuple[str, float]]:
        """Classify a query into provider categories.

        Returns a list of ``(provider_name, confidence)`` pairs sorted by
        confidence descending.  ``"general"`` is always included as a
        last-resort provider.
        """
        query_lower = query.lower()
        tokens = self._tokenize(query_lower)
        num_tokens = len(tokens)

        if not tokens:
            return [("general", 1.0)]

        scores: list[tuple[str, float]] = []
        for provider, seeds in self.CATEGORY_SEEDS.items():
            word_hits = 0
            phrase_hits = 0

            for seed in seeds:
                seed_lower = seed.lower()
                if " " in seed:
                    # Multi-word seed: exact phrase match
                    if seed_lower in query_lower:
                        phrase_hits += 1
                else:
                    # Single-word seed: token match
                    if len(seed_lower) >= 2 and seed_lower not in self._STOPWORDS:
                        if seed_lower in tokens:
                            word_hits += 1

            # Score: fraction of query tokens matched + capped phrase bonus
            word_frac = word_hits / num_tokens
            phrase_frac = min(phrase_hits, 3) / 3  # capped at 3 phrases

            # Weighted: words 60%, phrases 40%
            total = min(word_frac * 0.6 + phrase_frac * 0.4, 1.0)
            scores.append((provider, round(total, 4)))

        # Sort by confidence desc
        scores.sort(key=lambda x: x[1], reverse=True)

        # Below threshold -> route purely to general web search
        if scores[0][1] < self._GENERAL_FALLBACK_THRESHOLD:
            return [("general", 1.0)]

        # Return all providers within 30% of the top score
        top_score = scores[0][1]
        result = [(p, s) for p, s in scores if s >= top_score * 0.3]

        # Always append general as a co-provider for safety
        if not any(p == "general" for p, _ in result):
            result.append(("general", self._GENERAL_FALLBACK_THRESHOLD))

        return result
_ROUTER = SemanticRouter()  # module-level singleton


def semantic_route_providers(query: str) -> list[str]:
    """Route a query to providers using the SemanticRouter.

    Returns a deduplicated list of provider names ordered by confidence.
    Always includes a general web search fallback.
    """
    classified = _ROUTER.classify(query)
    return [p for p, _ in classified]


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
                    # Entity-specific branch: preserve original query context
                    entity = unique_entities[0]
                    ctx = _simplify_query(query) or query
                    ctx = re.sub(r'\b(compare|versus|vs\.?|or|and)\b', '', ctx, flags=re.I).strip()
                    for other_entity in (e for e in unique_entities if e != entity):
                        ctx = re.sub(r'\b' + re.escape(other_entity) + r'\b', '', ctx, flags=re.I).strip()
                    ctx = re.sub(r'\s+', ' ', ctx).strip()
                    branch_q = f"{entity} {ctx}" if ctx else f"{entity} deep research features how it works"
                elif i == 1 and len(unique_entities) > 1:
                    entity = unique_entities[1]
                    ctx = _simplify_query(query) or query
                    ctx = re.sub(r'\b(compare|versus|vs\.?|or|and)\b', '', ctx, flags=re.I).strip()
                    for other_entity in (e for e in unique_entities if e != entity):
                        ctx = re.sub(r'\b' + re.escape(other_entity) + r'\b', '', ctx, flags=re.I).strip()
                    ctx = re.sub(r'\s+', ' ', ctx).strip()
                    branch_q = f"{entity} {ctx}" if ctx else f"{entity} deep research features how it works"
                elif i == 2 and len(unique_entities) > 2:
                    entity = unique_entities[2]
                    ctx = _simplify_query(query) or query
                    ctx = re.sub(r'\b(compare|versus|vs\.?|or|and)\b', '', ctx, flags=re.I).strip()
                    for other_entity in (e for e in unique_entities if e != entity):
                        ctx = re.sub(r'\b' + re.escape(other_entity) + r'\b', '', ctx, flags=re.I).strip()
                    ctx = re.sub(r'\s+', ' ', ctx).strip()
                    branch_q = f"{entity} {ctx}" if ctx else f"{entity} deep research features how it works"
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
    "reddit": ["discussion", "opinion", "experience", "review", "comparison"],
    "twitter": ["news", "announcement", "trending", "breaking", "realtime", "general"],
    "github": ["technical", "tool", "library", "implementation", "open_source", "code"],
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
    """Pick the best providers for this query.

    Uses the SemanticRouter to classify the query by term overlap with
    each category's seed profile.  Falls back to intent-based heuristics
    when semantic confidence is low.

    Always includes a general web search provider as a safety net.
    """
    # Semantic classification
    semantic = _ROUTER.classify(query)

    # Extract provider names sorted by confidence
    providers: list[str] = []
    seen: set[str] = set()
    for provider, confidence in semantic:
        if provider not in seen:
            seen.add(provider)
            providers.append(provider)

    # If semantic only gave "general", supplement with intent-based hints
    if providers == ["general"]:
        if intent in ("factual", "interrogative"):
            providers.append("wikipedia")
        if intent in ("list", "comparison"):
            providers.append("reddit")
        if any(t in query.lower() for t in ["paper", "research", "academic", "science", "arxiv"]):
            providers.append("arxiv")
        if any(t in query.lower() for t in ["startup", "hacker", "tech", "launch"]):
            providers.append("hackernews")

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
    Uses regex patterns + capitalization heuristics + numeric extraction + table parsing.
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
    for match in _RE_STAT.finditer(text):
        facts.append({"type": "stat", "value": match.group(), "context": text[max(0, match.start() - 20) : min(len(text), match.end() + 20)]})

    # Extract currency values ($X, $X.XX)
    for match in _RE_PRICE.finditer(text):
        facts.append({"type": "stat", "value": match.group(), "context": text[max(0, match.start() - 20) : min(len(text), match.end() + 20)]})

    # Extract markdown table rows (pipe-delimited) — each row is a structured fact
    # The first row is the header; subsequent rows contain data
    lines = text.splitlines()
    in_table = False
    header_cells: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) >= 2:
                if not in_table:
                    # This is the header row
                    header_cells = cells
                    in_table = True
                else:
                    # Skip separator rows (| --- | --- |)
                    if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                        continue
                    # Data row: extract each cell as a fact
                    for i, cell in enumerate(cells):
                        if i < len(header_cells) and header_cells[i] and cell:
                            key = header_cells[i].strip()
                            if len(cell) > 1 and len(cell) < 80 and cell != key:
                                facts.append({
                                    "type": "table_cell",
                                    "value": cell,
                                    "field": key,
                                    "context": f"{key}: {cell}",
                                })
        else:
            in_table = False
            header_cells = []

    # Extract key-value patterns: "Key: Value" or "Key — Value" where Value is meaningful
    for match in re.finditer(r"([A-Za-z][A-Za-z\s]{2,30}?)\s*[:]\s*(.{1,80})\s*$", text, re.MULTILINE):
        key = match.group(1).strip()
        val = match.group(2).strip()
        if key and val and len(key) > 2 and len(val) > 1:
            # Skip if key looks like a time, URL, or known boilerplate
            if not val.startswith("http") and not re.match(r"^\d{1,2}:\d{2}", val):
                facts.append({
                    "type": "key_value",
                    "value": val,
                    "field": key,
                    "context": f"{key}: {val}",
                })

    return facts


def _coverage_score(query: SubQuery, fetched: list[FetchResult]) -> float:
    """Score how well fetched results cover the sub-query topic.

    Uses term overlap density (not just presence) and intent-aware checks.
    Range 0.0–1.0. No inflation multipliers.
    """
    if not fetched:
        return 0.0
    query_terms = query.parent_terms or {t.lower() for t in _RE_TERM_TOKEN.findall(query.text)}
    if not query_terms:
        return 0.5  # neutral if no terms to match

    scores = []
    for r in fetched:
        if not r.text or len(r.text.strip()) < 200:
            continue
        result_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(r.text)}
        if not result_terms:
            continue
        # Overlap fraction
        overlap = len(query_terms & result_terms)
        max_possible = len(query_terms)
        overlap_frac = overlap / max_possible if max_possible else 0

        # Density: how many total query term occurrences per 1000 chars
        text_lower = r.text.lower()
        term_density = sum(text_lower.count(t) for t in query_terms) / max(1, len(text_lower) / 1000)
        density_factor = min(term_density / 10.0, 1.0)  # 10+ occurrences/1K chars = max

        # Combined: 60% overlap presence, 40% density
        combined = overlap_frac * 0.6 + density_factor * 0.4
        scores.append(combined)

    if not scores:
        return 0.0
    return min(1.0, sum(scores) / len(scores))


# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH COVERAGE + GAP DETECTION  (shared by core.research)
# ═══════════════════════════════════════════════════════════════════════════


def _research_coverage_score(query_text: str, fetched: list[FetchResult]) -> float:
    """Compute coverage score (0.0–1.0) for a plain query string and fetched results.

    Wraps ``_coverage_score`` for the research() flow which doesn't use SubQuery.
    """
    if not fetched:
        return 0.0
    query_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(query_text)}
    if not query_terms:
        return 0.5  # neutral

    scores = []
    for r in fetched:
        if not r.text or len(r.text.strip()) < 200:
            continue
        result_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(r.text)}
        if not result_terms:
            continue
        # Overlap fraction
        overlap = len(query_terms & result_terms)
        max_possible = len(query_terms)
        overlap_frac = overlap / max_possible if max_possible else 0

        # Density: total query term occurrences per 1000 chars
        text_lower = r.text.lower()
        term_density = sum(text_lower.count(t) for t in query_terms) / max(1, len(text_lower) / 1000)
        density_factor = min(term_density / 10.0, 1.0)  # 10+ occurrences/1K chars = max

        # Combined: 60% overlap presence, 40% density
        combined = overlap_frac * 0.6 + density_factor * 0.4
        scores.append(combined)

    if not scores:
        return 0.0
    return min(1.0, sum(scores) / len(scores))


def _detect_knowledge_gaps(query_text: str, fetched: list[FetchResult]) -> list[dict[str, Any]]:
    """Detect which query terms are poorly covered across fetched results.

    Returns a list of dicts sorted by coverage_level (worst first):
        {"term": str, "coverage_level": str, "suggested_refine": str}

    Coverage levels:
        "none"   — term not found in any fetched source
        "weak"   — term found in only 1-2 sources
        "moderate" — term found in 3-5 sources
        "strong" — term found in 6+ sources
    """
    if not fetched:
        return []

    # Extract meaningful terms from the query (skip stopwords, short tokens)
    query_tokens = {t.lower() for t in _RE_TERM_TOKEN.findall(query_text)}
    # Filter out very common/generic terms
    stopwords = _ROUTER._STOPWORDS | frozenset({
        "use", "using", "used", "get", "make", "way", "thing", "things",
        "like", "well", "also", "one", "two", "first", "second", "last",
        "new", "many", "much", "more", "most", "need", "want", "know",
    })
    meaningful_terms = query_tokens - stopwords

    if not meaningful_terms:
        return []

    # Count sources per term
    term_source_count: dict[str, int] = {t: 0 for t in meaningful_terms}
    for r in fetched:
        if not r.text:
            continue
        text_lower = r.text.lower()
        for t in meaningful_terms:
            if t in text_lower:
                term_source_count[t] += 1

    num_fetched = max(1, len(fetched))

    gaps: list[dict[str, Any]] = []
    for term, count in term_source_count.items():
        ratio = count / num_fetched
        if count == 0:
            level = "none"
        elif ratio < 0.25 or count <= 1:
            level = "weak"
        elif ratio < 0.5 or count <= 3:
            level = "moderate"
        else:
            level = "strong"

        gaps.append({
            "term": term,
            "coverage_level": level,
            "suggested_refine": f"{query_text} {term}",
        })

    # Sort: none first, then weak, then moderate, then strong
    level_order = {"none": 0, "weak": 1, "moderate": 2, "strong": 3}
    gaps.sort(key=lambda g: level_order.get(g["coverage_level"], 99))
    return gaps


def _suggest_followups(query_text: str, knowledge_gaps: list[dict[str, Any]]) -> list[str]:
    """Generate suggested follow-up queries based on detected knowledge gaps.

    Returns up to 3 concise follow-up suggestions.
    """
    if not knowledge_gaps:
        return []

    # Only consider gaps that are "none" or "weak"
    significant_gaps = [g for g in knowledge_gaps if g["coverage_level"] in ("none", "weak")]
    if not significant_gaps:
        return []

    followups: list[str] = []
    seen: set[str] = set()

    for gap in significant_gaps:
        refine = gap.get("suggested_refine", "")
        if refine and refine not in seen:
            followups.append(refine)
            seen.add(refine)
        if len(followups) >= 3:
            break

    # If still not enough, add broader suggestions from moderate gaps
    if len(followups) < 2:
        moderate_gaps = [g for g in knowledge_gaps if g["coverage_level"] == "moderate"]
        for gap in moderate_gaps:
            refine = gap.get("suggested_refine", "")
            if refine and refine not in seen:
                followups.append(refine)
                seen.add(refine)
            if len(followups) >= 3:
                break

    return followups


def run_subagent(
    sub_query: SubQuery,
    providers: list[str],
    timeout: int = 20,
    max_chars: int = 4000,
) -> SubAgentResult:
    """
    A 'sub-agent' is just a thread. It searches, fetches, and extracts
    structured facts — all without any LLM.

    Improvements:
    - Multi-query expansion: searches 3 variants of the query per branch
      (original, keyword version, site: expansion) for dramatically wider coverage
    - Reference/citation chasing: after fetching top results, extracts outbound
      reference links and fetches the highest-scored ones
    """
    warnings = []

    # ── Multi-query expansion (generates 3 query variants per branch) ──
    queries_to_search = [sub_query.text]
    simplified = _simplify_query(sub_query.text)
    if simplified != sub_query.text:
        queries_to_search.append(simplified)

    # Keyword-only version for higher recall
    keywords = _extract_keywords(sub_query.text)
    if keywords and keywords not in queries_to_search and keywords != simplified:
        queries_to_search.append(keywords)

    # Site-specific expansion for diversity (only for general intent)
    if sub_query.intent == "general" or len(queries_to_search) < 2:
        queries_to_search.append(f"{keywords or sub_query.text}")

    # Add a "related:" or "site:" expansion variant for diversity
    if len(queries_to_search) < 3:
        queries_to_search.append(f"{keywords or sub_query.text}")

    # Cap at 3 and deduplicate
    seen_queries: set[str] = set()
    unique_queries: list[str] = []
    for q in queries_to_search:
        q_norm = q.lower().strip()
        if q_norm and q_norm not in seen_queries:
            seen_queries.add(q_norm)
            unique_queries.append(q)
    queries_to_search = unique_queries[:3]

    # Log expanded queries
    if len(queries_to_search) > 1:
        warnings.append(f"query_expansion:expanded_to_{len(queries_to_search)}_variants")

    # 1. Search all query variants across all routed providers
    all_results: list[SearchResult] = []
    for search_query in queries_to_search:
        for provider in providers[:3]:  # cap at 3 providers per sub-agent
            try:
                results = search_by_provider(provider, search_query, max_results=5, timeout=timeout)
                all_results.extend(results)
            except Exception as exc:
                if not any(f"provider_{provider}_error" in w for w in warnings):
                    warnings.append(f"provider_{provider}_error:{exc}")

    # ── Zero-result fallback chain ──────────────────────────────────────
    if not all_results:
        keyword_q = _extract_keywords(sub_query.text)
        if keyword_q and keyword_q not in queries_to_search:
            try:
                kw_results = search_by_provider("general", keyword_q, max_results=5, timeout=timeout)
                if kw_results:
                    all_results.extend(kw_results)
                    warnings.append(f"keyword_fallback:used '{keyword_q}'")
            except Exception as exc:
                warnings.append(f"keyword_fallback_error:{exc}")

    if not all_results:
        try:
            jina_results = search_by_provider("jina", sub_query.text, max_results=5, timeout=timeout)
            if jina_results:
                all_results.extend(jina_results)
                warnings.append("jina_fallback:used Jina Search")
        except Exception as exc:
            warnings.append(f"jina_fallback_error:{exc}")

    if not all_results and sub_query.intent == "factual":
        min_keywords = _extract_keywords(sub_query.text)
        kw_parts = min_keywords.split()
        if len(kw_parts) > 3:
            short_q = " ".join(kw_parts[:4])
            try:
                hn_results = search_by_provider("general", short_q, max_results=5, timeout=timeout)
                if hn_results:
                    all_results.extend(hn_results)
                    warnings.append(f"factual_short_fallback:used '{short_q}'")
            except Exception as exc:
                warnings.append(f"factual_short_fallback_error:{exc}")

    # 2. Deduplicate by canonical URL
    seen_urls: set[str] = set()
    unique_results: list[SearchResult] = []
    for r in all_results:
        url_key = r.url.split("?")[0].rstrip("/").lower()
        url_key = url_key.removeprefix("https://").removeprefix("http://")
        url_key = url_key.removeprefix("www.")
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

    # ── 3b. Reference/citation link following ─────────────────────────────
    # Extract all outbound links from fetched text that look like references
    reference_urls: list[tuple[str, float, str]] = []
    REFERENCE_PATTERNS = {
        "arxiv": re.compile(r"(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/\d+\.\d+"),
        "doi": re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/10\.\d{4,}[^\s\"'<>]*"),
        "wikipedia": re.compile(r"(?:https?://)?(?:en\.)?wikipedia\.org/wiki/[^\s\"'<>]+"),
        "github": re.compile(r"(?:https?://)?(?:www\.)?github\.com/[^\s/]+/[^\s/\"'<>]+"),
        "pdf": re.compile(r"(?:https?://[^\s\"'<>]+\.pdf)"),
        "general_ref": re.compile(r"(?:https?://[^\s\"'<>]+)"),
    }

    # Score reference links by type
    REFERENCE_SCORES = {
        "arxiv": 2.0,
        "doi": 1.8,
        "wikipedia": 1.5,
        "github": 1.3,
        "pdf": 1.2,
        "general_ref": 0.8,
    }

    seen_refs: set[str] = set()
    for fr in fetched:
        if not fr.text:
            continue
        for ref_type, pattern in REFERENCE_PATTERNS.items():
            for m in pattern.finditer(fr.text):
                ref_url = m.group(0).rstrip(".,;:)\"'")
                canonical = ref_url.split("?")[0].rstrip("/")
                if canonical in seen_refs:
                    continue
                seen_refs.add(canonical)
                # Skip URLs that point back to already-fetched pages
                if any(f.url and canonical in f.url for f in fetched):
                    continue
                ref_score = REFERENCE_SCORES.get(ref_type, 1.0)
                reference_urls.append((ref_url, ref_score, ref_type))

    # Deduplicate and sort by score
    reference_urls.sort(key=lambda x: x[1], reverse=True)

    # Fetch top 3 reference links
    ref_fetched: list[FetchResult] = []
    if reference_urls:
        top_refs = [r[0] for r in reference_urls[:3]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ref_pool:
            ref_fut_map = {
                ref_pool.submit(fetch_url, ref_url, timeout=timeout, max_chars=max_chars, use_jina=True): ref_url
                for ref_url in top_refs
            }
            for fut in concurrent.futures.as_completed(ref_fut_map):
                try:
                    ref_result = fut.result()
                    if ref_result and ref_result.ok and ref_result.text:
                        ref_result.tactics.append("reference_chase")
                        ref_fetched.append(ref_result)
                except Exception:
                    pass

        if ref_fetched:
            warnings.append(f"reference_chase:followed_{len(ref_fetched)}_reference_links")

    # Merge reference-fetched results into main fetched list
    all_fetched = fetched + ref_fetched

    # 4. Extract entities and structured facts
    all_facts: list[dict] = []
    for r in all_fetched:
        if r.text:
            all_facts.extend(_extract_entities(r.text))

    coverage = _coverage_score(sub_query, all_fetched)

    return SubAgentResult(
        sub_query_id=sub_query.id,
        search_results=all_results,
        fetched_results=all_fetched,
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


def _classify_source_type(url: str, text: str) -> str:
    """Classify a source URL into a type category.

    Categories: academic, news, blog, forum, documentation, wikipedia,
    social, government, commercial, general
    """
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()

    # Academic sources
    if any(d in domain for d in ["arxiv.org", "nature.com", "science.org", "sciencedirect.com",
                                  "springer.com", "ieee.org", "acm.org", "pubmed.ncbi.nlm.nih.gov",
                                  "jstor.org", "cambridge.org", "oup.com", "tandfonline.com",
                                  "wiley.com", "sagepub.com"]):
        return "academic"
    if "/abs/" in parsed.path or "/pdf/" in parsed.path:
        return "academic"
    if "doi.org" in domain or "doi" in parsed.path:
        return "academic"

    # Wikipedia
    if "wikipedia.org" in domain:
        return "wikipedia"

    # Government
    if domain.endswith((".gov", ".mil", ".gov.uk", ".gouv.fr", ".europa.eu")):
        return "government"

    # News
    if any(d in domain for d in ["news", "reuters.com", "apnews.com", "bbc.", "cnn.com",
                                  "nytimes.com", "wsj.com", "washingtonpost.com", "theguardian.com",
                                  "bloomberg.com", "economist.com", "theverge.com", "wired.com",
                                  "zdnet.com", "arstechnica.com", "techcrunch.com", "thehill.com",
                                  "politico.com", "npr.org", "theatlantic.com"]):
        return "news"

    # Social
    if any(d in domain for d in ["reddit.com", "twitter.com", "x.com", "facebook.com",
                                  "linkedin.com", "tiktok.com", "instagram.com", "threads.net"]):
        return "social"

    # Forums
    if any(d in domain for d in ["stackoverflow.com", "stackexchange.com", "quora.com",
                                  "stackapps.com", "serverfault.com", "superuser.com"]):
        return "forum"

    # Documentation
    if any(d in domain for d in ["docs.", "readthedocs.io", "readme.io", "gitbook.io",
                                  "w3.org", "mozilla.org", "developer.", "dev.to",
                                  "learn.microsoft.com", "kubernetes.io"]):
        return "documentation"
    if domain.endswith((".github.io", ".gitbooks.io")):
        return "documentation"

    # Commercial
    if domain.endswith((".com", ".io", ".co")) and not any(d in domain for d in [".gov", ".edu", ".org"]):
        return "commercial"

    # Blog — common blog platforms
    if any(d in domain for d in ["medium.com", "substack.com", "blogspot.com", "wordpress.com",
                                  "ghost.org", "hashnode.dev", "dev.to"]):
        return "blog"

    # Check text for academic indicators
    if text and len(text) > 500:
        lower_text = text.lower()
        academic_signals = sum(1 for t in [
            "references", "citations", "doi:", "abstract", "introduction",
            "methodology", "experiment", "results show", "we propose",
            "conference", "proceedings", "journal"
        ] if t in lower_text)
        if academic_signals >= 4:
            return "academic"

    return "general"


def _extract_date_from_text(text: str) -> str | None:
    """Extract a publication/freshness date from text content or metadata."""
    # Look for ISO dates
    m = re.search(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b", text)
    if m:
        return m.group(0)

    # Look for common date patterns like "January 15, 2024"
    months = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    m = re.search(rf"{months}\s+\d{{1,2}},?\s+(20\d{{2}})", text)
    if m:
        return m.group(0)

    # Look for standalone years (last resort)
    m = re.search(r"\b(20[2-9]\d)\b", text)
    if m:
        return m.group(1)

    return None


def _freshness_score(date_str: str | None, intent: str) -> float:
    """Score how fresh a source is based on its date and query intent.

    Returns 0.0–1.0 multiplier applied to freshness component.
    News/intent queries get higher freshness bonuses.
    """
    if not date_str:
        return 0.3  # neutral if no date

    # Extract year
    m = re.search(r"(20\d{2})", date_str)
    if not m:
        return 0.3
    year = int(m.group(1))

    import datetime
    current_year = datetime.date.today().year
    age = current_year - year

    if age <= 1:
        base = 1.0
    elif age <= 3:
        base = 0.8
    elif age <= 5:
        base = 0.6
    elif age <= 10:
        base = 0.4
    else:
        base = 0.2

    # News/queries with temporal intent get higher freshness weight
    if intent in ("news", "interrogative"):
        return base * 1.2
    elif intent in ("list", "comparison"):
        return base * 1.0
    else:
        return base * 0.8


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
    4. Diversity bonus for underrepresented source types
    5. Freshness bonus for recent content (especially news/interrogative queries)

    Formula: total = 0.3 * bm25 + 0.2 * authority + 0.2 * coverage + 0.2 * diversity + 0.1 * freshness
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

    # Classify source types for diversity scoring
    source_types: dict[str, int] = {}
    for (fr, _, _) in all_fetched:
        st = _classify_source_type(fr.url or "", fr.text or "")
        source_types[st] = source_types.get(st, 0) + 1
    total_sources = len(all_fetched)

    scored: list[ScoredSource] = []
    for (fr, coverage, sub_result), bm25_score in zip(all_fetched, bm25_scores):
        authority = _authority_boost(fr.url or "")

        # Source type classification + diversity bonus
        source_type = _classify_source_type(fr.url or "", fr.text or "")
        type_count = source_types.get(source_type, 1)
        # Underrepresented types get a diversity bonus
        diversity_bonus = 1.0 - (type_count / max(total_sources, 1)) + 0.5
        diversity_bonus = min(diversity_bonus, 1.5)  # cap at 1.5

        # Freshness detection
        date_str = _extract_date_from_text(fr.text or "")
        freshness = _freshness_score(date_str, intent)

        # Normalize bm25 score to 0–1 range
        max_bm = max(bm25_scores) if max(bm25_scores) > 0 else 1
        norm_bm = bm25_score / max_bm

        # New scoring formula with diversity and freshness
        total = 0.3 * norm_bm + 0.2 * authority + 0.2 * coverage + 0.2 * diversity_bonus + 0.1 * freshness
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


# Regex for broader stat detection (numbers, prices, percentages, scores)
_RE_STAT = re.compile(
    r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|million|billion|thousand|dollars?|usd|"
    r"points?|score|rating|rank|users?|requests?)\b",
    re.I,
)
_RE_PRICE = re.compile(r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?")
_RE_TABLE_ROW = re.compile(
    r"^\|\s*.+\|.*$", re.MULTILINE
)  # markdown table row
_RE_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


def _is_nav_or_title_sentence(sent: str) -> bool:
    """Return True if sentence looks like a page title, nav label, or menu item."""
    low = sent.lower().strip()
    # Single phrase with no verb and <8 words that ends without punctuation
    if len(sent.split()) <= 6 and not any(c in sent for c in [",", ";", ":", " — ", " – "]):
        if re.match(r"^[A-Z][a-zA-Z\s\-'<=>]{2,60}$", sent.strip()):
            return True
    # Known nav/filter patterns
    nav_patterns = [
        "default order", "vfm sort", "best <=", "best ≤", "sort by", "filter by",
        "skip to content", "menu", "subscribe", "sign in", "log in",
        "load more", "show more", "click here", "read more",
        "default order best", "value for money",
    ]
    for pat in nav_patterns:
        if pat in low:
            return True
    return False


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
    4. Penalize short/nav/title sentences
    5. Select top-N by composite score
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
            if len(sent) < 25 or len(sent) > 700:
                continue
            # Deduplicate by sentence hash
            h = hashlib.md5(sent.lower().encode()).hexdigest()[:12]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            # Skip nav/title/menu sentences entirely
            if _is_nav_or_title_sentence(sent):
                continue

            s_terms = {t.lower() for t in _RE_TERM_TOKEN.findall(sent)}
            s_len = len(sent)
            overlap = len(q_terms & s_terms)
            boost = len(boost_terms & s_terms)
            entity_count = len(_RE_ENTITY_CAPTURE.findall(sent))
            stat_count = len(_RE_STAT.findall(sent))
            price_count = len(_RE_PRICE.findall(sent))
            table_row = 1 if _RE_TABLE_ROW.match(sent) else 0
            num_count = len(_RE_NUMBER.findall(sent))

            # Base relevance: overlap density
            base = overlap / max(1, len(s_terms)) if overlap > 0 else 0

            # Boost signals for substantive content
            substantive = (stat_count * 0.8) + (price_count * 0.8) + (entity_count * 0.15) + (num_count * 0.15)
            intent_boost = (boost / max(1, len(s_terms))) * 0.5
            table_boost = table_row * 0.5

            # Length penalty: sentences <60 chars are suspicious (nav/title)
            length_penalty = 0.0
            if s_len < 60:
                length_penalty = -0.3
            elif s_len < 100:
                length_penalty = -0.1

            # Composite relevance score — meaningful range 0.0–~2.5
            relevance = base + substantive + intent_boost + table_boost + length_penalty
            relevance = max(0.0, relevance)

            if overlap > 0 and relevance > 0:
                all_sentences.append((sent, fr, relevance))

    # Sort by relevance and pick top-N
    all_sentences.sort(key=lambda x: x[2], reverse=True)

    claims: list[EvidenceClaim] = []
    for sent, fr, relevance in all_sentences[:max_claims]:
        # Classify claim type — more aggressive stat detection
        if (re.search(r"\d+(?:\.\d+)?%", sent)
            or re.search(r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?", sent)
            or re.search(r"\d+(?:,\d{3})*(?:\.\d+)?\s*(million|billion|thousand|users|requests?|points?)", sent, re.I)):
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
    Zero LLM: uses numeric divergence + opposing keyword detection + entity-value conflicts.
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
        ("best", "worst"),
        ("leader", "laggard"),
        ("cheaper", "expensive"),
        ("faster", "slower"),
    ]

    contradictions = []
    for i, c1 in enumerate(claims):
        for c2 in claims[i + 1 :]:
            s1, s2 = c1.sentence.lower(), c2.sentence.lower()

            # ── Numeric divergence on same entity/metric ────────────────
            # Extract all (number, entity_context) pairs from each sentence
            nums1 = re.findall(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|\$|million|billion|thousand)?", s1, re.I)
            nums2 = re.findall(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|\$|million|billion|thousand)?", s2, re.I)
            # Extract entities for context matching
            ents1 = _RE_ENTITY_CAPTURE.findall(s1)
            ents2 = _RE_ENTITY_CAPTURE.findall(s2)
            shared_entities = set(e.lower() for e in ents1) & set(e.lower() for e in ents2)

            if nums1 and nums2 and (shared_entities or (len(nums1) == 1 and len(nums2) == 1)):
                # Try comparing percentage values
                pcts1 = [float(n[0].replace(",", "")) for n in nums1 if n[1] == "%"]
                pcts2 = [float(n[0].replace(",", "")) for n in nums2 if n[1] == "%"]
                if pcts1 and pcts2:
                    diff = abs(max(pcts1) - max(pcts2))
                    if diff > 15 and shared_entities:
                        contradictions.append((c1, c2))
                        c1.is_contradictory = True
                        c2.is_contradictory = True
                        continue
                # Try comparing raw numbers on same entity topic
                raw1 = [float(n[0].replace(",", "")) for n in nums1]
                raw2 = [float(n[0].replace(",", "")) for n in nums2]
                if shared_entities and len(raw1) == 1 and len(raw2) == 1:
                    large = max(raw1[0], raw2[0])
                    if large > 0:
                        pct_diff = abs(raw1[0] - raw2[0]) / large * 100
                        if pct_diff > 30:
                            contradictions.append((c1, c2))
                            c1.is_contradictory = True
                            c2.is_contradictory = True
                            continue

            # ── Opposing keywords ─────────────────────────────────────
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
    # Pick substantive sentences: prefer stats, longer content, diverse sources
    exec_candidates = [c for c in claims[:10] if not _is_nav_or_title_sentence(c.sentence) and len(c.sentence) > 60]
    if not exec_candidates:
        exec_candidates = [c for c in claims[:15] if len(c.sentence) > 40 and not _is_nav_or_title_sentence(c.sentence)]
    if not exec_candidates:
        exec_candidates = claims[:5]

    # Pick up to 3 sentences, preferring stat types and diversity of sources
    exec_sents = []
    seen_urls = set()
    for c in exec_candidates:
        if len(exec_sents) >= 3:
            break
        key = c.source_url.split("?")[0].rstrip("/")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        exec_sents.append(c.sentence)

    exec_summary = " ".join(exec_sents) if exec_sents else "No substantive findings retrieved."
    if len(exec_summary) > 800:
        exec_summary = exec_summary[:797].rsplit(" ", 1)[0] + "..."

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

    # ── 2b. Entity Deep-Dive ──────────────────────────────────────────────
    # Group claims by named entity, showing what was learned about each entity
    entity_deep_dive_lines = []
    entity_map: dict[str, dict[str, Any]] = {}
    query_entities = set(_RE_ENTITY_CAPTURE.findall(query))

    # Collect entities from all sub_results entity_facts
    all_entity_facts: list[dict] = []
    for sr in sub_results:
        all_entity_facts.extend(sr.entity_facts)

    # Build entity -> claims mapping
    for c in claims:
        entities = _RE_ENTITY_CAPTURE.findall(c.sentence)
        for ent in entities:
            ent_lower = ent.lower().strip()
            if len(ent_lower) <= 3:
                continue
            if ent_lower in {"this", "that", "these", "those", "they", "there", "which", "what"}:
                continue
            if ent not in entity_map:
                entity_map[ent] = {"claims": [], "sources": set(), "mention_count": 0}
            entity_map[ent]["claims"].append(c)
            entity_map[ent]["sources"].add(c.source_url)
            entity_map[ent]["mention_count"] += 1

    # Also add entity_facts that aren't covered by claims
    for fact in all_entity_facts:
        val = fact.get("value", "")
        if val and len(val) > 2:
            for ent in _RE_ENTITY_CAPTURE.findall(val):
                ent_lower = ent.lower().strip()
                if len(ent_lower) <= 3 or ent_lower in {"this", "that", "these", "those"}:
                    continue
                if ent not in entity_map:
                    entity_map[ent] = {"claims": [], "sources": set(), "mention_count": 0}
                entity_map[ent]["mention_count"] += 1

    # Rank entities: prefer entities in the query itself, then by mention count
    ranked_entities = sorted(
        entity_map.items(),
        key=lambda x: (
            2 if x[0].lower() in {e.lower() for e in query_entities} else 1,
            x[1]["mention_count"],
        ),
        reverse=True,
    )

    if ranked_entities:
        entity_deep_dive_lines.append("## Entity Deep-Dive\n")
        for ent_name, ent_data in ranked_entities[:8]:  # Top 8 entities
            sources_count = len(ent_data["sources"])
            mention_count = ent_data["mention_count"]
            top_claims = sorted(ent_data["claims"], key=lambda c: c.relevance_score, reverse=True)[:3]
            entity_deep_dive_lines.append(f"### {ent_name}\n")
            entity_deep_dive_lines.append(f"- Sources mentioning: {sources_count}\n")
            entity_deep_dive_lines.append(f"- Mention count: {mention_count}\n")
            if top_claims:
                entity_deep_dive_lines.append("- Key claims:\n")
                for c in top_claims:
                    entity_deep_dive_lines.append(
                        f"  - {_truncate(c.sentence, 180)} — [{c.source_title or c.source_url}]({c.source_url})\n"
                    )
            entity_deep_dive_lines.append("\n")

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
        *entity_deep_dive_lines,
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
                    "ok": s.result.ok,
                    "status_code": s.result.status_code,
                    "source": s.result.source,
                    "text_len": len(s.result.text) if s.result.text else 0,
                    "quality_score": s.result.quality_score(),
                    "total_score": round(s.total_score, 3),
                    "bm25_score": round(s.bm25_score, 3),
                    "authority_boost": s.authority_boost,
                    "novel_score": round(getattr(s, 'novel_score', 1.0), 3),
                    "suppression_reason": (
                        "already_known" if getattr(s, 'novel_score', 1.0) < 0.3 else ""
                    ),
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

    .. deprecated::
        Use ``research(query, refine=\"...\")`` or ``deep_research(query, refine=\"...\")``
        for agent-steerable refinement instead.
    """
    warnings.warn(
        "expand_query_terms() is deprecated — use research(refine=...) for agent-steerable refinement.",
        DeprecationWarning,
        stacklevel=2,
    )
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

    .. deprecated::
        Use ``research(refine=\"...\")`` or ``deep_research(refine=\"...\")``
        for agent-steerable refinement instead.
    """
    warnings.warn(
        "refine_with_additional_search() is deprecated — use research(refine=...) for agent-steerable refinement.",
        DeprecationWarning,
        stacklevel=2,
    )
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


def _deep_research_stream(
    query: str,
    *,
    max_results: int = 8,
    timeout: int = 20,
    max_chars: int = 6000,
    refinement_loops: int = 0,
    refine: str | None = None,
    guard: InputGuard | None = None,
    already_knows: list[str] | None = None,
) -> Iterable[dict[str, Any]]:
    """Generator that runs the full deep research pipeline but yields
    intermediate phase dicts so callers can consume progress incrementally.

    Yields the following dicts in order:

    - ``{"phase": "decompose", "query": str, "branches": [SubQuery dicts]}``
    - ``{"phase": "search", "branch": str, "results": [SearchResult dicts]}``
        — once per sub-agent after its search completes
    - ``{"phase": "fetch", "branch": str, "sources": [FetchResult dicts]}``
        — once per sub-agent after its fetch completes
    - ``{"phase": "rank", "sources": [ScoredSource dicts]}``
    - ``{"phase": "evidence", "claims": [EvidenceClaim dicts]}``
    - ``{"phase": "complete", "report": {...}}`` — the final report dict
    """
    start_time = time.time()

    # 0. Safety guard
    if guard is None:
        guard = InputGuard()
    guard.validate_text(query)

    # Augment query with refine steering (if provided)
    effective_query = f"{query} refine: {refine}" if refine else query

    # 1. Query decomposition
    plan = decompose_query(effective_query)
    providers = route_providers(effective_query, plan.intent)

    # --- yield decompose phase ---
    yield {
        "phase": "decompose",
        "query": effective_query,
        "branches": [_subquery_to_dict(q) for q in plan.sub_queries],
    }

    # 2. Dispatch sub-agents in parallel
    sub_results: list[SubAgentResult] = []
    branch_count = plan.branch_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=branch_count) as pool:
        fut_map = {
            pool.submit(run_subagent, sq, providers, timeout, max_chars): sq
            for sq in plan.sub_queries
        }
        for fut in concurrent.futures.as_completed(fut_map):
            sq = fut_map[fut]
            try:
                sr: SubAgentResult = fut.result()
                sub_results.append(sr)

                # --- yield search results for this branch ---
                yield {
                    "phase": "search",
                    "branch": sq.id,
                    "results": [r.to_dict() for r in sr.search_results],
                }

                # --- yield fetch sources for this branch ---
                yield {
                    "phase": "fetch",
                    "branch": sq.id,
                    "sources": [r.to_dict(max_chars=max_chars) for r in sr.fetched_results],
                }

            except Exception as exc:
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

    # 3. Refinement loop (if needed — off by default, kept for backward compat)
    if refinement_loops > 0:
        sub_results = refine_with_additional_search(
            plan, sub_results, [], max_refinement_loops=refinement_loops, timeout=timeout
        )

    # 4. Rank all sources
    scored_sources = rank_sources(sub_results, effective_query, plan.intent)

    # ── TF-IDF novelty scoring against already_knows ──────────────────
    if already_knows:
        texts = [s.result.text or "" for s in scored_sources]
        novel_scores = compute_novelty_scores(already_knows, texts)
        for s, ns in zip(scored_sources, novel_scores):
            s.novel_score = round(ns, 3)
        # Re-rank: boost novelty (50% original score + 50% novelty)
        max_score = max(s.total_score for s in scored_sources) if scored_sources else 1.0
        for s in scored_sources:
            s.total_score = 0.5 * (s.total_score / max_score) + 0.5 * getattr(s, 'novel_score', 0.5)
        scored_sources.sort(key=lambda x: x.total_score, reverse=True)
    else:
        for s in scored_sources:
            s.novel_score = 1.0  # default: fully novel

    # --- yield rank phase ---
    yield {
        "phase": "rank",
        "sources": [
            {
                "url": s.result.final_url or s.result.url,
                "title": s.result.title,
                "bm25_score": round(s.bm25_score, 3),
                "authority_boost": s.authority_boost,
                "coverage_boost": s.coverage_boost,
                "total_score": round(s.total_score, 3),
                "quality_score": s.result.quality_score(),
                "novel_score": round(getattr(s, 'novel_score', 1.0), 3),
            }
            for s in scored_sources[:15]
        ],
    }

    # 5. Extract evidence
    claims = extract_evidence(scored_sources, effective_query, plan.intent, max_claims=20)

    # 5b. Add structured facts from table/key-value extraction
    table_claims: list[EvidenceClaim] = []
    seen_table_keys: set[str] = set()
    for sr in sub_results:
        for fact in sr.entity_facts:
            if fact["type"] in ("table_cell", "key_value"):
                key = f"{fact.get('field','')}:{fact['value']}"
                h = hashlib.md5(key.lower().encode()).hexdigest()[:12]
                if h not in seen_table_keys:
                    seen_table_keys.add(h)
                    table_claims.append(EvidenceClaim(
                        sentence=fact.get("context", fact["value"]),
                        source_url="",
                        source_title="",
                        claim_type="stat" if re.search(r"\d", fact["value"]) else "fact",
                        relevance_score=0.5,
                    ))
    # Merge with sentence-level claims, keeping top-N by relevance
    all_claims = sorted(claims + table_claims, key=lambda c: c.relevance_score, reverse=True)
    claims = all_claims[:20]

    # --- yield evidence phase ---
    yield {
        "phase": "evidence",
        "claims": [
            {
                "sentence": c.sentence,
                "source_url": c.source_url,
                "source_title": c.source_title,
                "claim_type": c.claim_type,
                "relevance_score": round(c.relevance_score, 3),
            }
            for c in claims
        ],
    }

    # 6. Detect contradictions
    contradictions = detect_contradictions(claims)

    # 7. Build report
    report = build_report(effective_query, plan, sub_results, scored_sources, claims, contradictions)

    elapsed = time.time() - start_time

    final_report = {
        "query": query,
        "elapsed_seconds": round(elapsed, 1),
        "report_markdown": report["report_markdown"],
        "report_json": report["report_json"],
    }
    if refine:
        final_report["refine"] = refine

    # --- yield complete phase with the final report ---
    yield {
        "phase": "complete",
        "report": final_report,
    }


def deep_research(
    query: str,
    *,
    max_results: int = 8,
    timeout: int = 20,
    max_chars: int = 6000,
    refinement_loops: int = 0,
    refine: str | None = None,
    guard: InputGuard | None = None,
    already_knows: list[str] | None = None,
) -> dict[str, Any]:
    """
    AgentWeb's deep research pipeline. Zero LLM calls.

    Pipeline:
      Query Plan → Sub-Agent Dispatch → Parallel Search/Fetch →
      BM25 Ranking → Evidence Extraction → Contradiction Detection →
      (Optional) Refinement Loop → Report Generation

    Parameters
    ----------
    query : str
        The research query.
    refine : str | None, optional
        Agent-steerable refinement string appended to the query
        (e.g., ``"pricing"`` or ``"technical specifications"``).

    Returns a dict with both 'report_markdown' (human-readable) and
    'report_json' (structured).
    """
    start_time = time.time()

    # 0. Safety guard
    if guard is None:
        guard = InputGuard()
    guard.validate_text(query)

    # Augment query with refine steering (if provided)
    effective_query = f"{query} refine: {refine}" if refine else query

    # 1. Query decomposition
    plan = decompose_query(effective_query)
    providers = route_providers(effective_query, plan.intent)

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

    # 3. Refinement loop (if needed — off by default, kept for backward compat)
    if refinement_loops > 0:
        sub_results = refine_with_additional_search(
            plan, sub_results, [], max_refinement_loops=refinement_loops, timeout=timeout
        )

    # 4. Rank all sources
    scored_sources = rank_sources(sub_results, effective_query, plan.intent)

    # ── TF-IDF novelty scoring against already_knows ──────────────────
    if already_knows:
        texts = [s.result.text or "" for s in scored_sources]
        novel_scores = compute_novelty_scores(already_knows, texts)
        for s, ns in zip(scored_sources, novel_scores):
            s.novel_score = round(ns, 3)
        # Re-rank: blend original score with novelty
        max_score = max(s.total_score for s in scored_sources) if scored_sources else 1.0
        for s in scored_sources:
            s.total_score = 0.5 * (s.total_score / max_score) + 0.5 * getattr(s, 'novel_score', 0.5)
        scored_sources.sort(key=lambda x: x.total_score, reverse=True)
    else:
        for s in scored_sources:
            s.novel_score = 1.0  # default

    # 5. Extract evidence
    claims = extract_evidence(scored_sources, effective_query, plan.intent, max_claims=20)

    # 5b. Add structured facts from table/key-value extraction
    table_claims: list[EvidenceClaim] = []
    seen_table_keys: set[str] = set()
    for sr in sub_results:
        for fact in sr.entity_facts:
            if fact["type"] in ("table_cell", "key_value"):
                key = f"{fact.get('field','')}:{fact['value']}"
                h = hashlib.md5(key.lower().encode()).hexdigest()[:12]
                if h not in seen_table_keys:
                    seen_table_keys.add(h)
                    table_claims.append(EvidenceClaim(
                        sentence=fact.get("context", fact["value"]),
                        source_url="",
                        source_title="",
                        claim_type="stat" if re.search(r"\d", fact["value"]) else "fact",
                        relevance_score=0.5,
                    ))
    # Merge with sentence-level claims, keeping top-N by relevance
    all_claims = sorted(claims + table_claims, key=lambda c: c.relevance_score, reverse=True)
    claims = all_claims[:20]

    # 6. Detect contradictions
    contradictions = detect_contradictions(claims)

    # 7. Build report
    report = build_report(effective_query, plan, sub_results, scored_sources, claims, contradictions)

    elapsed = time.time() - start_time

    result = {
        "query": query,
        "elapsed_seconds": round(elapsed, 1),
        "report_markdown": report["report_markdown"],
        "report_json": report["report_json"],
    }
    if refine:
        result["refine"] = refine
    return result
