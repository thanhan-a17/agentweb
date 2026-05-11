from __future__ import annotations

import json
import threading
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


def test_cli_research_empty_search_returns_degraded_exit(monkeypatch, capsys):
    monkeypatch.setattr(core, "search_web", lambda query, max_results=6, timeout=20: [])
    code = main(["research", "rare topic", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 2
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
