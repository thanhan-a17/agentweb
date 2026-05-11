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
