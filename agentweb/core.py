"""AgentWeb core web-access engine.

The design goal is boring but useful: one CLI call gives an agent a compact,
cited, high-signal source pack instead of making it juggle search, curl,
readability extraction, browser fallbacks, and weird SPA payloads itself.
"""

from __future__ import annotations

import concurrent.futures
import email.utils
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

BLOCK_PATTERNS = re.compile(
    r"captcha|cloudflare|access denied|verify you are human|unusual traffic|bot detection|blocked|"
    r"just a moment|please wait for verification|enable javascript and cookies|network security|"
    r"sign in to view|log in to your .*account|target url returned error\s+403|duckduckgo.*/anomaly\.js",
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
        score = 0.0
        combined = "\n".join([self.title, self.text])
        blocked = _looks_blocked(combined, self.status_code)

        if self.ok:
            score += 2.0
        if self.title and not blocked:
            score += 0.4
        text_len = len(self.text.strip())
        score += min(text_len / 2500.0, 3.0)
        if self.links and not blocked:
            score += 0.2

        warning_text = " ".join(self.warnings).lower()
        if any(term in warning_text for term in ("block", "captcha", "login", "verification")):
            score -= 5.0
        if self.status_code and self.status_code >= 400:
            score -= 3.0
        if blocked:
            score -= 6.0
        return score

    def to_dict(self, max_chars: int = 12000) -> dict[str, Any]:
        text = self.text.strip()
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n…[truncated]"
        return {
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


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source}


SearchProvider = Callable[[str, int, int], list[SearchResult]]


@dataclass(frozen=True)
class SearchService:
    """A no-key discovery service with a subject-matter bias."""

    name: str
    provider: SearchProvider
    subjects: tuple[str, ...] = ("general",)
    weight: float = 1.0


@dataclass(frozen=True)
class SubjectProfile:
    """Lightweight query routing so research is not tech/web-only."""

    subjects: tuple[str, ...]
    services: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"subjects": list(self.subjects), "services": list(self.services)}


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


def _safe_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported URL: {url}")
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


def _extract_structured_data(raw: str) -> list[dict[str, Any]]:
    """Extract JSON-LD blocks so agents get data beyond visible boilerplate."""
    out: list[dict[str, Any]] = []
    for m in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw):
        blob = html.unescape(m.group(1)).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                if "@graph" in item and isinstance(item["@graph"], list):
                    out.extend(x for x in item["@graph"] if isinstance(x, dict))
                else:
                    out.append(item)
    return out[:20]


def _structured_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "headline", "description", "text", "url"):
            if value.get(key):
                return _structured_value(value[key])
    if isinstance(value, list):
        return ", ".join(filter(None, (_structured_value(v) for v in value)))
    return ""


def _structured_data_text(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    interesting = ["@type", "headline", "name", "description", "datePublished", "dateModified", "author", "publisher", "url"]
    for item in items[:10]:
        parts = []
        for key in interesting:
            val = _structured_value(item.get(key))
            if val:
                parts.append(f"{key}: {val}")
        if parts:
            lines.append("; ".join(parts))
    return _clean_text("\n".join(lines))


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


def _classify_fetch_result(result: FetchResult) -> FetchResult:
    blocked = _looks_blocked("\n".join([result.title, result.text]), result.status_code)
    if blocked:
        result.ok = False
        if "blocker_or_login_wall" not in result.warnings:
            result.warnings.append("blocker_or_login_wall")
    elif not result.text.strip():
        result.ok = False
        if "empty_text" not in result.warnings:
            result.warnings.append("empty_text")
    else:
        result.ok = not (result.status_code and result.status_code >= 500)
    result.warnings = sorted(set(result.warnings))
    return result


def fetch_url(
    url: str,
    *,
    timeout: int = 20,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
    max_chars: int = 12000,
    use_jina: bool = True,
    use_browser: bool = False,
    use_camoufox: bool = False,
) -> FetchResult:
    start = time.monotonic()
    url = _safe_url(url)
    result = FetchResult(url=url)
    tactics: list[str] = []
    warnings: list[str] = []

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
        structured = _structured_data_text(_extract_structured_data(raw))
        visible = _strip_html(raw)
        text = visible
        if structured:
            text = _clean_text(text + "\n\n[Structured data]\n" + structured)
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
        if jina:
            _classify_fetch_result(jina)
        if jina and jina.ok and len(jina.text) > len(text):
            tactics.append("jina_reader")
            text = jina.text
            result.title = result.title or jina.title
            result.metadata.update(jina.metadata)
            warnings.extend(jina.warnings)

    if use_camoufox and (not text or _looks_blocked("\n".join([result.title, text]), result.status_code)):
        camoufox_text = _fetch_with_camoufox(url, timeout=timeout)
        if camoufox_text and not _looks_blocked(camoufox_text, None):
            tactics.append("camoufox_browser")
            text = camoufox_text
            result.title = ""
            result.status_code = None
            warnings = [w for w in warnings if "block" not in w.lower() and "login" not in w.lower()]
            warnings.append("camoufox_rendered_from_blocked_page")

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
    return _classify_fetch_result(result)


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


def _fetch_with_camoufox(url: str, timeout: int = 30) -> str:
    """Optional bot-resistant browser fallback. No hard dependency: returns empty if absent."""
    script = r'''
import sys
try:
    from camoufox.sync_api import Camoufox
except Exception:
    sys.exit(2)
url = sys.argv[1]
with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(url, wait_until="networkidle", timeout=int(sys.argv[2]) * 1000)
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        text = page.content()
    print((title + "\n" + text).strip())
'''
    try:
        proc = subprocess.run(
            [shutil.which("python3") or "python3", "-c", script, url, str(timeout)],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode == 0 and len(proc.stdout.strip()) > 100:
        return _clean_text(proc.stdout)
    return ""


def search_web(
    query: str,
    *,
    max_results: int = 8,
    timeout: int = 20,
    services: list[str] | tuple[str, ...] | None = None,
) -> list[SearchResult]:
    selected_services = _select_search_services(query, services)
    providers = [svc.provider for svc in selected_services]
    results: list[SearchResult] = []
    seen = set()
    if not providers:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futs = [pool.submit(p, query, max_results, timeout) for p in providers]
        for fut in concurrent.futures.as_completed(futs):
            try:
                for item in fut.result():
                    key = _canonical_url(item.url)
                    if key and key not in seen:
                        seen.add(key)
                        results.append(item)
            except Exception:
                continue
    return _balance_search_results(results, max_results=max_results)


def infer_subject_profile(query: str, services: list[str] | tuple[str, ...] | None = None) -> SubjectProfile:
    selected = _select_search_services(query, services)
    subjects = []
    for svc in selected:
        for subject in svc.subjects:
            if subject not in subjects:
                subjects.append(subject)
    return SubjectProfile(subjects=tuple(subjects or ["general"]), services=tuple(svc.name for svc in selected))


def _select_search_services(query: str, services: list[str] | tuple[str, ...] | None = None) -> list[SearchService]:
    registry = _search_service_registry()
    if services:
        selected: list[SearchService] = []
        for name in services:
            if name == "all":
                return list(registry.values())
            if name not in registry:
                raise ValueError(f"Unknown search service {name!r}. Available: {', '.join(registry)}")
            selected.append(registry[name])
        return selected

    q = query.lower()
    wanted = {"duckduckgo", "wikipedia", "wikidata"}
    subject_rules = [
        (("paper", "study", "journal", "doi", "citation", "scholar", "arxiv", "preprint", "research"), {"openalex", "crossref", "arxiv"}),
        (("medicine", "medical", "clinical", "disease", "drug", "therapy", "trial", "pubmed", "biology", "genome"), {"pubmed", "openalex"}),
        (("code", "github", "repository", "library", "sdk", "api", "package", "framework"), {"github", "hackernews"}),
        (("startup", "product", "pricing", "saas", "company", "market", "competitor"), {"hackernews", "github"}),
        (("history", "biography", "country", "city", "artist", "philosophy", "law", "policy"), {"wikipedia", "wikidata"}),
    ]
    for terms, additions in subject_rules:
        if any(term in q for term in terms):
            wanted.update(additions)
    # Keep the default pack broad without turning every query into a slow API carnival.
    ordered = ["duckduckgo", "wikipedia", "wikidata", "openalex", "crossref", "arxiv", "pubmed", "github", "hackernews"]
    return [registry[name] for name in ordered if name in wanted]


def _balance_search_results(results: list[SearchResult], *, max_results: int) -> list[SearchResult]:
    """Avoid one provider flooding the pack; subject coverage beats monoculture."""
    buckets: dict[str, list[SearchResult]] = {}
    for item in results:
        buckets.setdefault(item.source or "unknown", []).append(item)
    balanced: list[SearchResult] = []
    while len(balanced) < max_results and any(buckets.values()):
        for source in sorted(buckets):
            if buckets[source]:
                balanced.append(buckets[source].pop(0))
                if len(balanced) >= max_results:
                    break
    return balanced


def _search_service_registry() -> dict[str, SearchService]:
    return {
        "duckduckgo": SearchService("duckduckgo", _search_duckduckgo_html, ("general",), 1.0),
        "wikipedia": SearchService("wikipedia", _search_wikipedia, ("encyclopedic", "humanities", "general"), 0.9),
        "wikidata": SearchService("wikidata", _search_wikidata, ("facts", "entities", "general"), 0.8),
        "openalex": SearchService("openalex", _search_openalex, ("scholarly", "science"), 0.9),
        "crossref": SearchService("crossref", _search_crossref, ("scholarly", "citation"), 0.8),
        "arxiv": SearchService("arxiv", _search_arxiv, ("scholarly", "preprints", "science"), 0.8),
        "pubmed": SearchService("pubmed", _search_pubmed, ("medicine", "biology", "clinical"), 0.8),
        "github": SearchService("github", _search_github_repositories, ("software", "code"), 0.8),
        "hackernews": SearchService("hackernews", _search_hn_algolia, ("software", "startups", "tech"), 0.6),
    }


def list_search_services() -> list[dict[str, Any]]:
    return [
        {"name": svc.name, "subjects": list(svc.subjects), "weight": svc.weight}
        for svc in _search_service_registry().values()
    ]


def _search_wikipedia(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "opensearch", "search": query, "limit": min(max_results, 5), "namespace": 0, "format": "json"}
    )
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
    data = resp.json()
    titles = data[1] if len(data) > 1 else []
    snippets = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    return [SearchResult(t, u, snippets[i] if i < len(snippets) else "", "wikipedia") for i, (t, u) in enumerate(zip(titles, urls))]


def _search_openalex(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
        {"search": query, "per-page": min(max_results, 5), "select": "title,doi,publication_year,authorships,primary_location"}
    )
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
    data = resp.json()
    items: list[SearchResult] = []
    for work in data.get("results", []):
        title = work.get("title") or "OpenAlex result"
        loc = work.get("primary_location") or {}
        source = loc.get("landing_page_url") or work.get("doi")
        if not source:
            continue
        year = work.get("publication_year")
        authors = [a.get("author", {}).get("display_name") for a in work.get("authorships", [])[:3]]
        snippet = ", ".join([str(year or ""), ", ".join(x for x in authors if x)]).strip(", ")
        items.append(SearchResult(title, source, snippet, "openalex"))
    return items


def _search_crossref(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query": query, "rows": min(max_results, 5), "select": "title,DOI,published-print,published-online,author,container-title"}
    )
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
    data = resp.json()
    items: list[SearchResult] = []
    for work in data.get("message", {}).get("items", []):
        titles = work.get("title") or []
        title = titles[0] if titles else "Crossref work"
        doi = work.get("DOI")
        if not doi:
            continue
        authors = []
        for author in work.get("author", [])[:3]:
            name = " ".join(filter(None, [author.get("given"), author.get("family")]))
            if name:
                authors.append(name)
        year = _crossref_year(work)
        journal = (work.get("container-title") or [""])[0]
        snippet = ", ".join(filter(None, [str(year or ""), journal, ", ".join(authors)]))
        items.append(SearchResult(title, f"https://doi.org/{doi}", snippet, "crossref"))
    return items


def _crossref_year(work: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        parts = work.get(key, {}).get("date-parts") or []
        if parts and parts[0]:
            return parts[0][0]
    return None


def _search_arxiv(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": "all:" + query, "start": 0, "max_results": min(max_results, 5)}
    )
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout)
    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[SearchResult] = []
    for entry in root.findall("atom:entry", ns):
        title = _clean_text(entry.findtext("atom:title", default="arXiv paper", namespaces=ns))
        link = ""
        for node in entry.findall("atom:link", ns):
            if node.attrib.get("rel") == "alternate" or not link:
                link = node.attrib.get("href", link)
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))[:300]
        published = entry.findtext("atom:published", default="", namespaces=ns)[:10]
        snippet = " — ".join(filter(None, [published, summary]))
        if link:
            items.append(SearchResult(title, link, snippet, "arxiv"))
    return items


def _search_pubmed(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    search_url = base + "esearch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "term": query, "retmode": "json", "retmax": min(max_results, 5)}
    )
    ids = requests.get(search_url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout).json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summary_url = base + "esummary.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    data = requests.get(summary_url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout).json().get("result", {})
    items: list[SearchResult] = []
    for pmid in ids:
        rec = data.get(pmid) or {}
        title = rec.get("title") or "PubMed article"
        journal = rec.get("fulljournalname") or rec.get("source") or ""
        pubdate = rec.get("pubdate") or ""
        snippet = ", ".join(filter(None, [pubdate, journal]))
        items.append(SearchResult(title, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", snippet, "pubmed"))
    return items


def _search_wikidata(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": query, "language": "en", "format": "json", "limit": min(max_results, 5)}
    )
    data = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout).json()
    items = []
    for item in data.get("search", []):
        qid = item.get("id")
        label = item.get("label") or qid or "Wikidata entity"
        if not qid:
            continue
        snippet = item.get("description") or ""
        items.append(SearchResult(label, f"https://www.wikidata.org/wiki/{qid}", snippet, "wikidata"))
    return items


def _search_github_repositories(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 5)}
    )
    data = requests.get(url, headers={"User-Agent": USER_AGENTS[0]}, timeout=timeout).json()
    items = []
    for repo in data.get("items", []):
        full_name = repo.get("full_name") or "GitHub repository"
        html_url = repo.get("html_url")
        if not html_url:
            continue
        stars = repo.get("stargazers_count", 0)
        language = repo.get("language") or ""
        description = repo.get("description") or ""
        snippet = f"{stars} stars"
        if language:
            snippet += f", {language}"
        if description:
            snippet += f" — {description[:220]}"
        items.append(SearchResult(full_name, html_url, snippet, "github"))
    return items


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
    use_camoufox: bool = True,
    services: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    profile = infer_subject_profile(query, services)
    if services is None:
        search_results = search_web(query, max_results=max_results, timeout=timeout)
    else:
        search_results = search_web(query, max_results=max_results, timeout=timeout, services=services)
    fetched: list[FetchResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(search_results)))) as pool:
        fut_map = {
            pool.submit(fetch_url, r.url, timeout=timeout, max_chars=max_chars, use_jina=True, use_camoufox=use_camoufox): r
            for r in search_results
        }
        for fut in concurrent.futures.as_completed(fut_map):
            try:
                fetched.append(fut.result())
            except Exception as exc:
                sr = fut_map[fut]
                fetched.append(FetchResult(url=sr.url, title=sr.title, warnings=[f"fetch_failed:{exc}"]))
    fetched.sort(key=lambda r: r.quality_score(), reverse=True)
    usable = [r for r in fetched if r.ok and r.quality_score() >= 1.0]
    warnings = []
    status = "ok"
    if not search_results:
        status = "degraded"
        warnings.append("no_search_results")
    elif not usable:
        status = "degraded"
        warnings.append("no_usable_sources")
    return {
        "query": query,
        "generated_at": email.utils.formatdate(usegmt=True),
        "status": status,
        "subject_profile": profile.to_dict(),
        "warnings": warnings,
        "search_results": [r.to_dict() for r in search_results],
        "sources": [r.to_dict(max_chars=max_chars) for r in usable],
        "rejected_sources": [r.to_dict(max_chars=1000) for r in fetched if r not in usable],
        "answer_pack": _answer_pack(query, usable),
    }


def _answer_pack(query: str, sources: Iterable[FetchResult]) -> dict[str, Any]:
    q_terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9]{3,}", query)}
    bullets = []
    for src in sources:
        if not src.ok or not src.text or _looks_blocked("\n".join([src.title, src.text]), src.status_code):
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
    return "\n".join(parts).strip() + "\n"
