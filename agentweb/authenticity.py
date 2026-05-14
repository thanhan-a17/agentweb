"""Content authenticity detector — domain-agnostic response quality assessment.

Replaces the old "stealth domains" approach (hardcoded domain list + per-domain
config) with a runtime content quality score. Instead of asking "is this domain
known to block bots?", we ask "does this response look like real content?"

The fetch pipeline uses this score to auto-escalate through extraction tactics
(HTTP -> Jina -> Browser) without any domain config. No whitelists, no per-site
tuning. Just works.

Usage:
    from agentweb.authenticity import ContentAuthenticity

    score = ContentAuthenticity.score(text, raw_html, status_code)
    is_blocked = ContentAuthenticity.is_blocked(text, raw_html, status_code)
"""

from __future__ import annotations

import re
from typing import Any

# ── Blocked-response signal patterns ──────────────────────────────────────
# These are checked in the first 2000 chars of extracted text.
_BLOCKED_SIGNALS: list[str] = [
    "just a moment",
    "verify you are human",
    "verify your identity",
    "access denied",
    "access blocked",
    "unusual traffic",
    "automated access",
    "automated requests",
    "captcha",
    "cloudflare",
    "enable javascript",
    "enable cookies",
    "browser check",
    "checking your browser",
    "your request has been blocked",
    "please turn javascript on",
    "you have been blocked",
    "sorry, you have been blocked",
    "we need to verify",
    "security check",
    "ddos protection",
    "attention required",
    "403 forbidden",
    "503 service unavailable",
    "blocked",
]

# ── Paywall / login-wall signals (milder penalty — content might be real
#    but incomplete) ───────────────────────────────────────────────────────
_PAYWALL_SIGNALS: list[str] = [
    "subscribe to read more",
    "sign up to continue",
    "sign in to read",
    "subscribe to continue",
    "this article is for subscribers",
    "membership required",
    "unlock this article",
    "continue reading",
    "read the full article",
    "sign up for free",
    "create account to view",
    "log in to view",
    "you've reached your article limit",
    "this is a premium article",
]

# ── Common navigation / boilerplate sentences to filter from analysis ────
_BOILERPLATE_SENTENCES: set[str] = {
    "skip to content",
    "skip to main content",
    "menu",
    "navigation",
    "subscribe",
    "sign in",
    "log in",
    "sign up",
    "follow us",
    "share this article",
    "related articles",
    "you might also like",
    "advertisement",
    "sponsored",
    "cookie settings",
    "accept cookies",
    "reject cookies",
    "privacy policy",
    "terms of service",
    "loading",
    "please wait",
}


class ContentAuthenticity:
    """Domain-agnostic content quality detector.

    Scores a fetched response on a 0.0–1.0 scale where 1.0 = definitely
    real, readable content and 0.0 = definitely blocked / shell / error.

    The score considers:
    - HTTP status code
    - Raw extracted text length and structure
    - Blocked-response signal patterns (CAPTCHA, Cloudflare, etc.)
    - Paywall / login-wall signals
    - Content-to-markup ratio (when raw HTML is available)
    - Line diversity (boilerplate detection)
    - Meaningful sentence count
    """

    # Thresholds
    BLOCKED_THRESHOLD = 0.3   # Score below this = almost certainly blocked
    SUSPICIOUS_THRESHOLD = 0.5  # Score below this = suspicious, try fallback

    @classmethod
    def score(
        cls,
        text: str,
        raw_html: str = "",
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> float:
        """Score content authenticity on a 0.0–1.0 scale.

        Args:
            text: Extracted text content (after HTML stripping).
            raw_html: Raw response body (for markup ratio analysis).
            status_code: HTTP response status code.
            headers: Response HTTP headers (reserved for future heuristics).

        Returns:
            Float from 0.0 (blocked) to 1.0 (real content).
        """
        text = text or ""
        text_stripped = text.strip()

        # ── Quick knockouts — no content or clear error ──────────────
        if status_code is not None:
            if status_code in (401, 403, 429, 503):
                return 0.0
            if status_code >= 500:
                return 0.0

        if not text_stripped:
            return 0.0

        # ── Start at neutral ─────────────────────────────────────────
        score = 0.5

        # ── 1. Content length (up to +0.3) ───────────────────────────
        text_len = len(text_stripped)
        if text_len >= 5000:
            score += 0.3
        elif text_len >= 2000:
            score += 0.2
        elif text_len >= 500:
            score += 0.1
        elif text_len >= 200:
            score += 0.05
        else:
            score -= 0.3  # Very short — suspicious

        # ── 2. Blocked signal patterns (up to -0.6) ──────────────────
        text_lower = text_stripped.lower()
        blocked_hits = sum(1 for sig in _BLOCKED_SIGNALS if sig in text_lower[:2000])
        score -= min(blocked_hits * 0.15, 0.6)

        # ── 3. Paywall / login-wall signals (up to -0.3) ─────────────
        paywall_hits = sum(1 for sig in _PAYWALL_SIGNALS if sig in text_lower[:3000])
        score -= min(paywall_hits * 0.1, 0.3)

        # ── 4. Content-to-markup ratio (if raw HTML available) ───────
        if raw_html and text_len > 0:
            html_len = len(raw_html)
            if html_len > 0:
                ratio = text_len / html_len
                if ratio < 0.02:
                    score -= 0.4  # Extremely thin content
                elif ratio < 0.05:
                    score -= 0.2  # Below average density
                elif ratio > 0.3:
                    score += 0.05  # High content density

        # ── 5. Meaningful sentence count ─────────────────────────────
        sentences = re.split(r"(?<=[.!?])\s+", text_stripped)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 8]
        meaningful = [
            s for s in sentences
            if s.lower() not in _BOILERPLATE_SENTENCES
            and not s.startswith(("http", "www.", "//"))
        ]
        if len(meaningful) < 2:
            score -= 0.3  # No real sentences
        elif len(meaningful) >= 5:
            score += 0.05  # Multiple substantive sentences

        # ── 6. Line diversity / boilerplate detection ────────────────
        lines = [
            l.strip() for l in text_stripped.splitlines()
            if len(l.strip()) > 20
        ]
        if lines:
            unique_ratio = len(set(lines)) / len(lines)
            if unique_ratio < 0.2:
                score -= 0.4  # Extremely repetitive
            elif unique_ratio < 0.4:
                score -= 0.2  # Mostly boilerplate
            elif unique_ratio > 0.7:
                score += 0.1  # Diverse content

        # ── 7. Paragraph-level structure ─────────────────────────────
        paragraphs = [p.strip() for p in text_stripped.split("\n\n") if len(p.strip()) > 50]
        if len(paragraphs) >= 3:
            score += 0.05

        return max(0.0, min(1.0, score))

    @classmethod
    def is_blocked(
        cls,
        text: str,
        raw_html: str = "",
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> bool:
        """Quick check: is this response definitely blocked / shell content?

        Uses BLOCKED_THRESHOLD (0.3). Returns True when the content is almost
        certainly not what the user wanted (CAPTCHA, Cloudflare, empty shell,
        login wall with no actual content, etc.).
        """
        return cls.score(text, raw_html, status_code, headers) < cls.BLOCKED_THRESHOLD

    @classmethod
    def is_suspicious(
        cls,
        text: str,
        raw_html: str = "",
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> bool:
        """Check if content is suspicious enough to warrant fallback tactics.

        Uses SUSPICIOUS_THRESHOLD (0.5). Returns True when the content
        might be incomplete or substandard — triggers Jina reader or
        browser fallback.
        """
        return cls.score(text, raw_html, status_code, headers) < cls.SUSPICIOUS_THRESHOLD

    @classmethod
    def analysis(
        cls,
        text: str,
        raw_html: str = "",
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return a detailed analysis dict for debugging / logging.

        Includes the overall score, individual factor breakdowns,
        and flagged signals.
        """
        text = text or ""
        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        blocked_hits = [sig for sig in _BLOCKED_SIGNALS if sig in text_lower[:2000]]
        paywall_hits = [sig for sig in _PAYWALL_SIGNALS if sig in text_lower[:3000]]

        sentences = re.split(r"(?<=[.!?])\s+", text_stripped)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 8]
        meaningful = [
            s for s in sentences
            if s.lower() not in _BOILERPLATE_SENTENCES
            and not s.startswith(("http", "www.", "//"))
        ]

        lines = [l.strip() for l in text_stripped.splitlines() if len(l.strip()) > 20]
        unique_ratio = len(set(lines)) / len(lines) if lines else 0.0

        text_len = len(text_stripped)
        html_len = len(raw_html)
        markup_ratio = text_len / html_len if html_len > 0 else 0.0

        return {
            "score": cls.score(text, raw_html, status_code, headers),
            "is_blocked": cls.is_blocked(text, raw_html, status_code, headers),
            "is_suspicious": cls.is_suspicious(text, raw_html, status_code, headers),
            "factors": {
                "text_length": text_len,
                "html_length": html_len,
                "markup_ratio": round(markup_ratio, 4),
                "blocked_signals": blocked_hits,
                "paywall_signals": paywall_hits,
                "meaningful_sentences": len(meaningful),
                "unique_line_ratio": round(unique_ratio, 4),
                "paragraphs": len([p for p in text_stripped.split("\n\n") if len(p) > 50]),
            },
        }
