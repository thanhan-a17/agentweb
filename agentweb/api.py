"""Executable SDK-style API facade for AgentWeb.

The facade returns HTTP-like envelopes so it can be wrapped by an actual HTTP
server later without changing core request/response semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__, core
from .mechanics import AgentDefinition, ExecutionPolicy, ValidationError, validate_schema
from .storage import AgentWebStore

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
        "use_camoufox": {"type": "boolean"},
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
        "use_camoufox": {"type": "boolean"},
        "services": {"type": "array", "items": {"type": "string"}},
    },
}

AGENT_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["name", "role", "goal"],
    "properties": {
        "name": {"type": "string"},
        "role": {"type": "string"},
        "goal": {"type": "string"},
        "tools": {"type": "array", "items": {"type": "string"}},
        "permissions": {"type": "array", "items": {"type": "string"}},
        "memory": {"type": "object"},
        "model": {"type": "object"},
        "execution_policy": {"type": "object"},
    },
}

TASK_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["task_id", "goal"],
    "properties": {"task_id": {"type": "string"}, "goal": {"type": "string"}},
}


class AgentWebAPI:
    """Small request dispatcher for documented AgentWeb operations."""

    def __init__(self, *, store_path: str | Path | None = None) -> None:
        self.store = AgentWebStore(store_path or ":memory:")
        if str(self.store.path) != ":memory:":
            self.store.initialize()

    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        method = method.upper()
        body = body or {}
        try:
            if method == "GET" and path == "/v1/health":
                return self._response(200, self.health())
            if method == "GET" and path == "/v1/services":
                return self._response(200, {"services": core.list_search_services()})
            if method == "GET" and path == "/v1/agents":
                return self._response(200, {"agents": self.store.list_agents()})
            if method == "POST" and path == "/v1/agents":
                validate_schema(AGENT_REQUEST_SCHEMA, body, schema_name="agent_request")
                agent = self._agent_from_body(body)
                self.store.save_agent(agent, actor="api", request_id=body.get("request_id", ""))
                data = agent.to_dict()
                data["status"] = "active"
                return self._response(201, {"agent": data})
            if path.startswith("/v1/agents/"):
                handled = self._handle_agent_operation(method, path, body)
                if handled is not None:
                    return handled
            if method == "POST" and path == "/v1/tasks":
                validate_schema(TASK_REQUEST_SCHEMA, body, schema_name="task_request")
                self.store.upsert_task(body["task_id"], status="queued", goal=body["goal"], actor="api", request_id=body.get("request_id", ""))
                return self._response(202, {"task": self.store.load_task(body["task_id"])})
            if path.startswith("/v1/tasks/"):
                handled = self._handle_task_operation(method, path, body)
                if handled is not None:
                    return handled
            if method == "POST" and path == "/v1/search":
                validate_schema(SEARCH_REQUEST_SCHEMA, body, schema_name="search_request")
                results = core.search_web(
                    body["query"],
                    max_results=body.get("max_results", 8),
                    timeout=body.get("timeout", 20),
                    services=body.get("services"),
                )
                return self._response(200, {"query": body["query"], "results": [r.to_dict() for r in results]})
            if method == "POST" and path == "/v1/fetch":
                validate_schema(FETCH_REQUEST_SCHEMA, body, schema_name="fetch_request")
                result = core.fetch_url(
                    body["url"],
                    timeout=body.get("timeout", 20),
                    max_chars=body.get("max_chars", 12000),
                    use_jina=body.get("use_jina", True),
                    use_browser=body.get("use_browser", False),
                    use_camoufox=body.get("use_camoufox", False),
                )
                return self._response(200 if result.ok else 502, result.to_dict(max_chars=body.get("max_chars", 12000)))
            if method == "POST" and path == "/v1/research":
                validate_schema(RESEARCH_REQUEST_SCHEMA, body, schema_name="research_request")
                pack = core.research(
                    body["query"],
                    max_results=body.get("max_results", 6),
                    timeout=body.get("timeout", 20),
                    max_chars=body.get("max_chars", 6000),
                    use_camoufox=body.get("use_camoufox", True),
                    services=body.get("services"),
                )
                return self._response(200 if pack.get("status") == "ok" else 207, pack)
            return self._response(404, {"error": f"Unknown endpoint: {method} {path}"})
        except ValidationError as exc:
            return self._response(400, {"error": str(exc)})
        except ValueError as exc:
            return self._response(400, {"error": str(exc)})

    def health(self) -> dict[str, Any]:
        if str(self.store.path) == ":memory:":
            schema_version = 0
        else:
            schema_version = self.store.schema_version()
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "app_version": __version__,
            "schema_version": schema_version,
        }

    def _response(self, status_code: int, body: dict[str, Any]) -> dict[str, Any]:
        return {"status_code": status_code, "body": body}

    def _agent_from_body(self, body: dict[str, Any]) -> AgentDefinition:
        policy_data = body.get("execution_policy", {})
        allowed = {"max_steps", "max_runtime_seconds", "max_tool_calls", "max_cost_usd", "require_review"}
        policy = ExecutionPolicy(**{key: value for key, value in policy_data.items() if key in allowed})
        return AgentDefinition(
            name=body["name"],
            role=body["role"],
            goal=body["goal"],
            tools=body.get("tools", []),
            permissions=body.get("permissions", []),
            memory=body.get("memory", {}),
            model=body.get("model", {}),
            execution_policy=policy,
        )

    def _handle_agent_operation(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["v1", "agents"]:
            return None
        name = parts[2]
        if method == "GET" and len(parts) == 3:
            agent = self.store.load_agent(name)
            if agent is None:
                return self._response(404, {"error": f"Unknown agent: {name}"})
            data = agent.to_dict()
            statuses = {item["name"]: item["status"] for item in self.store.list_agents()}
            data["status"] = statuses.get(name, "active")
            return self._response(200, {"agent": data})
        if method == "DELETE" and len(parts) == 3:
            deleted = self.store.delete_agent(name, actor="api", request_id=body.get("request_id", ""))
            return self._response(200 if deleted else 404, {"deleted": deleted})
        if method == "POST" and len(parts) == 4 and parts[3] in {"pause", "resume"}:
            status = "paused" if parts[3] == "pause" else "active"
            agent = self.store.set_agent_status(name, status, actor="api", request_id=body.get("request_id", ""))
            if agent is None:
                return self._response(404, {"error": f"Unknown agent: {name}"})
            return self._response(200, {"agent": agent})
        return None

    def _handle_task_operation(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["v1", "tasks"]:
            return None
        task_id = parts[2]
        if method == "GET" and len(parts) == 3:
            task = self.store.load_task(task_id)
            if task is None:
                return self._response(404, {"error": f"Unknown task: {task_id}"})
            return self._response(200, {"task": task, "tool_calls": self.store.tool_calls(task_id=task_id)})
        if method == "POST" and len(parts) == 4 and parts[3] == "cancel":
            if self.store.load_task(task_id) is None:
                return self._response(404, {"error": f"Unknown task: {task_id}"})
            self.store.upsert_task(task_id, status="cancelled", actor="api", request_id=body.get("request_id", ""))
            return self._response(200, {"task": self.store.load_task(task_id)})
        return None
