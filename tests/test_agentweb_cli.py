from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentweb.cli import main
from agentweb.core import fetch_url, research
from agentweb import core


class TestDDGS:
    """Mock DDGS for testing _search_duckduckgo."""
    def text(self, query, max_results=10):
        return [
            {"title": "Hermes Agent - Nous Research", "href": "https://example.com/hermes", "body": "An AI agent framework"},
            {"title": "AgentWeb CLI", "href": "https://github.com/example/agentweb", "body": "Zero-API web access"},
        ]


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
            <p>AgentWeb fetches clean evidence for AI agents from messy web pages.
            It extracts titles, text, links, and metadata so that language models can
            reason over real web content without needing API keys or complex setup.
            The tool supports multiple fallback tactics including Jina Reader and
            browser snapshots for JavaScript-heavy sites.</p>
            <p>Additional paragraph with more content to ensure the quality score
            passes the threshold of three points. This provides enough text length
            for the scoring algorithm to consider the page useful and informative.</p>
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


def test_duckduckgo_search_returns_structured_results(monkeypatch):
    """Test _search_duckduckgo parses DDGS.text() output correctly."""
    monkeypatch.setattr(core, "DDGS", lambda: TestDDGS())
    results = core._search_duckduckgo("hermes agent", max_results=5, timeout=5)
    assert len(results) == 2
    assert results[0].title == "Hermes Agent - Nous Research"
    assert results[0].url == "https://example.com/hermes"
    assert results[0].snippet == "An AI agent framework"
    assert results[0].source == "duckduckgo"
    assert results[1].title == "AgentWeb CLI"


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


def test_fetch_wikipedia_article_extracts_content(monkeypatch):
    """Smoke test for Wikipedia article fetching via the REST API."""
    import json

    # Mock Wikipedia REST API response
    mock_response_text = json.dumps({
        "title": "Python (programming language)",
        "description": "General-purpose programming language",
        "extract": "Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability with the use of significant indentation.",
        "pageid": 23862,
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python_(programming_language)"}},
    })

    class MockResponse:
        status_code = 200
        text = mock_response_text

        def json(self):
            return json.loads(self.text)

    original_get = core.requests.Session.get

    def mock_get(self, url, **kwargs):
        if "wikipedia.org/api/rest_v1/page/summary/" in url:
            return MockResponse()
        return original_get(self, url, **kwargs)

    monkeypatch.setattr(core.requests.Session, "get", mock_get)

    result = core.fetch_url(
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        use_jina=False,
    )
    assert result.ok
    assert result.title == "Python (programming language)"
    assert "high-level" in result.text
    assert result.tactics[0] == "wikipedia_api"


def test_fetch_wikipedia_article_detects_wikipedia_url():
    """Test that Wikipedia URL detection works correctly."""
    assert core._is_wikipedia_url("https://en.wikipedia.org/wiki/Python_(programming_language)") == "Python (programming language)"
    assert core._is_wikipedia_url("https://en.wikipedia.org/wiki/Main_Page") == "Main Page"
    assert core._is_wikipedia_url("https://google.com") is None
    assert core._is_wikipedia_url("https://en.wikipedia.org/wiki/") is None
