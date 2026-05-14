"""AgentWeb core web-access engine.

The design goal is boring but useful: one CLI call gives an agent a compact,
cited, high-signal source pack instead of making it juggle search, curl,
readability extraction, browser fallbacks, and weird SPA payloads itself.
"""

from __future__ import annotations

import base64
import concurrent.futures
import email.utils
import html
import json
import os
import math
import re
import shutil
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Iterable

import requests

from agentweb.errors import (
    AgentWebError,
    BotBlocked,
    InvalidURL,
    NoResults,
    RateLimited,
    Timeout,
    map_exception,
)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

BLOCK_PATTERNS = re.compile(
    r"captcha|cloudflare|access denied|verify you are human|unusual traffic|bot detection|blocked",
    re.I,
)
TEXT_MIME_HINTS = ("text/", "application/json", "application/xml", "application/xhtml+xml")


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    ok: bool = False
    status_code: int | None = None
    source: str = ""
    title: str = ""
    text: str = ""
    markdown: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    tactics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def quality_score(self) -> float:
        """Score page quality on a 0–10 scale.

        Differentiating factors:
        - ok + 2.0
        - title + 0.5
        - text length bonus: up to 4.0 for content-rich pages
        - content density: penalize pages with high link-to-text ratio
        - content uniqueness: reward pages with higher unique-content ratio
        - penalties for bot blocks, warnings, error status codes
        """
        score = 0.0
        if self.ok:
            score += 2.0
        if self.title:
            score += 0.5
        text_len = len(self.text.strip())
        # Text bonus: scales from 0 to 4.0, diminishing returns after 10K chars
        score += min(text_len / 2500.0, 4.0)
        # Links: high link density = chrome/nav page
        if self.links:
            score += 0.3
            link_density = len(self.links) / max(1, min(text_len, 20000) / 1000.0)
            if link_density > 2.0:  # >2 links per 1K chars = nav-heavy
                score -= 0.3
            if link_density > 4.0:
                score -= 0.5
        # Content uniqueness: unique line ratio
        if text_len > 500:
            lines = self.text.splitlines()
            unique_lines = set()
            total_content_lines = 0
            for line in lines:
                stripped = line.strip().lower()
                if len(stripped) > 10:
                    total_content_lines += 1
                    unique_lines.add(stripped)
            if total_content_lines > 3:
                unique_ratio = len(unique_lines) / total_content_lines
                if unique_ratio < 0.4:  # heavily repetitive
                    score -= 1.0
                elif unique_ratio < 0.7:
                    score -= 0.3
        # Penalties
        if any("block" in w.lower() or "captcha" in w.lower() for w in self.warnings):
            score -= 2.0
        if self.status_code and self.status_code >= 400:
            score -= 1.5
        return max(0.0, min(score, 10.0))

    def to_dict(self, max_chars: int = 12000) -> dict[str, Any]:
        text = self.text.strip()
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n…[truncated]"
        # Lazy import to avoid circular dependency (deep_research imports from core)
        from agentweb.deep_research import _authority_boost, _classify_source_type, _extract_date_from_text

        result = {
            "url": self.url,
            "final_url": self.final_url or self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "source": self.source,
            "title": self.title,
            "text": text,
            "links": self.links[:50],
            "metadata": self.metadata,
            "tactics": self.tactics,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
            "quality_score": round(self.quality_score(), 3),
        }
        result["meta"] = {
            "confidence": round(self.quality_score() / 10, 3),
            "domain_authority": _authority_boost(self.url or ""),
            "recency_hint": _extract_date_from_text(self.text or "") or "",
            "content_type": _classify_source_type(self.url or "", self.text or ""),
        }
        return result


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        from agentweb.deep_research import _authority_boost, _classify_source_type, _extract_date_from_text

        snippet_len = len(self.snippet.strip()) if self.snippet else 0
        # Heuristic confidence based on snippet length and source presence
        conf = min(snippet_len / 500, 1.0) if snippet_len else 0.2
        if self.source:
            conf = min(conf + 0.1, 1.0)
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "meta": {
                "confidence": round(conf, 3),
                "domain_authority": _authority_boost(self.url or ""),
                "recency_hint": _extract_date_from_text(self.snippet or "") or "",
                "content_type": _classify_source_type(self.url or "", self.snippet or ""),
            },
        }


def _session(timeout: int = 20, cookies: str | None = None, headers: dict[str, str] | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    if headers:
        s.headers.update(headers)
    if cookies:
        p = Path(cookies).expanduser()
        if p.exists():
            jar = MozillaCookieJar(str(p))
            jar.load(ignore_discard=True, ignore_expires=True)
            s.cookies.update(jar)
        else:
            s.headers["Cookie"] = cookies
    s.request = _timeout_wrapper(s.request, timeout)  # type: ignore[method-assign]
    return s


def _timeout_wrapper(fn, timeout: int):
    def wrapped(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return fn(method, url, **kwargs)

    return wrapped


def _get_default_session() -> requests.Session:
    """Return a shared session with connection pooling and standard headers."""
    global _DEFAULT_SESSION
    if _DEFAULT_SESSION is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": USER_AGENTS[0],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        _DEFAULT_SESSION = s
    return _DEFAULT_SESSION


_DEFAULT_SESSION: requests.Session | None = None


def _safe_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidURL(f"Unsupported URL: {url}", url=url)
    return urllib.parse.urlunparse(parsed)


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|canvas|template).*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(p|div|section|article|li|h[1-6]|tr|blockquote)>", "\n", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return _clean_text(raw)


def _clean_text(text: str) -> str:
    lines = []
    seen = set()
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        # Drop obvious nav boilerplate but keep repeated short facts out.
        low = line.lower()
        if low in {"skip to content", "menu", "subscribe", "sign in", "log in"}:
            continue
        key = line[:160]
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_title(raw: str) -> str:
    for pattern in [
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'(?is)<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
        r"(?is)<title[^>]*>(.*?)</title>",
        r"(?is)<h1[^>]*>(.*?)</h1>",
    ]:
        m = re.search(pattern, raw)
        if m:
            return _clean_text(_strip_html(m.group(1)))[:250]
    return ""


def _extract_metadata(raw: str, response: requests.Response | None = None) -> dict[str, str]:
    meta: dict[str, str] = {}
    if response is not None:
        for key in ["content-type", "last-modified", "etag"]:
            val = response.headers.get(key)
            if val:
                meta[key] = val
        if response.headers.get("date"):
            meta["fetched_server_date"] = response.headers["date"]
    for m in re.finditer(r'(?is)<meta\s+([^>]+)>', raw):
        attrs = dict(re.findall(r'([\w:-]+)=["\']([^"\']*)["\']', m.group(1)))
        name = attrs.get("name") or attrs.get("property")
        content = attrs.get("content")
        if name and content and name.lower() in {
            "description",
            "og:description",
            "article:published_time",
            "article:modified_time",
            "author",
        }:
            meta[name.lower()] = html.unescape(content).strip()
    return meta


def _extract_links(raw: str, base_url: str) -> list[dict[str, str]]:
    links = []
    seen = set()
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw):
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urllib.parse.urljoin(base_url, html.unescape(href))
        absolute = absolute.split("#", 1)[0]
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({"url": absolute, "text": _clean_text(_strip_html(label))[:160]})
        if len(links) >= 80:
            break
    return links


def _extract_nextjs_payload(raw: str) -> str:
    chunks: list[str] = []
    for m in re.finditer(r"self\.__next_f\.push\((.*?)\)</script>", raw, re.S):
        blob = html.unescape(m.group(1))
        strings = re.findall(r'"((?:[^"\\]|\\.){40,})"', blob)
        for s in strings:
            try:
                s = json.loads('"' + s + '"')
            except Exception:
                pass
            if re.search(r"[A-Za-z]{4}", s):
                chunks.append(s)
    cleaned = _clean_text("\n".join(chunks))
    return cleaned[:20000]


def _looks_blocked(text: str, status_code: int | None) -> bool:
    if status_code in {401, 403, 429, 503}:
        return True
    return bool(BLOCK_PATTERNS.search(text[:5000]))


def _is_wikipedia_url(url: str) -> str | None:
    """Detect Wikipedia article URLs and extract the page title.

    Returns the page title if the URL is a Wikipedia article, or None.
    """
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if not (domain.endswith("wikipedia.org") or domain.endswith("wikipedia.com")):
        return None
    # Parse path like /wiki/Page_Title or /en.wikipedia.org/wiki/Page_Title
    path = parsed.path.rstrip("/")
    # Support both /wiki/Title and language-prefixed /en/wiki/Title forms
    m = re.search(r"/wiki/([^/?#]+)", path)
    if m:
        return urllib.parse.unquote(m.group(1)).replace("_", " ")
    return None


def _fetch_wikipedia_article(url: str, timeout: int) -> FetchResult | None:
    """Fetch a Wikipedia article using the REST API v1.

    Returns a FetchResult with full article text as markdown-style content,
    or None if the URL is not a Wikipedia article or the API call fails.
    """
    title = _is_wikipedia_url(url)
    if not title:
        return None

    start = time.monotonic()
    try:
        # Try the summary endpoint first (faster, cleaner)
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
        session = _get_default_session()
        resp = session.get(summary_url, timeout=timeout)
        if resp.status_code >= 400:
            return None
        data = resp.json()

        extract = data.get("extract", "")
        if not extract:
            return None

        description = data.get("description", "")
        title_text = data.get("title", title)
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", url)
        # Build markdown-style content
        parts = [f"# {title_text}"]
        if description:
            parts.append(f"\n*{description}*\n")
        parts.append("")
        parts.append(extract)
        text = "\n".join(parts)

        elapsed = int((time.monotonic() - start) * 1000)
        return FetchResult(
            url=url,
            final_url=page_url,
            ok=True,
            status_code=resp.status_code,
            source="wikipedia_api",
            title=title_text,
            text=text,
            metadata={"source": "wikipedia", "description": description, "page_id": str(data.get("pageid", ""))},
            tactics=["wikipedia_api"],
            elapsed_ms=elapsed,
        )
    except Exception:
        return None


def _is_youtube_url(url: str) -> bool:
    """Detect if a URL is a YouTube video."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if "youtube.com" in domain or "youtu.be" in domain:
        # Must have a video ID in path or query
        if "youtu.be" in domain:
            return bool(parsed.path.strip("/"))
        # youtube.com/watch?v=VIDEO_ID
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs:
            return bool(qs["v"][0])
        # youtube.com/embed/VIDEO_ID or /shorts/VIDEO_ID
        if parsed.path.startswith(("/embed/", "/shorts/", "/v/")):
            return True
    return False


def _fetch_youtube_transcript(url: str, timeout: int) -> FetchResult | None:
    """Fetch a YouTube video transcript using yt-dlp or youtube_transcript_api.

    Returns structured text with timestamps, or None if unavailable.
    No API keys required — yt-dlp is free and youtube_transcript_api uses
    YouTube's public transcript endpoints.
    """
    if not _is_youtube_url(url):
        return None

    start = time.monotonic()
    title = ""
    description = ""
    transcript_text = ""

    # Strategy 1: Use yt-dlp if available (handles most cases)
    yt_dlp_exe = shutil.which("yt-dlp")
    if yt_dlp_exe:
        try:
            # Get title and description
            info_result = subprocess.run(
                [yt_dlp_exe, "--skip-download", "--print", "title", "--print", "description", url],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            if info_result.returncode == 0:
                lines = info_result.stdout.strip().split("\n", 1)
                title = lines[0].strip() if lines else ""
                description = lines[1].strip() if len(lines) > 1 else ""

            # Try to get auto-subs transcript
            subprocess.run(
                [
                    yt_dlp_exe, "--skip-download",
                    "--write-auto-subs", "--sub-lang", "en",
                    "--convert-subs", "srt",
                    "--output", "/tmp/yt_transcript_%(id)s",
                    url,
                ],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            # Find the generated SRT file
            import glob
            srt_files = glob.glob("/tmp/yt_transcript_*.en.srt") or glob.glob("/tmp/yt_transcript_*.srt")
            if srt_files:
                srt_text = Path(srt_files[0]).read_text(encoding="utf-8", errors="replace")
                # Parse SRT: extract text lines (skip timestamps and sequence numbers)
                srt_lines = []
                for line in srt_text.splitlines():
                    line = line.strip()
                    if not line or "-->" in line or line.isdigit():
                        continue
                    srt_lines.append(line)
                transcript_text = "\n".join(srt_lines)
                # Clean up temp file
                try:
                    Path(srt_files[0]).unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass

    # Strategy 2: Try youtube_transcript_api Python package
    if not transcript_text:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-untyped]

            # Extract video ID from URL
            parsed = urllib.parse.urlparse(url)
            video_id = ""
            if "youtu.be" in parsed.netloc:
                video_id = parsed.path.strip("/").split("?")[0]
            else:
                qs = urllib.parse.parse_qs(parsed.query)
                video_id = qs.get("v", [""])[0]
            if video_id:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
                parts = []
                for entry in transcript_list:
                    seconds = int(entry["start"])
                    minutes = seconds // 60
                    secs = seconds % 60
                    timestamp = f"[{minutes:02d}:{secs:02d}]"
                    parts.append(f"{timestamp} {entry['text']}")
                transcript_text = "\n".join(parts)
        except ImportError:
            pass  # Package not available
        except Exception:
            pass

    if not transcript_text and not title:
        return None

    elapsed = int((time.monotonic() - start) * 1000)

    # Build structured text
    parts = []
    if title:
        parts.append(f"# {title}")
    if description:
        parts.append(f"\n{description}\n")
    if transcript_text:
        parts.append("## Transcript\n")
        parts.append(transcript_text)
    else:
        if title:
            parts.append("\n*Title and description available, no transcript found.*")

    text = "\n".join(parts)
    return FetchResult(
        url=url,
        final_url=url,
        ok=True,
        status_code=200,
        source="youtube_transcript",
        title=title or "YouTube Video",
        text=text,
        metadata={"source": "youtube", "description": description[:200] if description else ""},
        tactics=["youtube_transcript"],
        elapsed_ms=elapsed,
    )


def _fetch_arxiv_pdf_text(url: str, timeout: int) -> FetchResult | None:
    """Fetch an arXiv paper's abstract directly from its abstract page.

    Much better than trying to parse the PDF. Handles both abstract URLs
    (arxiv.org/abs/XXXX) and PDF URLs (arxiv.org/pdf/XXXX).
    """
    # Normalize to abstract URL
    abs_url = re.sub(r"/pdf/(\d+\.\d+)", r"/abs/\1", url)
    abs_url = re.sub(r"/pdf/(\d+\.\d+)\.pdf", r"/abs/\1", abs_url)

    if "/abs/" not in abs_url:
        return None

    start = time.monotonic()
    try:
        session = _get_default_session()
        resp = session.get(abs_url, timeout=timeout, headers={"User-Agent": USER_AGENTS[0]})
        if resp.status_code >= 400:
            return None
        raw = resp.text

        # Extract title
        title = ""
        m = re.search(r'<meta\s+name="citation_title"\s+content="([^"]+)"', raw)
        if m:
            title = html.unescape(m.group(1))

        # Extract authors
        authors = []
        for m in re.finditer(r'<meta\s+name="citation_author"\s+content="([^"]+)"', raw):
            authors.append(html.unescape(m.group(1)))

        # Extract abstract
        abstract = ""
        m = re.search(r'<blockquote\s+class="abstract[^"]*"[^>]*>\s*(.*?)\s*</blockquote>', raw, re.DOTALL)
        if m:
            abstract = _strip_html(m.group(1))
        else:
            m = re.search(r'<meta\s+name="citation_abstract"\s+content="([^"]+)"', raw)
            if m:
                abstract = html.unescape(m.group(1))

        # Extract subjects/categories
        subjects = []
        for m in re.finditer(r'<span\s+class="primary-subject"[^>]*>(.*?)</span>', raw):
            subjects.append(_strip_html(m.group(1)))

        if not abstract and not title:
            return None

        # Build structured markdown
        parts = [f"# {title or 'arXiv Paper'}", ""]
        if authors:
            parts.append(f"**Authors:** {', '.join(authors)}")
        if subjects:
            parts.append(f"**Subjects:** {', '.join(subjects)}")
        parts.append(f"**URL:** {abs_url}")
        parts.append("")
        if abstract:
            parts.append("## Abstract")
            parts.append(abstract)

        text = "\n".join(parts)
        elapsed = int((time.monotonic() - start) * 1000)

        return FetchResult(
            url=url,
            final_url=abs_url,
            ok=True,
            status_code=resp.status_code,
            source="arxiv_abstract",
            title=title or "arXiv Paper",
            text=text,
            metadata={"authors": ", ".join(authors), "subjects": ", ".join(subjects)} if authors else {},
            tactics=["arxiv_abstract"],
            elapsed_ms=elapsed,
        )
    except Exception:
        return None


def fetch_url(
    url: str,
    *,
    timeout: int = 20,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
    max_chars: int = 12000,
    use_jina: bool = True,
    use_browser: bool = False,
) -> FetchResult:
    start = time.monotonic()
    url = _safe_url(url)
    result = FetchResult(url=url)
    tactics: list[str] = []
    warnings: list[str] = []

    # ── Specialized extractors (run first, they produce better content) ──
    # Wikipedia full article via REST API
    if _is_wikipedia_url(url):
        wiki_result = _fetch_wikipedia_article(url, timeout)
        if wiki_result and wiki_result.ok and wiki_result.text:
            wiki_result.elapsed_ms = max(wiki_result.elapsed_ms, int((time.monotonic() - start) * 1000))
            return wiki_result

    # YouTube transcript extraction
    if _is_youtube_url(url):
        yt_result = _fetch_youtube_transcript(url, timeout)
        if yt_result and yt_result.ok and yt_result.text:
            yt_result.elapsed_ms = max(yt_result.elapsed_ms, int((time.monotonic() - start) * 1000))
            return yt_result

    # arXiv abstract extraction (better than PDF parsing)
    if "/abs/" in url or "/pdf/" in url and "arxiv.org" in url.lower():
        arxiv_result = _fetch_arxiv_pdf_text(url, timeout)
        if arxiv_result and arxiv_result.ok and arxiv_result.text:
            arxiv_result.elapsed_ms = max(arxiv_result.elapsed_ms, int((time.monotonic() - start) * 1000))
            return arxiv_result

    # ── Generic HTTP fetch ──
    s = _session(timeout=timeout, cookies=cookies, headers=headers)
    raw = ""
    response: requests.Response | None = None
    try:
        tactics.append("direct_http")
        response = s.get(url, allow_redirects=True)
        result.status_code = response.status_code
        result.final_url = response.url
        ctype = response.headers.get("content-type", "")
        if not any(h in ctype for h in TEXT_MIME_HINTS) and response.content:
            warnings.append(f"non_text_content_type:{ctype or 'unknown'}")
        response.encoding = response.encoding or response.apparent_encoding
        raw = response.text or ""
    except Exception as exc:
        warnings.append(f"direct_http_failed:{type(exc).__name__}:{exc}")

    text = ""
    if raw:
        next_payload = _extract_nextjs_payload(raw)
        visible = _strip_html(raw)
        text = visible
        if next_payload and len(next_payload) > len(visible) * 0.25:
            tactics.append("nextjs_rsc_payload")
            text = _clean_text(visible + "\n\n[Next.js/RSC payload]\n" + next_payload)
        result.title = _extract_title(raw)
        result.links = _extract_links(raw, result.final_url or url)
        result.metadata = _extract_metadata(raw, response)
        if _looks_blocked(raw + "\n" + text, result.status_code):
            warnings.append("possible_bot_block_or_login_wall")

    # Jina reader is excellent for article-like public pages and often beats ad-heavy HTML.
    if use_jina and (not text or len(text) < 1200 or warnings):
        jina = _fetch_jina(url, timeout=timeout)
        if jina and len(jina.text) > len(text):
            tactics.append("jina_reader")
            text = jina.text
            result.title = result.title or jina.title
            result.metadata.update(jina.metadata)
            warnings.extend(jina.warnings)

    # Optional browser fallback. Kept opt-in because browsers are expensive.
    if use_browser and (not text or _looks_blocked(text, result.status_code)):
        browser_text = _fetch_with_agent_browser(url, timeout=timeout)
        if browser_text and len(browser_text) > len(text):
            tactics.append("agent_browser_snapshot")
            text = browser_text

    result.text = text[:max_chars] if max_chars else text
    result.ok = bool(text) and not (result.status_code and result.status_code >= 500)
    result.source = tactics[-1] if tactics else "none"
    result.tactics = tactics
    result.warnings = sorted(set(warnings))
    result.elapsed_ms = int((time.monotonic() - start) * 1000)

    # Raise structured errors when no content could be fetched after all tactics.
    if not result.ok and not text:
        if result.status_code == 429:
            raise RateLimited(
                f"Rate limited fetching {url} (HTTP 429)",
                retry_after=10,
            )
        if result.status_code in (401, 403):
            raise BotBlocked(
                f"Request blocked (HTTP {result.status_code}) fetching {url}",
                url=url,
            )
        # Look for timeout signals in warnings.
        for w in warnings:
            w_lower = w.lower()
            if "timeout" in w_lower or "timed out" in w_lower:
                raise Timeout(
                    f"Request timed out fetching {url} after {timeout}s",
                    timeout=timeout,
                )
        # When a response was received, check content for block patterns.
        if raw and _looks_blocked(raw, result.status_code):
            raise BotBlocked(
                "Response content suggests bot blocking or login wall",
                url=url,
            )
        # Generic failure — nothing more specific to report.
        raise AgentWebError(
            f"Failed to fetch {url}: {'; '.join(warnings) or 'unknown error'}",
            code="fetch_failed",
        )

    return result


def _fetch_jina(url: str, timeout: int = 20) -> FetchResult | None:
    reader_url = "https://r.jina.ai/http://" + re.sub(r"^https?://", "", url)
    if url.startswith("https://"):
        reader_url = "https://r.jina.ai/http://" + url[len("https://") :]
    try:
        resp = requests.get(reader_url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
        text = resp.text or ""
        if resp.status_code >= 400 or not text.strip():
            return None
        title = ""
        m = re.search(r"^Title:\s*(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        return FetchResult(
            url=url,
            final_url=url,
            ok=True,
            status_code=resp.status_code,
            source="jina_reader",
            title=title,
            text=_clean_text(text),
            metadata={"reader": "jina.ai"},
            tactics=["jina_reader"],
        )
    except Exception as exc:
        return FetchResult(url=url, warnings=[f"jina_failed:{type(exc).__name__}:{exc}"])


def _fetch_with_agent_browser(url: str, timeout: int = 30) -> str:
    exe = shutil.which("agent-browser")
    if not exe:
        return ""
    # agent-browser subcommands vary across versions; try the stable text/snapshot shapes.
    commands = [
        [exe, "snapshot", url, "--full"],
        [exe, "navigate", url, "--snapshot"],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if proc.returncode == 0 and len(out.strip()) > 200:
                return _clean_text(out)
        except Exception:
            continue
    return ""


def _search_duckduckgo_html(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
    raw = resp.text
    items: list[SearchResult] = []
    for block in re.findall(r'(?is)<div class="result results_links.*?</div>\s*</div>', raw):
        href_match = re.search(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not href_match:
            continue
        href = html.unescape(href_match.group(1))
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            href = qs["uddg"][0]
        if _is_duckduckgo_ad_url(href):
            continue
        snippet = ""
        sn = re.search(r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', block)
        if sn:
            snippet = _clean_text(_strip_html(sn.group(1)))
        items.append(SearchResult(_clean_text(_strip_html(href_match.group(2))), href, snippet, "duckduckgo"))
        if len(items) >= max_results:
            break
    return items


def _is_duckduckgo_ad_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = p.netloc.lower()
    qs = urllib.parse.parse_qs(p.query)
    return host.endswith("duckduckgo.com") and (p.path.endswith("/y.js") or "ad_domain" in qs or "ad_provider" in qs)


def _search_hn_algolia(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(
        {"query": query, "tags": "story", "hitsPerPage": min(max_results, 10)}
    )
    resp = requests.get(url, timeout=timeout)
    data = resp.json()
    items = []
    for hit in data.get("hits", []):
        target = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        title = hit.get("title") or hit.get("story_title") or "Hacker News result"
        points = hit.get("points")
        comments = hit.get("num_comments")
        snippet = f"HN: {points or 0} points, {comments or 0} comments"
        items.append(SearchResult(title, target, snippet, "hackernews"))
    return items


def research(
    query: str,
    *,
    max_results: int = 6,
    timeout: int = 20,
    max_chars: int = 6000,
    refine: str = "",
    exclude_sources: list[str] | None = None,
) -> dict[str, Any]:
    # Apply refine: append refinement text to the search query
    search_query = f"{query} {refine}".strip() if refine else query

    search_results = search_web(search_query, max_results=max_results, timeout=timeout)

    # Apply exclude_sources on search results
    if exclude_sources:
        exclude_lower = {s.lower() for s in exclude_sources}
        search_results = [
            r for r in search_results
            if not any(excl in (r.source or "").lower() for excl in exclude_lower)
        ]

    fetched: list[FetchResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(search_results)))) as pool:
        fut_map = {
            pool.submit(fetch_url, r.url, timeout=timeout, max_chars=max_chars, use_jina=True): r
            for r in search_results
        }
        for fut in concurrent.futures.as_completed(fut_map):
            try:
                fetched.append(fut.result())
            except Exception as exc:
                sr = fut_map[fut]
                fetched.append(FetchResult(url=sr.url, title=sr.title, warnings=[f"fetch_failed:{exc}"]))
    fetched.sort(key=lambda r: r.quality_score(), reverse=True)

    # Apply exclude_sources on fetched results
    if exclude_sources:
        exclude_lower = {s.lower() for s in exclude_sources}
        fetched = [
            r for r in fetched
            if not any(excl in (r.source or "").lower() for excl in exclude_lower)
        ]

    # Compute coverage and gaps using deep_research utilities
    from agentweb.deep_research import (
        _detect_knowledge_gaps,
        _research_coverage_score,
        _suggest_followups,
    )

    coverage_score = _research_coverage_score(query, fetched)
    knowledge_gaps = _detect_knowledge_gaps(query, fetched)
    suggested_followups = _suggest_followups(query, knowledge_gaps)

    return {
        "query": query,
        "generated_at": email.utils.formatdate(usegmt=True),
        "coverage_score": round(coverage_score * 100, 1),  # 0–100% scale
        "knowledge_gaps": knowledge_gaps,
        "suggested_followups": suggested_followups,
        "search_results": [r.to_dict() for r in search_results],
        "sources": [r.to_dict(max_chars=max_chars) for r in fetched],
        "answer_pack": _answer_pack(query, fetched),
    }


def _answer_pack(query: str, sources: Iterable[FetchResult]) -> dict[str, Any]:
    q_terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9]{3,}", query)}
    bullets = []
    for src in sources:
        if not src.text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n+", src.text)
        ranked = []
        for s in sentences:
            terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9]{3,}", s)}
            overlap = len(q_terms & terms)
            if overlap and 60 <= len(s) <= 500:
                ranked.append((overlap, len(s), s.strip()))
        ranked.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        for _, _, sent in ranked[:2]:
            bullets.append({"claim_or_evidence": sent, "source": src.final_url or src.url, "title": src.title})
        if len(bullets) >= 10:
            break
    return {
        "usage_note": "Use these as evidence snippets, not a final answer. Verify conflicts across sources.",
        "evidence": bullets[:10],
    }


def _canonical_url(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        return urllib.parse.urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", "", ""))
    except Exception:
        return url


def format_markdown_fetch(result: FetchResult, max_chars: int = 12000) -> str:
    data = result.to_dict(max_chars=max_chars)
    parts = [f"# {data['title'] or data['final_url']}", ""]
    parts.append(f"URL: {data['final_url']}")
    parts.append(f"Status: {data['status_code']} | Source: {data['source']} | Quality: {data['quality_score']}")
    if data["warnings"]:
        parts.append("Warnings: " + ", ".join(data["warnings"]))
    parts.append("\n## Text\n")
    parts.append(data["text"])
    if data["links"]:
        parts.append("\n## Links\n")
        for link in data["links"][:20]:
            label = link.get("text") or link["url"]
            parts.append(f"- [{label}]({link['url']})")
    return "\n".join(parts).strip() + "\n"


def format_markdown_research(pack: dict[str, Any]) -> str:
    parts = [f"# AgentWeb research: {pack['query']}", "", f"Generated: {pack['generated_at']}", ""]
    parts.append("## Evidence snippets")
    for i, ev in enumerate(pack.get("answer_pack", {}).get("evidence", []), 1):
        title = ev.get("title") or ev.get("source")
        parts.append(f"{i}. {ev['claim_or_evidence']}  ")
        parts.append(f"   Source: [{title}]({ev['source']})")
    parts.append("\n## Sources")
    for i, src in enumerate(pack.get("sources", []), 1):
        parts.append(f"### {i}. {src.get('title') or src.get('final_url')}")
        parts.append(f"URL: {src.get('final_url')}  ")
        parts.append(f"Quality: {src.get('quality_score')} | Tactics: {', '.join(src.get('tactics') or [])}")
        if src.get("warnings"):
            parts.append(f"Warnings: {', '.join(src['warnings'])}")
        text = src.get("text") or ""
        parts.append("\n" + text[:2500].strip())


# ═══════════════════════════════════════════════════════════════════
# PROVIDER-SPECIFIC SEARCH
# ═══════════════════════════════════════════════════════════════════

# Regex for cleaning arXiv XML text
_RE_ARXIV_CLEAN = re.compile(r"<[^>]+>")
_RE_MULTISPACE = re.compile(r"\s+")


def _search_arxiv_api(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search arXiv API for academic papers. Returns SearchResult list."""
    url = (
        "http://export.arxiv.org/api/query?"
        + urllib.parse.urlencode(
            {"search_query": f"all:{query}", "start": 0, "max_results": min(max_results, 10)}
        )
    )
    try:
        session = _get_default_session()
        resp = session.get(url, timeout=timeout)
        if resp.status_code >= 400:
            return []
        root = ET.fromstring(resp.text)
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        items: list[SearchResult] = []
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            title = _clean_text(_RE_ARXIV_CLEAN.sub("", (title_el.text or ""))) if title_el is not None else ""
            id_el = entry.find("a:id", ns)
            url_text = id_el.text.strip() if id_el is not None and id_el.text else ""
            summary_el = entry.find("a:summary", ns)
            summary = ""
            if summary_el is not None and summary_el.text:
                summary = _clean_text(_RE_ARXIV_CLEAN.sub(" ", summary_el.text))[:300]
            if title and url_text:
                items.append(SearchResult(title, url_text, summary, "arxiv"))
        return items[:max_results]
    except Exception:
        return []


def _search_wikipedia_api(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search Wikipedia opensearch API."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": query,
            "limit": min(max_results, 10),
            "namespace": 0,
            "format": "json",
        }
    )
    try:
        session = _get_default_session()
        resp = session.get(url, timeout=timeout)
        data = resp.json()
        if not data or len(data) < 4:
            return []
        titles, urls, descriptions = data[1], data[3], data[2] if len(data) > 2 else []
        items: list[SearchResult] = []
        for i, title in enumerate(titles):
            page_url = urls[i] if i < len(urls) else ""
            snippet = descriptions[i] if i < len(descriptions) else ""
            if title and page_url:
                items.append(SearchResult(title, page_url, snippet, "wikipedia"))
        return items[:max_results]
    except Exception:
        return []


def _decode_bing_url(url: str) -> str:
    """Extract the actual destination URL from a Bing/DDG tracking redirect URL.

    Bing wraps search-result links in ``bing.com/ck/a?...`` URLs with a
    base64-encoded real URL in the ``u`` query parameter (prefixed by 2
    salt bytes).  DuckDuckGo uses ``duckduckgo.com/l/?uddg=<urlencode>``.
    Falls back to the original URL on any parse failure.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        # DuckDuckGo: uddg param
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            decoded = urllib.parse.unquote(uddg)
            if decoded.startswith("http"):
                return decoded
        # Bing: base64 u param with 2-char prefix
        u_val = qs.get("u", [None])[0]
        if u_val and len(u_val) > 2:
            b64 = u_val[2:]
            padding = 4 - len(b64) % 4
            if padding != 4:
                b64 += "=" * padding
            decoded = base64.b64decode(b64).decode("utf-8")
            if decoded.startswith("http"):
                return decoded
    except Exception:
        pass
    return url


def _search_via_jina_reader(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """General web search via DuckDuckGo rendered through Jina Reader API.

    Jina's ``r.jina.ai`` reader bypasses bot-blocking on DuckDuckGo and
    returns clean markdown.  URLs are extracted from DDG redirect URLs.
    Free, no API key required.
    """
    ddg_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    reader_url = "https://r.jina.ai/http://" + re.sub(r"^https?://", "", ddg_url)

    try:
        session = _get_default_session()
        resp = session.get(reader_url, timeout=timeout)
        if resp.status_code >= 400:
            return []
        text = resp.text

        # Locate the ``Markdown Content:`` section.
        md_idx = text.find("Markdown Content:")
        if md_idx == -1:
            return []
        content = text[md_idx + len("Markdown Content:"):].strip()

        # Each search result in the markdown looks like:
        #   ## [**Title**](url)\n\nsnippet\n\n## ...
        # or:
        #   N.   ## [**Title**](url)\n\nsnippet\n\nN+1.  ## ...
        _RE_RESULT = re.compile(
            r"^\s*(?:\d+\.\s+)?##\s+\[([^\]]+)\]\(([^)]+)\)\s*\n"
            r"([\s\S]*?)"
            r"(?=\n\s*(?:\d+\.\s+)?##|\Z)",
            re.MULTILINE,
        )

        items: list[SearchResult] = []
        for m in _RE_RESULT.finditer(content):
            title = m.group(1).strip()
            # Strip markdown bold markers from title
            title = re.sub(r"\*{1,2}", "", title).strip()
            raw_url = m.group(2).strip()
            raw_snippet = m.group(3).strip()

            # Clean markdown bold markers from snippet
            snippet = re.sub(r"\*{1,2}", "", raw_snippet).strip()

            # Extract real URL from DDG/Bing redirect
            url = _decode_bing_url(raw_url)

            items.append(SearchResult(title, url, snippet, "duckduckgo_jina"))
            if len(items) >= max_results:
                break

        return items
    except Exception:
        return []


def _search_jina_general(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """General web search via Bing through Jina Reader API."""
    return _search_via_jina_reader(query, max_results, timeout)


def _search_github_api(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search GitHub repositories via the public search API.

    No API key required (rate-limited to 60/hr without key, 10/min for
    the search endpoint).  Returns repos with stars, description, and
    language — excellent for technical/niche queries.

    Source tag: "github"
    """
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 25)}
    )
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "AgentWeb/0.1",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return []
        data = resp.json()
        items: list[SearchResult] = []
        for repo in data.get("items", []):
            name = repo.get("full_name", "") or repo.get("name", "")
            repo_url = repo.get("html_url", "")
            description = (repo.get("description") or "")[:200]
            stars = repo.get("stargazers_count", 0)
            language = repo.get("language") or ""
            snippet = f"⭐ {stars} stars"
            if language:
                snippet += f" | {language}"
            if description:
                snippet = f"{description} — {snippet}"
            if name and repo_url:
                items.append(SearchResult(name, repo_url, snippet, "github"))
            if len(items) >= max_results:
                break
        return items
    except Exception:
        return []


def _search_reddit_api(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search Reddit using the public Reddit JSON API.

    Returns real Reddit posts with title, URL, score, comments, and subreddit.
    No API key required — Reddit's public JSON endpoint is free and accessible
    with a proper User-Agent.

    Rate limit: ~60 req/min unauthenticated.
    """
    url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode(
        {
            "q": query,
            "sort": "relevance",
            "limit": min(max_results, 25),
            "raw_json": 1,
            "t": "all",
        }
    )
    headers = {"User-Agent": "AgentWeb/0.1 (by /u/agentweb_search)"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        items: list[SearchResult] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = d.get("title", "")
            permalink = d.get("permalink", "")
            # Reddit post URL: external link for link posts, permalink for self posts
            post_url = d.get("url", "")
            if d.get("is_self") or not post_url or "reddit.com" in post_url.lower():
                post_url = "https://www.reddit.com" + permalink
            subreddit = d.get("subreddit", "")
            score = d.get("score", 0)
            comments = d.get("num_comments", 0)
            # Build rich snippet
            selftext = (d.get("selftext") or "")[:250]
            sentence = (
                selftext.replace("\n", " ").strip()
                if selftext
                else d.get("domain", "")
            )
            snippet = f"[r/{subreddit}] Score: {score} | Comments: {comments}"
            if sentence:
                snippet = f"{sentence[:200]} — {snippet}"
            items.append(SearchResult(title, post_url, snippet, "reddit"))
            if len(items) >= max_results:
                break
        return items
    except Exception:
        return []


def _search_reddit_site(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search Reddit via Jina general search with site:reddit.com operator."""
    site_query = f"site:reddit.com {query}"
    return _search_jina_general(site_query, max_results, timeout)


def _search_twitter_site(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search X/Twitter via DDG/Jina with site operators.

    Twitter's API requires OAuth, so we use ``site:twitter.com OR site:x.com``
    through DuckDuckGo HTML and Jina Reader in sequence.  Catches tweets
    and X posts in search results.

    Falls back cleanly with 0 results when Twitter content isn't indexed
    (common with modern Twitter restrictions).  The other 4 providers in
    the broad pipeline still deliver diverse results.

    Returns: SearchResult list with source="twitter".
    """
    site_query = f"site:twitter.com OR site:x.com {query}"
    # Try DDG HTML first (better for site: operator queries)
    try:
        results = _search_duckduckgo_html(site_query, max_results, timeout)
        if results:
            for r in results:
                r.source = "twitter"
            return results
    except Exception:
        pass
    # Fallback: Jina Reader through DDG
    return _search_jina_general(site_query, max_results, timeout)


# Provider dispatch table
def _search_nominatim(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search OpenStreetMap Nominatim for places, locations, food, travel.

    Free, no API key required (needs a polite User-Agent per their ToS).
    Returns: display name, OSM link, location type, lat/lon.

    Rate limit: 1 req/sec — be nice. Returns 0 results on 429.
    Source tag: "nominatim"
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": min(max_results, 10),
        "addressdetails": 0,
    }
    headers = {"User-Agent": "AgentWeb/0.1 (place search; nominatim@agentweb.dev)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        items: list[SearchResult] = []
        for place in data:
            display = place.get("display_name", "")
            name = display.split(",")[0] if display else "Unknown place"
            place_type = place.get("type", "")
            category = place.get("category", "")
            lat = place.get("lat", "")
            lon = place.get("lon", "")
            osm_type = place.get("osm_type", "node")
            osm_id = place.get("osm_id", 0)
            osm_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
            snippet = f"{category}/{place_type}"
            if lat and lon:
                snippet += f" \u2022 {lat}, {lon}"
            if display:
                snippet += f" \u2014 {display[:150]}"
            if name:
                items.append(SearchResult(name, osm_url, snippet, "nominatim"))
            if len(items) >= max_results:
                break
        return items
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════════
# SECTOR ROUTER — classify queries into domains, route to relevant providers
# ═══════════════════════════════════════════════════════════════════

# Sector seed terms for query classification.
# Multi-word seeds get 3× weight (stronger signal).
_SECTOR_SEEDS: dict[str, set[str]] = {
    "tech": {
        "code", "coding", "programming", "software", "app", "apps",
        "api", "framework", "library", "github", "git", "deploy",
        "server", "database", "python", "javascript", "react", "docker",
        "linux", "windows", "macos", "cli", "terminal", "algorithm",
        "bug", "error", "crash", "compile", "runtime", "debug",
        "startup", "saas", "cloud", "devops", "kubernetes", "aws",
        "ai", "ml", "llm", "neural", "gpu", "tensorflow", "pytorch",
        "website", "web", "backend", "frontend", "fullstack",
        "computer", "laptop", "monitor", "keyboard", "tech",
        "download", "install", "setup", "configuration",
        "tutorial", "guide", "documentation",
    },
    "food": {
        "food", "foods", "recipe", "recipes", "cook", "cooking", "bake", "baking",
        "restaurant", "restaurants", "cafe", "cuisine", "dish", "dishes",
        "meal", "meals", "dinner", "dinners", "lunch", "breakfast", "ingredient", "chef", "kitchen",
        "delicious", "tasty", "flavor", "spicy", "sweet",
        "pho", "pizza", "pasta", "sushi", "burger", "salad",
        "chicken", "beef", "pork", "fish", "vegetarian", "vegan",
        "wine", "coffee", "tea", "beer", "cocktail",
        "nutrition", "calories", "healthy eating",
        "eat", "dining", "brunch",
        "bread", "soup", "sauce", "pancake", "pancakes",
        "chocolate", "cheese", "butter", "rice", "noodle", "noodles",
        "fruit", "vegetable", "vegetables", "tofu", "egg", "eggs",
        "bake", "roast", "roasting", "grill", "fry", "frying",
        "yummy", "homemade", "organic",
        "snack", "snacks",
    },
    "travel": {
        "travel", "trip", "trips", "vacation", "holiday", "holidays",
        "tourist", "tourism", "tour",
        "hotel", "hotels", "hostel", "hostels", "resort", "resorts",
        "flight", "flights", "airport", "airports", "airline", "airlines",
        "destination", "destinations", "visit", "sightseeing", "attraction", "attractions",
        "beach", "beaches", "mountain", "mountains", "hiking", "camping", "road trip",
        "passport", "visa", "backpacking", "cruise",
        "city", "cities", "country", "countries", "province", "island", "islands", "abroad",
        "map", "direction", "directions", "location", "address", "near me",
        "museum", "museums", "park", "parks", "temple", "church", "churches", "market",
        "accommodation", "lodging",
        "itinerary", "explore", "wander",
    },
    "shopping": {
        "buy", "purchase", "order", "shop", "shopping", "store",
        "product", "price", "cost", "cheap", "expensive", "deal",
        "discount", "sale", "coupon", "offer",
        "amazon", "ebay", "etsy", "walmart", "aliexpress",
        "delivery", "shipping", "return", "warranty",
        "review", "reviews", "rating", "ratings", "top",
        "gift", "gifts", "present", "accessory", "fashion", "clothing",
        "electronics", "gadget", "gadgets", "furniture", "decor",
        "headphones", "speaker", "speakers", "laptop", "laptops",
        "phone", "phones", "tablet", "tablets", "camera", "cameras",
        "tv", "monitor", "monitors", "printer", "printers",
    },
    "health": {
        "health", "healthy", "fitness", "exercise", "workout",
        "diet", "weight loss", "muscle", "yoga", "meditation",
        "doctor", "hospital", "clinic", "pharmacy", "medicine",
        "symptom", "disease", "illness", "condition", "treatment",
        "therapy", "surgery", "diagnosis", "prevention",
        "vitamin", "supplement", "protein",
        "mental health", "anxiety", "depression",
        "sleep", "insomnia", "headache", "pain",
        "pregnancy", "baby",
    },
    "academic": {
        "paper", "research", "study", "academic", "preprint",
        "publication", "scientific", "scholar", "doi",
        "conference", "journal", "experiment", "methodology",
        "benchmark", "dataset", "thesis", "dissertation",
        "professor", "lecture", "curriculum",
        "science", "mathematics", "physics", "chemistry", "biology",
    },
    "entertainment": {
        "movie", "movies", "film", "films", "tv", "show", "shows",
        "series", "episode", "episodes",
        "music", "song", "songs", "album", "albums", "artist", "artists",
        "band", "concert", "concerts",
        "game", "games", "gaming", "video game", "playstation", "xbox", "nintendo",
        "book", "books", "novel", "novels", "author", "authors",
        "reading", "literature",
        "anime", "manga", "comic", "comics", "cartoon", "cartoons",
        "sport", "sports", "football", "soccer", "basketball", "tennis",
        "celebrity", "celebrities", "actor", "actors", "actress", "actresses", "director",
        "stream", "streaming", "netflix", "youtube", "spotify",
        "funny", "joke", "jokes", "meme", "memes",
        "watch", "listen", "walkthrough", "walkthroughs", "gameplay",
        "review", "reviews", "rating", "ratings",
    },
    "news": {
        "news", "breaking", "headline", "headlines", "report", "reports",
        "coverage", "latest", "update", "updates", "announcement", "announcements",
        "election", "policy", "government", "politics", "political",
        "economy", "market", "markets", "stock", "stocks", "crypto", "bitcoin",
        "war", "conflict", "protest", "protests", "scandal",
    },
}

_STOPWORDS_SECTOR: frozenset[str] = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "was", "one", "our", "out", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "way", "who",
    "did", "she", "use", "via", "that", "from", "have", "been",
    "were", "said", "also", "they", "this", "what", "than",
    "with", "their", "about", "into", "over", "after", "some",
    "more", "most", "much", "many", "very", "just", "like",
})


def _classify_sector(query: str) -> str:
    """Classify a query into a sector using keyword overlap scoring.

    Returns one of: tech, food, travel, shopping, health, academic,
    entertainment, news, general.
    """
    q_lower = query.lower()
    tokens = {m.group() for m in re.finditer(r"[a-zA-Z]{3,}", q_lower)
              if m.group() not in _STOPWORDS_SECTOR}

    best_sector = "general"
    best_score = 0

    for sector, seeds in _SECTOR_SEEDS.items():
        score = 0
        for seed in seeds:
            if " " in seed:
                # Multi-word seed: substring match gives strong signal
                if seed in q_lower:
                    score += 3
            else:
                if seed in tokens:
                    score += 1
        if score > best_score:
            best_score = score
            best_sector = sector

    # If no sector scored above a single keyword match, stay general
    if best_score <= 0:
        return "general"
    return best_sector


# Sector → relevant search provider functions.
# Each sector only queries sources that make sense for its domain,
# avoiding noise from irrelevant providers (e.g. HN for food queries).
_SECTOR_PROVIDERS: dict[str, list] = {
    "tech": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_hn_algolia, _search_github_api,
        _search_reddit_api, _search_arxiv_api,
    ],
    "food": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
        _search_nominatim,
    ],
    "travel": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
        _search_nominatim,
    ],
    "shopping": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
    ],
    "health": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
    ],
    "academic": [
        _search_arxiv_api, _search_wikipedia_api,
        _search_duckduckgo_html, _search_via_jina_reader,
    ],
    "entertainment": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
    ],
    "news": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_hn_algolia,
    ],
    "general": [
        _search_duckduckgo_html, _search_via_jina_reader,
        _search_reddit_api, _search_wikipedia_api,
    ],
}


def search_web(query: str, *, max_results: int = 8, timeout: int = 20) -> list[SearchResult]:
    """Search the web with sector-aware provider routing.

    The query is classified into a sector (tech, food, travel, shopping,
    health, academic, entertainment, news, or general), and only the
    providers relevant to that sector are queried in parallel.  This
    eliminates noise — HN/GitHub/arXiv are only queried for tech queries,
    Nominatim (OpenStreetMap) only for food/travel queries, etc.

    Results are **interleaved by source** for maximum diversity.

    Returns a deduplicated list of up to ``max_results`` SearchResult items.

    Raises:
        NoResults: If no results were returned by any provider.
        Timeout: If all providers timed out.
    """
    sector = _classify_sector(query)
    providers = _SECTOR_PROVIDERS.get(sector, _SECTOR_PROVIDERS["general"])

    # Collect results from all providers in parallel
    all_items: list[SearchResult] = []
    saw_timeout = False
    seen = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futs = [pool.submit(p, query, max_results, timeout) for p in providers]
        for fut in concurrent.futures.as_completed(futs):
            try:
                for item in fut.result():
                    key = _canonical_url(item.url)
                    if key and key not in seen:
                        seen.add(key)
                        all_items.append(item)
            except Exception as exc:
                # Track timeouts for structured error reporting
                exc_name = type(exc).__name__.lower()
                if "timeout" in exc_name or "timed out" in str(exc).lower():
                    saw_timeout = True
                continue

    if not all_items:
        if saw_timeout:
            raise Timeout(
                f"All search providers timed out for query: {query[:80]}",
                timeout=timeout,
            )
        raise NoResults(
            f"No search results found for query: {query[:80]}",
            query=query,
        )

    # Interleave results by source for maximum diversity
    by_source: dict[str, list[SearchResult]] = {}
    for item in all_items:
        src = item.source or "unknown"
        by_source.setdefault(src, []).append(item)

    interleaved: list[SearchResult] = []
    while any(by_source.values()):
        for src in list(by_source.keys()):
            if by_source.get(src):
                interleaved.append(by_source[src].pop(0))
                if len(interleaved) >= max_results:
                    return interleaved
    return interleaved


def _search_stackexchange_api(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    """Search StackOverflow and StackExchange sites via their public API.

    No API key needed for basic usage. Free but throttled (~300 req/day per IP).
    Returns results with: title, link, tags, score, answer_count.
    Searches stackoverflow.com by default; also tries stackexchange.com for broader coverage.
    """
    results: list[SearchResult] = []
    sites = ["stackoverflow", "stackexchange"]

    for site in sites:
        if len(results) >= max_results:
            break
        url = "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode(
            {
                "order": "desc",
                "sort": "relevance",
                "q": query,
                "site": site,
                "pagesize": min(max_results, 10),
            }
        )
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENTS[0]})
            if resp.status_code >= 400:
                continue
            data = resp.json()
            for item in data.get("items", []):
                title = html.unescape(item.get("title", ""))
                link = item.get("link", "")
                tags = item.get("tags", [])
                score = item.get("score", 0)
                answer_count = item.get("answer_count", 0)
                is_answered = item.get("is_answered", False)
                snippet = f"Score: {score} | Answers: {answer_count}"
                if tags:
                    snippet += f" | Tags: {', '.join(tags[:4])}"
                if is_answered:
                    snippet += " | ✓ Accepted"
                if title and link:
                    results.append(SearchResult(title, link, snippet, "stackexchange"))
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    return results[:max_results]


_SEARCH_PROVIDERS: dict[str, list] = {
    "duckduckgo": [_search_duckduckgo_html],
    "hackernews": [_search_hn_algolia],
    "arxiv": [_search_arxiv_api],
    "wikipedia": [_search_wikipedia_api],
    "reddit": [_search_reddit_api, _search_reddit_site],
    "github": [_search_github_api],
    "nominatim": [_search_nominatim],
    "twitter": [_search_twitter_site],
    "xcom": [_search_twitter_site],
    "bing": [_search_via_jina_reader],
    "jina": [_search_jina_general],
    "stackexchange": [_search_stackexchange_api],
    "general": [_search_duckduckgo_html, _search_via_jina_reader, _search_hn_algolia, _search_reddit_api, _search_stackexchange_api],
}

def search_by_provider(
    provider: str,
    query: str,
    *,
    max_results: int = 5,
    timeout: int = 20,
) -> list[SearchResult]:
    """Search using a specific named provider.

    Supported providers: duckduckgo, hackernews, arxiv, wikipedia,
    reddit, bing, jina, general (falls through providers).
    Returns deduplicated SearchResult list.

    Raises:
        NoResults: If no results were returned by any backend.
        Timeout: If all backends timed out.
    """
    backends = _SEARCH_PROVIDERS.get(provider, _SEARCH_PROVIDERS["general"])
    results: list[SearchResult] = []
    saw_timeout = False
    seen = set()
    for backend_fn in backends:
        try:
            for item in backend_fn(query, max_results, timeout):
                key = _canonical_url(item.url)
                if key and key not in seen:
                    seen.add(key)
                    results.append(item)
        except Exception as exc:
            exc_name = type(exc).__name__.lower()
            if "timeout" in exc_name or "timed out" in str(exc).lower():
                saw_timeout = True
            continue
        if len(results) >= max_results:
            break

    if not results:
        if saw_timeout:
            raise Timeout(
                f"All search backends timed out for provider '{provider}' query: {query[:80]}",
                timeout=timeout,
            )
        raise NoResults(
            f"No search results from provider '{provider}' for query: {query[:80]}",
            query=query,
        )
    return results[:max_results]


# ═══════════════════════════════════════════════════════════════════
# TF-IDF NOVELTY SCORING  (used by SDK already_knows parameter)
# ═══════════════════════════════════════════════════════════════════

_RE_SHORT_TOKEN = re.compile(r"[a-zA-Z0-9]{3,}")


def compute_novelty_scores(
    already_knows: list[str],
    result_texts: list[str],
) -> list[float]:
    """Compute TF-IDF novelty scores for each result vs ``already_knows`` texts.

    Algorithm
    ---------
    1. Compute **TF** (raw term counts) for each term across all ``already_knows``
       texts.
    2. Compute **IDF** using ``log(N / df)`` where *N* is the number of result
       texts and *df* is the number of result texts containing the term.
    3. Build **TF-IDF vectors** (``tf * idf``) for the already-knows text and
       for each result, then L2-normalise each vector to unit length.
    4. **overlap_score** = cosine similarity (dot product) between the
       normalised already-knows TF-IDF vector and each normalised result
       TF-IDF vector.
    5. **novel_score** = ``1 - overlap_score``.

    Returns
    -------
    list[float]
        One novelty score per result (0.0 = identical to already-known content,
        1.0 = completely novel / no overlap).

    Notes
    -----
    - Terms shorter than 3 characters are ignored.
    - If ``already_knows`` is empty or all result texts are empty, every result
      gets a novelty score of 1.0 (fully novel).
    """
    if not already_knows or not result_texts:
        return [1.0] * len(result_texts)

    # ── 1. Tokenise & build term-frequency dicts ───────────────────────
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

    # All unique terms across known + all results
    all_terms: set[str] = set(known_tf)
    for rt in result_tfs:
        all_terms.update(rt)

    # ── 2. IDF across the result corpus ────────────────────────────────
    N = len(result_tfs)
    doc_freq: dict[str, int] = {}
    for rt in result_tfs:
        for term in rt:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    # ── 3. TF-IDF vectors (L2-normalised) ──────────────────────────────
    def _tfidf_vector(
        tf: dict[str, int],
        idf_weight: float = 1.0,
    ) -> tuple[dict[str, float], float]:
        """Build a TF-IDF vector and return (vector, L2-norm)."""
        vec: dict[str, float] = {}
        sq_sum = 0.0
        for term, raw_tf in tf.items():
            idf = doc_freq.get(term, 0)
            # Add-one-smoothed IDF: 1 + log(N / df) guarantees idf >= 1
            # for any present term, while rare terms get higher weight.
            w = idf_weight * (1.0 + math.log(N / idf)) if idf > 0 else 0.0
            val = raw_tf * w
            vec[term] = val
            sq_sum += val * val
        return vec, math.sqrt(sq_sum) if sq_sum > 0 else 1.0

    known_vec, known_norm_v = _tfidf_vector(known_tf)

    scores: list[float] = []
    for rt_tf in result_tfs:
        res_vec, res_norm_v = _tfidf_vector(rt_tf)

        # Cosine similarity
        dot = sum(
            known_vec.get(t, 0.0) * res_vec.get(t, 0.0)
            for t in all_terms
        )
        overlap = dot / (known_norm_v * res_norm_v) if known_norm_v * res_norm_v > 0 else 0.0
        overlap = max(0.0, min(1.0, overlap))
        scores.append(1.0 - overlap)

    return scores
