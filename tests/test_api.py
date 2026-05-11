from __future__ import annotations

from agentweb.api import AgentWebAPI
from agentweb import core


def test_api_health_reports_versions_and_schema(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")

    response = api.handle("GET", "/v1/health", {})

    assert response["status_code"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["api_version"] == "v1"
    assert response["body"]["schema_version"] >= 1


def test_api_services_endpoint_returns_registered_services(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")

    response = api.handle("GET", "/v1/services", {})

    assert response["status_code"] == 200
    assert {item["name"] for item in response["body"]["services"]} >= {"duckduckgo", "pubmed", "arxiv"}


def test_api_search_validates_request_body(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")

    response = api.handle("POST", "/v1/search", {"max_results": 3})

    assert response["status_code"] == 400
    assert "query" in response["body"]["error"]


def test_api_search_wraps_core_search(monkeypatch, tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")
    monkeypatch.setattr(
        core,
        "search_web",
        lambda query, max_results=8, timeout=20, services=None: [core.SearchResult("Ada", "https://example.com/ada", "bio", "test")],
    )

    response = api.handle("POST", "/v1/search", {"query": "Ada", "max_results": 1, "services": ["wikipedia"]})

    assert response["status_code"] == 200
    assert response["body"]["results"] == [{"title": "Ada", "url": "https://example.com/ada", "snippet": "bio", "source": "test"}]


def test_api_unknown_endpoint_is_human_readable(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")

    response = api.handle("DELETE", "/v1/nope", {})

    assert response["status_code"] == 404
    assert response["body"]["error"] == "Unknown endpoint: DELETE /v1/nope"
