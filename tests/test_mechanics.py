from __future__ import annotations

import pytest

from agentweb.mechanics import (
    AgentDefinition,
    ExecutionPolicy,
    PermissionDenied,
    ToolRegistry,
    ToolSpec,
    ValidationError,
)


def test_tool_registry_validates_input_output_and_records_permissions():
    registry = ToolRegistry()

    def add(payload):
        return {"sum": payload["a"] + payload["b"]}

    registry.register(
        ToolSpec(
            name="math.add",
            description="Add two integers.",
            input_schema={
                "type": "object",
                "required": ["a", "b"],
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            },
            output_schema={
                "type": "object",
                "required": ["sum"],
                "properties": {"sum": {"type": "integer"}},
            },
            permissions=["math"],
            timeout_seconds=3,
            failure_modes=["invalid_number"],
            usage_constraints=["deterministic"],
            handler=add,
        )
    )

    agent = AgentDefinition(
        name="calculator",
        role="worker",
        goal="Do safe arithmetic.",
        tools=["math.add"],
        permissions=["math"],
    )

    result = registry.invoke("math.add", {"a": 2, "b": 5}, agent=agent)

    assert result == {"sum": 7}
    listed = registry.list_tools()[0]
    assert listed["name"] == "math.add"
    assert listed["permissions"] == ["math"]
    assert listed["timeout_seconds"] == 3
    assert listed["failure_modes"] == ["invalid_number"]


def test_tool_registry_rejects_invalid_inputs_before_execution():
    registry = ToolRegistry()
    called = False

    def handler(payload):
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(
        ToolSpec(
            name="demo.strict",
            description="Strict object tool.",
            input_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
            permissions=[],
            timeout_seconds=1,
            failure_modes=[],
            usage_constraints=[],
            handler=handler,
        )
    )

    with pytest.raises(ValidationError) as exc:
        registry.invoke("demo.strict", {"name": 42})

    assert "name" in str(exc.value)
    assert called is False


def test_tool_registry_rejects_invalid_outputs_after_execution():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.bad_output",
            description="Bad output tool.",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
            permissions=[],
            timeout_seconds=1,
            failure_modes=["bad_output"],
            usage_constraints=[],
            handler=lambda payload: {"ok": "yes"},
        )
    )

    with pytest.raises(ValidationError) as exc:
        registry.invoke("demo.bad_output", {})

    assert "ok" in str(exc.value)


def test_agent_permissions_prevent_unauthorized_tool_invocation():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="web.fetch",
            description="Fetch web content.",
            input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
            output_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            permissions=["web"],
            timeout_seconds=5,
            failure_modes=["network_error"],
            usage_constraints=["public URLs only"],
            handler=lambda payload: {"text": "content"},
        )
    )
    agent = AgentDefinition(
        name="restricted",
        role="analyst",
        goal="Analyze local data only.",
        tools=[],
        permissions=[],
        execution_policy=ExecutionPolicy(max_steps=2, max_runtime_seconds=10, max_tool_calls=1),
    )

    with pytest.raises(PermissionDenied) as exc:
        registry.invoke("web.fetch", {"url": "https://example.com"}, agent=agent)

    assert "web.fetch" in str(exc.value)


def test_agent_definition_serializes_policy_model_memory_and_permissions():
    agent = AgentDefinition(
        name="medical_reviewer",
        role="critic",
        goal="Review health claims with citations.",
        tools=["pubmed.search"],
        permissions=["medical_sources"],
        memory={"short_term": True, "long_term": False, "scope": "task"},
        model={"provider": "local", "model": "test-model", "temperature": 0},
        execution_policy=ExecutionPolicy(max_steps=5, max_runtime_seconds=120, max_tool_calls=4, require_review=True),
    )

    data = agent.to_dict()

    assert data["name"] == "medical_reviewer"
    assert data["execution_policy"]["require_review"] is True
    assert data["memory"]["scope"] == "task"
    assert data["model"]["temperature"] == 0
