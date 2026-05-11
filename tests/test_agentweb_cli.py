from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentweb.cli import main
from agentweb.core import fetch_url, research
from agentweb import core


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/next":
            body = """
            <html><head><title>Shell</title></head><body>
            <div id="__next"></div>
            <script>self.__next_f.push([1,"This is a long rendered server payload about AgentWeb extracting useful hidden pricing and product details from Next.js applications."])</script>
            </body></html>
            """
        else:
            body = """
            <html><head><title>AgentWeb Test Page</title>
            <meta name="description" content="A clean test page for agents"></head>
            <body><nav>menu</nav><h1>AgentWeb Test Page</h1>
            <p>AgentWeb fetches clean evidence for AI agents from messy web pages.</p>
            <a href="/next">Next payload</a></body></html>
            """
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def server_url():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def test_fetch_url_extracts_title_text_links():
    httpd, base = server_url()
    try:
        result = fetch_url(base, use_jina=False)
        assert result.ok
        assert result.title == "AgentWeb Test Page"
        assert "clean evidence" in result.text
        assert result.links[0]["url"] == base + "/next"
    finally:
        httpd.shutdown()


def test_fetch_url_extracts_nextjs_payload():
    httpd, base = server_url()
    try:
        result = fetch_url(base + "/next", use_jina=False)
        assert result.ok
        assert "nextjs_rsc_payload" in result.tactics
        assert "hidden pricing" in result.text
    finally:
        httpd.shutdown()


def test_cli_fetch_json(capsys):
    httpd, base = server_url()
    try:
        code = main(["fetch", base, "--no-jina", "--format", "json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["title"] == "AgentWeb Test Page"
    finally:
        httpd.shutdown()


def test_duckduckgo_search_skips_ad_redirects(monkeypatch):
    ad = "https://duckduckgo.com/y.js?ad_domain=amazon.com&ad_provider=bingv7aa"
    organic = "https://example.com/hermes"
    raw = f'''
    <div class="result results_links">
      <a class="result__a" href="{ad}">Save on hermes agent - Amazon.com Official Site</a>
      <a class="result__snippet">Sponsored result</a>
    </div></div>
    <div class="result results_links">
      <a class="result__a" href="/l/?uddg={organic}">Hermes Agent real result</a>
      <a class="result__snippet">Organic result</a>
    </div></div>
    '''

    class Resp:
        text = raw

    monkeypatch.setattr(core.requests, "get", lambda *args, **kwargs: Resp())
    results = core._search_duckduckgo_html("hermes agent", max_results=5, timeout=5)
    assert [r.url for r in results] == [organic]


def test_research_pack_uses_search_results(monkeypatch):
    httpd, base = server_url()
    try:
        from agentweb import core

        monkeypatch.setattr(
            core,
            "search_web",
            lambda query, max_results=6, timeout=20: [core.SearchResult("Local", base, "", "test")],
        )
        pack = research("AgentWeb evidence", max_results=1, timeout=5)
        assert pack["sources"][0]["ok"] is True
        assert pack["answer_pack"]["evidence"]
    finally:
        httpd.shutdown()


def test_blocker_pages_are_not_ok_or_evidence():
    result = core.FetchResult(
        url="https://stackoverflow.com/questions/123",
        final_url="https://stackoverflow.com/questions/123",
        ok=True,
        status_code=403,
        title="Just a moment...",
        text="Just a moment... Enable JavaScript and cookies to continue. Cloudflare Ray ID.",
    )
    core._classify_fetch_result(result)
    assert result.ok is False
    assert "blocker_or_login_wall" in result.warnings
    assert core._answer_pack("playwright target closed", [result])["evidence"] == []


def test_research_marks_empty_search_as_degraded(monkeypatch):
    monkeypatch.setattr(core, "search_web", lambda query, max_results=6, timeout=20: [])
    pack = research("rare topic with no results", max_results=3, timeout=5)
    assert pack["status"] == "degraded"
    assert pack["warnings"] == ["no_search_results"]
    assert pack["answer_pack"]["evidence"] == []


def test_cli_research_empty_search_returns_degraded_success(monkeypatch, capsys):
    monkeypatch.setattr(core, "search_web", lambda query, max_results=6, timeout=20: [])
    code = main(["research", "rare topic", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["status"] == "degraded"


def test_search_web_uses_broad_providers_beyond_hackernews(monkeypatch):
    def ddg(query, max_results, timeout):
        return []

    def wikipedia(query, max_results, timeout):
        return [core.SearchResult("Ada Lovelace", "https://en.wikipedia.org/wiki/Ada_Lovelace", "math history", "wikipedia")]

    monkeypatch.setattr(core, "_search_duckduckgo_html", ddg)
    monkeypatch.setattr(core, "_search_hn_algolia", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_wikipedia", wikipedia)
    monkeypatch.setattr(core, "_search_openalex", lambda *args, **kwargs: [])
    results = core.search_web("Ada Lovelace biography", max_results=5, timeout=5)
    assert results[0].source == "wikipedia"


def test_fetch_extracts_json_ld_structured_data():
    raw = '''
    <html><head><title>Surface title</title>
    <script type="application/ld+json">{
      "@type": "Article",
      "headline": "Structured Research Article",
      "datePublished": "2026-01-02",
      "author": {"name": "Ada Writer"},
      "description": "Deep structured evidence from JSON-LD."
    }</script></head><body><p>Short body.</p></body></html>
    '''
    data = core._extract_structured_data(raw)
    assert data[0]["headline"] == "Structured Research Article"
    text = core._structured_data_text(data)
    assert "Structured Research Article" in text
    assert "Ada Writer" in text


def test_camoufox_fallback_is_used_for_blocked_pages(monkeypatch):
    class Resp:
        status_code = 403
        url = "https://example.com/protected"
        headers = {"content-type": "text/html"}
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        text = "<html><title>Just a moment...</title><body>Just a moment...</body></html>"
        content = b"x"

    class Session:
        headers = {}
        cookies = {}
        def get(self, *args, **kwargs):
            return Resp()

    monkeypatch.setattr(core, "_session", lambda **kwargs: Session())
    monkeypatch.setattr(core, "_fetch_jina", lambda *args, **kwargs: None)
    monkeypatch.setattr(core, "_fetch_with_camoufox", lambda url, timeout=30: "Protected article content with real evidence after browser rendering.")
    result = fetch_url("https://example.com/protected", use_jina=True, use_camoufox=True)
    assert result.ok is True
    assert result.source == "camoufox_browser"
    assert "Protected article content" in result.text


def test_jina_fallback_does_not_launder_blocked_pages(monkeypatch):
    class Resp:
        status_code = 403
        url = "https://example.com/protected"
        headers = {"content-type": "text/html"}
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        text = "<html><title>Access denied</title><body>Enable JavaScript and cookies to continue.</body></html>"
        content = b"x"

    class Session:
        headers = {}
        cookies = {}
        def get(self, *args, **kwargs):
            return Resp()

    monkeypatch.setattr(core, "_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        core,
        "_fetch_jina",
        lambda *args, **kwargs: core.FetchResult(
            url="https://example.com/protected",
            final_url="https://example.com/protected",
            ok=True,
            status_code=200,
            source="jina_reader",
            title="Please wait for verification",
            text="Please wait for verification. Sign in to view more content. " * 80,
            tactics=["jina_reader"],
        ),
    )
    result = fetch_url("https://example.com/protected", use_jina=True, use_camoufox=False)
    assert result.ok is False
    assert result.source != "jina_reader"
    assert "blocker_or_login_wall" in result.warnings


def test_blocked_login_wall_quality_score_cannot_pass_source_gate():
    result = core.FetchResult(
        url="https://example.com/login-wall",
        final_url="https://example.com/login-wall",
        ok=True,
        status_code=200,
        source="direct_http",
        title="Sign in to view more content",
        text="Sign in to view more content. " * 1000,
    )
    assert result.quality_score() < 1.0


def test_duckduckgo_anomaly_page_returns_no_results(monkeypatch):
    class Resp:
        status_code = 200
        text = '<html><script src="/anomaly.js"></script><form id="challenge-form">verify</form></html>'

    monkeypatch.setattr(core.requests, "get", lambda *args, **kwargs: Resp())
    assert core._search_duckduckgo_html("agentweb", max_results=5, timeout=5) == []


def test_subject_profile_routes_academic_and_medical_queries():
    academic = core.infer_subject_profile("arxiv paper about sparse autoencoders")
    assert "arxiv" in academic.services
    assert "crossref" in academic.services
    assert "scholarly" in academic.subjects

    medical = core.infer_subject_profile("clinical trial medicine therapy")
    assert "pubmed" in medical.services
    assert "medicine" in medical.subjects


def test_search_can_be_restricted_to_explicit_services(monkeypatch):
    calls = []

    def wiki(query, max_results, timeout):
        calls.append("wikipedia")
        return [core.SearchResult("Ada", "https://en.wikipedia.org/wiki/Ada", "", "wikipedia")]

    def ddg(query, max_results, timeout):
        calls.append("duckduckgo")
        return [core.SearchResult("Ada", "https://example.com/ada", "", "duckduckgo")]

    monkeypatch.setattr(core, "_search_wikipedia", wiki)
    monkeypatch.setattr(core, "_search_duckduckgo_html", ddg)
    results = core.search_web("Ada", max_results=5, timeout=5, services=["wikipedia"])
    assert [r.source for r in results] == ["wikipedia"]
    assert calls == ["wikipedia"]


def test_balance_search_results_preserves_provider_diversity():
    results = [
        core.SearchResult("A1", "https://a/1", source="alpha"),
        core.SearchResult("A2", "https://a/2", source="alpha"),
        core.SearchResult("B1", "https://b/1", source="beta"),
    ]
    balanced = core._balance_search_results(results, max_results=3)
    assert [r.source for r in balanced] == ["alpha", "beta", "alpha"]


def test_cli_services_lists_registry(capsys):
    code = main(["services", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {item["name"] for item in data["services"]} >= {"duckduckgo", "wikipedia", "openalex", "pubmed", "github"}


def test_duckduckgo_lite_fallback_parses_results(monkeypatch):
    html = '''
    <html><body>
      <a rel="nofollow" class='result-link' href="https://example.com/nvidia-earnings">NVIDIA earnings release</a>
      <td class='result-snippet'>Data Center revenue increased in the latest quarterly earnings.</td>
      <a rel="nofollow" class='result-link' href="https://example.com/second">Second result</a>
      <td class='result-snippet'>Another useful snippet.</td>
    </body></html>
    '''

    class Resp:
        status_code = 200
        text = html

    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if "html" in url:
            class Blocked:
                status_code = 202
                text = '<html><script src="/anomaly.js"></script></html>'
            return Blocked()
        return Resp()

    monkeypatch.setattr(core.requests, "get", fake_get)
    results = core._search_duckduckgo_html("NVIDIA latest quarterly earnings", max_results=5, timeout=5)
    assert [r.url for r in results] == ["https://example.com/nvidia-earnings", "https://example.com/second"]
    assert results[0].snippet == "Data Center revenue increased in the latest quarterly earnings."


def test_search_web_falls_back_and_filters_irrelevant_vertical_results(monkeypatch):
    monkeypatch.setattr(core, "_search_duckduckgo_html", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_wikipedia", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_wikidata", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_openalex", lambda *args, **kwargs: [
        core.SearchResult("Crisis in Context: The End of the Late Bronze Age", "https://example.com/bronze", "Late Bronze Age collapse Eastern Mediterranean", "openalex")
    ])
    monkeypatch.setattr(core, "_search_crossref", lambda *args, **kwargs: [
        core.SearchResult("Taxation: Key Tables from OECD", "https://example.com/tax", "tax revenue", "crossref")
    ])
    monkeypatch.setattr(core, "_search_arxiv", lambda *args, **kwargs: [
        core.SearchResult("Garbage Collection Makes Rust Easier to Use", "https://example.com/rust", "Bronze garbage collector", "arxiv")
    ])
    monkeypatch.setattr(core, "_search_pubmed", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_github_repositories", lambda *args, **kwargs: [])
    monkeypatch.setattr(core, "_search_hn_algolia", lambda *args, **kwargs: [])

    results = core.search_web("causes of the Bronze Age collapse evidence", max_results=5, timeout=5)
    assert [r.url for r in results] == ["https://example.com/bronze"]


def test_subject_profile_routes_troubleshooting_to_software_services():
    profile = core.infer_subject_profile("Next.js hydration mismatch localStorage useEffect fix")
    assert "github" in profile.services
    assert "hackernews" in profile.services


def test_official_docs_with_report_a_bug_are_not_blocked():
    text = "What’s New In Python 3.13\nReport a bug\nFree-threaded CPython and an experimental JIT compiler."
    result = core.FetchResult(
        url="https://docs.python.org/3/whatsnew/3.13.html",
        final_url="https://docs.python.org/3/whatsnew/3.13.html",
        ok=True,
        status_code=200,
        title="What’s New In Python 3.13",
        text=text,
    )
    core._classify_fetch_result(result)
    assert result.ok is True
    assert "blocker_or_login_wall" not in result.warnings


def test_duckduckgo_html_captures_snippet_outside_title_div(monkeypatch):
    raw = '''
    <div class="result results_links">
      <div><div><a class="result__a" href="https://example.com/next">Next.js hydration fix</a></div></div>
      <a class="result__snippet" href="https://example.com/next">Use useEffect for browser-only localStorage state.</a>
    </div>
    <div class="result results_links">
      <div><div><a class="result__a" href="https://example.com/ramen">Tokyo Station ramen guide</a></div></div>
      <a class="result__snippet" href="https://example.com/ramen">Best ramen shops in Tokyo Station.</a>
    </div>
    '''

    class Resp:
        status_code = 200
        text = raw

    monkeypatch.setattr(core.requests, "get", lambda *args, **kwargs: Resp())
    results = core._search_duckduckgo_html("Next.js hydration fix", max_results=5, timeout=5)
    assert results[0].snippet == "Use useEffect for browser-only localStorage state."


def test_stackoverflow_search_provider_returns_questions(monkeypatch):
    class Resp:
        def json(self):
            return {"items": [{
                "title": "React custom localstorage hook hydration error in NextJS",
                "link": "https://stackoverflow.com/questions/73944543/react-custom-localstorage-hook-hydration-error-in-nextjs",
                "score": 12,
                "answer_count": 2,
                "tags": ["reactjs", "next.js", "local-storage"],
            }]}

    monkeypatch.setattr(core.requests, "get", lambda *args, **kwargs: Resp())
    results = core._search_stackoverflow("Next.js hydration mismatch localStorage useEffect fix", max_results=5, timeout=5)
    assert results[0].source == "stackoverflow"
    assert "hydration error" in results[0].title
    assert "2 answers" in results[0].snippet


def test_research_uses_search_snippets_when_fetches_are_blocked(monkeypatch):
    monkeypatch.setattr(
        core,
        "search_web",
        lambda query, max_results=6, timeout=20: [
            core.SearchResult(
                "React custom localstorage hook hydration error in NextJS",
                "https://stackoverflow.com/questions/73944543/react-custom-localstorage-hook-hydration-error-in-nextjs",
                "Use useEffect for browser-only localStorage state to avoid hydration mismatch.",
                "stackoverflow",
            )
        ],
    )
    monkeypatch.setattr(
        core,
        "fetch_url",
        lambda *args, **kwargs: core.FetchResult(
            url=args[0],
            final_url=args[0],
            ok=False,
            status_code=403,
            title="Just a moment...",
            text="Just a moment... Cloudflare",
            warnings=["blocker_or_login_wall"],
        ),
    )
    pack = research("Next.js hydration mismatch localStorage useEffect fix", max_results=1, timeout=5)
    assert pack["status"] == "ok"
    assert pack["sources"][0]["source"] == "search_snippet"
    assert pack["answer_pack"]["evidence"]


# ── Screenshot tests ──────────────────────────────────────────────

def test_take_screenshot_returns_path_on_success(monkeypatch, tmp_path):
    """_take_screenshot should return a file path when Playwright succeeds."""
    screenshot_path = str(tmp_path / "page.png")

    def mock_run(*args, **kwargs):
        Path(screenshot_path).write_bytes(b"fake_png_data")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core.subprocess, "run", mock_run)
    monkeypatch.setattr(core.shutil, "which", lambda x: "/usr/bin/python3")
    monkeypatch.setattr("tempfile.mkstemp", lambda suffix, prefix=None, dir=None: (0, screenshot_path))

    result = core._take_screenshot("https://example.com", timeout=10)
    assert result == screenshot_path
    assert Path(result).exists()


def test_take_screenshot_returns_empty_when_playwright_missing(monkeypatch):
    """_take_screenshot returns '' when Playwright not installed."""
    monkeypatch.setattr(core.shutil, "which", lambda x: None)
    result = core._take_screenshot("https://example.com")
    assert result == ""


def test_take_screenshot_returns_empty_on_failure(monkeypatch):
    """_take_screenshot returns '' when Playwright subprocess fails."""
    monkeypatch.setattr(core.shutil, "which", lambda x: "/usr/bin/python3")

    def mock_run(*args, **kwargs):
        raise Exception("playwright not found")

    monkeypatch.setattr(core.subprocess, "run", mock_run)
    result = core._take_screenshot("https://example.com")
    assert result == ""


def test_fetch_result_includes_screenshot_path_in_dict():
    """FetchResult.to_dict() includes screenshot_path when set."""
    fr = core.FetchResult(
        url="https://example.com",
        ok=True,
        screenshot_path="/tmp/shot.png",
    )
    d = fr.to_dict()
    assert d["screenshot_path"] == "/tmp/shot.png"


def test_fetch_result_omits_screenshot_when_empty():
    """FetchResult.to_dict() omits screenshot_path when empty."""
    fr = core.FetchResult(url="https://example.com", ok=True)
    d = fr.to_dict()
    assert d["screenshot_path"] == ""


def test_fetch_url_takes_screenshot_when_requested(monkeypatch, tmp_path):
    """fetch_url with take_screenshot=True calls _take_screenshot."""
    shot_path = str(tmp_path / "shot.png")
    Path(shot_path).write_bytes(b"png")

    captured_url = []

    def fake_take_screenshot(url, timeout=15):
        captured_url.append(url)
        return shot_path

    monkeypatch.setattr(core, "_take_screenshot", fake_take_screenshot)

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        url = "https://example.com"
        text = "<html><head><title>Test</title></head><body><p>Hello</p></body></html>"
        headers = {"content-type": "text/html"}

    monkeypatch.setattr(core.requests.Session, "get", lambda *a, **kw: FakeResp())

    result = core.fetch_url("https://example.com", take_screenshot=True)
    assert captured_url == ["https://example.com"]
    assert result.screenshot_path == shot_path


# ── Deep crawl tests ───────────────────────────────────────────────

def test_crawl_bfs_stops_at_max_depth(monkeypatch, tmp_path):
    """crawl BFS respects --depth and stops at boundary."""
    import pathlib
    fetched_urls = []

    def fake_fetch(url, **kwargs):
        fetched_urls.append(url)
        depth = int(url.split("/page")[1]) if "/page" in url else 0
        links = []
        if depth < 3:
            links = [{"url": f"https://example.com/page{depth+1}", "text": f"Page {depth+1}"}]
        return core.FetchResult(
            url=url, final_url=url, ok=True, status_code=200,
            title=f"Page {url}", text=f"Content of {url}",
            links=links,
            tactics=["direct_http"],
            source="direct_http",
        )

    monkeypatch.setattr(core, "fetch_url", fake_fetch)

    result = core.crawl("https://example.com/page0", depth=2, max_pages=10, timeout=10)
    assert result["status"] == "ok"
    urls = [s["url"] for s in result["sources"]]
    # depth 0, depth 1, depth 2 = 3 unique pages
    assert len(urls) == 3
    assert "https://example.com/page0" in urls
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls
    assert "https://example.com/page3" not in urls  # depth limit


def test_crawl_stops_at_max_pages(monkeypatch):
    """crawl respects --max-pages even when more reachable."""
    fetched_urls = []

    def fake_fetch(url, **kwargs):
        fetched_urls.append(url)
        return core.FetchResult(
            url=url, final_url=url, ok=True, status_code=200,
            title=url, text=f"Content of {url}",
            links=[{"url": f"{url}/a", "text": "A"}, {"url": f"{url}/b", "text": "B"}],
            tactics=["direct_http"], source="direct_http",
        )

    monkeypatch.setattr(core, "fetch_url", fake_fetch)

    result = core.crawl("https://example.com", depth=5, max_pages=3, timeout=10)
    assert len(result["sources"]) == 3


def test_crawl_deduplicates_canonical_urls(monkeypatch):
    """crawl skips already-seen canonical URLs."""
    def fake_fetch(url, **kwargs):
        return core.FetchResult(
            url=url, final_url="https://example.com/canonical",  # all same canonical
            ok=True, status_code=200,
            title=url, text=f"Content of {url}",
            links=[{"url": "https://example.com/other", "text": "Other"}],
            tactics=["direct_http"], source="direct_http",
        )

    monkeypatch.setattr(core, "fetch_url", fake_fetch)
    result = core.crawl("https://example.com", depth=2, max_pages=10, timeout=10)
    assert len(result["sources"]) == 1  # deduped


def test_crawl_skips_blocked_pages(monkeypatch):
    """crawl skips blocked pages but continues crawling."""
    calls = 0

    def fake_fetch(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return core.FetchResult(
                url=url, final_url=url, ok=True, status_code=200,
                title="Root", text="Root content",
                links=[{"url": "https://example.com/blocked", "text": "Blocked"},
                       {"url": "https://example.com/ok", "text": "OK"}],
                tactics=["direct_http"], source="direct_http",
            )
        elif "/blocked" in url:
            return core.FetchResult(
                url=url, final_url=url, ok=False, status_code=403,
                title="Blocked", text="Just a moment...",
                warnings=["blocker_or_login_wall"],
            )
        else:
            return core.FetchResult(
                url=url, final_url=url, ok=True, status_code=200,
                title="OK", text="OK content",
                links=[],
                tactics=["direct_http"], source="direct_http",
            )

    monkeypatch.setattr(core, "fetch_url", fake_fetch)
    result = core.crawl("https://example.com", depth=1, max_pages=10, timeout=10)
    sources = result["sources"]
    urls = [s["url"] for s in sources]
    assert "https://example.com" in urls
    assert "https://example.com/ok" in urls
    assert "https://example.com/blocked" not in urls
