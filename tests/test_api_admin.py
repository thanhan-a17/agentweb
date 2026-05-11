from __future__ import annotations

from agentweb.api import AgentWebAPI


def test_api_can_create_inspect_pause_resume_and_delete_agents(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")
    body = {
        "name": "ops_agent",
        "role": "operations",
        "goal": "Run operational checklists.",
        "tools": ["web.search"],
        "permissions": ["web"],
        "memory": {"scope": "workspace"},
        "model": {"provider": "local", "model": "test", "temperature": 0},
        "execution_policy": {"max_steps": 4, "max_runtime_seconds": 30, "max_tool_calls": 2},
    }

    created = api.handle("POST", "/v1/agents", body)
    listed = api.handle("GET", "/v1/agents", {})
    paused = api.handle("POST", "/v1/agents/ops_agent/pause", {})
    resumed = api.handle("POST", "/v1/agents/ops_agent/resume", {})
    deleted = api.handle("DELETE", "/v1/agents/ops_agent", {})

    assert created["status_code"] == 201
    assert listed["body"]["agents"][0]["name"] == "ops_agent"
    assert paused["body"]["agent"]["status"] == "paused"
    assert resumed["body"]["agent"]["status"] == "active"
    assert deleted["status_code"] == 200
    assert api.handle("GET", "/v1/agents", {})["body"]["agents"] == []


def test_api_exposes_task_status_history_and_cancellation(tmp_path):
    api = AgentWebAPI(store_path=tmp_path / "agentweb.sqlite")

    created = api.handle("POST", "/v1/tasks", {"task_id": "task-1", "goal": "Long research"})
    status = api.handle("GET", "/v1/tasks/task-1", {})
    cancelled = api.handle("POST", "/v1/tasks/task-1/cancel", {})

    assert created["status_code"] == 202
    assert status["body"]["task"]["status"] == "queued"
    assert cancelled["body"]["task"]["status"] == "cancelled"
