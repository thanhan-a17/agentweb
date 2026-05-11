from __future__ import annotations

import sqlite3

from agentweb.mechanics import AgentDefinition, ExecutionPolicy
from agentweb.storage import AgentWebStore, SCHEMA_VERSION


def test_store_initializes_versioned_schema(tmp_path):
    db = tmp_path / "agentweb.sqlite"
    store = AgentWebStore(db)
    store.initialize()

    assert store.schema_version() == SCHEMA_VERSION
    tables = store.table_names()
    assert {"agent_definitions", "tasks", "tool_call_records", "audit_logs", "schema_migrations"} <= tables


def test_store_saves_and_loads_agent_definition(tmp_path):
    store = AgentWebStore(tmp_path / "agentweb.sqlite")
    store.initialize()
    agent = AgentDefinition(
        name="science_reviewer",
        role="critic",
        goal="Review scientific claims.",
        tools=["arxiv.search"],
        permissions=["science_sources"],
        memory={"scope": "workspace", "short_term": True},
        model={"provider": "local", "model": "small"},
        execution_policy=ExecutionPolicy(max_steps=4, max_runtime_seconds=60, max_tool_calls=3),
    )

    store.save_agent(agent, actor="tester", request_id="req-1")
    loaded = store.load_agent("science_reviewer")

    assert loaded is not None
    assert loaded.name == "science_reviewer"
    assert loaded.execution_policy.max_tool_calls == 3
    assert loaded.memory["scope"] == "workspace"
    audit = store.audit_events(limit=5)
    assert audit[0]["actor"] == "tester"
    assert audit[0]["action"] == "agent.save"
    assert audit[0]["target"] == "science_reviewer"
    assert audit[0]["request_id"] == "req-1"


def test_store_records_task_state_and_tool_calls(tmp_path):
    store = AgentWebStore(tmp_path / "agentweb.sqlite")
    store.initialize()

    store.upsert_task("task-1", status="running", goal="Research a topic", actor="tester", request_id="req-2")
    store.record_tool_call(
        task_id="task-1",
        tool_name="web.search",
        input_payload={"query": "AgentWeb"},
        output_payload={"results": []},
        status="ok",
        elapsed_ms=12,
        actor="tester",
        request_id="req-2",
    )
    store.upsert_task("task-1", status="completed", result={"answer": "done"}, actor="tester", request_id="req-3")

    task = store.load_task("task-1")
    calls = store.tool_calls(task_id="task-1")

    assert task["status"] == "completed"
    assert task["result"] == {"answer": "done"}
    assert calls[0]["tool_name"] == "web.search"
    assert calls[0]["input_payload"] == {"query": "AgentWeb"}
    assert calls[0]["elapsed_ms"] == 12


def test_store_uses_foreign_keys_for_tool_calls(tmp_path):
    store = AgentWebStore(tmp_path / "agentweb.sqlite")
    store.initialize()

    try:
        store.record_tool_call(
            task_id="missing-task",
            tool_name="web.search",
            input_payload={},
            output_payload={},
            status="ok",
            elapsed_ms=1,
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("expected missing task foreign key to fail")
