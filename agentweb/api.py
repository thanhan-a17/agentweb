"""Executable SDK-style API facade for AgentWeb.

The facade returns HTTP-like envelopes so it can be wrapped by an actual HTTP
server later without changing core request/response semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__, core
from .errors import AgentWebError

API_VERSION = "v1"

SEARCH_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer"},
        "timeout": {"type": "integer"},
        "services": {"type": "array", "items": {"type": "string"}},
    },
}

FETCH_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string"},
        "timeout": {"type": "integer"},
        "max_chars": {"type": "integer"},
        "use_jina": {"type": "boolean"},
        "use_browser": {"type": "boolean"},
    },
}

RESEARCH_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer"},
        "timeout": {"type": "integer"},
        "max_chars": {"type": "integer"},
        "services": {"type": "array", "items": {"type": "string"}},
    },
}


def _validate_schema(schema: dict[str, Any], value: Any, *, schema_name: str = "") -> None:
    """Minimal schema validation for request bodies."""
    if not isinstance(value, dict):
        raise AgentWebError(f"{schema_name}: expected object", code="validation_error")
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            raise AgentWebError(f"{schema_name}.{key}: required field missing", code="validation_error")
    properties = schema.get("properties", {})
    for key in value:
        if key in properties and key not in value:
            continue


class AgentWebAPI:
    """Small request dispatcher for documented AgentWeb operations."""

    def __init__(self, *, store_path: str | Path | None = None) -> None:
        from .storage import AgentWebStore

        self.store = AgentWebStore(store_path or ":memory:")
        if str(self.store.path) != ":memory:":
            self.store.initialize()

    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        method = method.upper()
        body = body or {}
        try:
            if method == "GET" and path == "/v1/health":
                return self._response(200, self.health())
            if method == "POST" and path == "/v1/search":
                _validate_schema(SEARCH_REQUEST_SCHEMA, body, schema_name="search_request")
                results = core.search_web(
                    body["query"],
                    max_results=body.get("max_results", 8),
                    timeout=body.get("timeout", 20),
                )
                return self._response(200, {"query": body["query"], "results": [r.to_dict() for r in results]})
            if method == "POST" and path == "/v1/fetch":
                _validate_schema(FETCH_REQUEST_SCHEMA, body, schema_name="fetch_request")
                result = core.fetch_url(
                    body["url"],
                    timeout=body.get("timeout", 20),
                    max_chars=body.get("max_chars", 12000),
                    use_jina=body.get("use_jina", True),
                    use_browser=body.get("use_browser", False),
                )
                return self._response(200 if result.ok else 502, result.to_dict(max_chars=body.get("max_chars", 12000)))
            if method == "POST" and path == "/v1/research":
                _validate_schema(RESEARCH_REQUEST_SCHEMA, body, schema_name="research_request")
                pack = core.research(
                    body["query"],
                    max_results=body.get("max_results", 6),
                    timeout=body.get("timeout", 20),
                    max_chars=body.get("max_chars", 6000),
                )
                return self._response(200 if pack.get("status") == "ok" else 207, pack)
            return self._response(404, {"error": f"Unknown endpoint: {method} {path}"})
        except AgentWebError as exc:
            return self._response(400, {"error": str(exc)})
        except ValueError as exc:
            return self._response(400, {"error": str(exc)})

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "app_version": __version__,
        }

    def _response(self, status_code: int, body: dict[str, Any]) -> dict[str, Any]:
        return {"status_code": status_code, "body": body}
