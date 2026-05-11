from __future__ import annotations

import pytest

from agentweb.mechanics import AgentDefinition, ExecutionPolicy, ToolRegistry, ToolSpec, ValidationError
from agentweb.orchestration import (
    CollaborationMessage,
    ConflictResolver,
    Orchestrator,
    Plan,
    TaskStep,
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="research.search",
            description="Return source-backed research notes.",
            input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "required": ["summary", "citations"], "properties": {"summary": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}}},
            permissions=["research"],
            timeout_seconds=5,
            failure_modes=["service_unavailable"],
            usage_constraints=["cite sources"],
            handler=lambda payload: {"summary": f"researched {payload['query']}", "citations": ["source:local"]},
        )
    )
    registry.register(
        ToolSpec(
            name="writing.summarize",
            description="Summarize notes for a final answer.",
            input_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}},
            permissions=["write"],
            timeout_seconds=5,
            failure_modes=["bad_input"],
            usage_constraints=["no hidden chain of thought"],
            handler=lambda payload: {"summary": payload["text"][:80]},
        )
    )
    return registry


def _agents() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            name="researcher",
            role="researcher",
            goal="Find source-backed facts.",
            tools=["research.search"],
            permissions=["research"],
            execution_policy=ExecutionPolicy(max_steps=3, max_tool_calls=2),
        ),
        AgentDefinition(
            name="writer",
            role="writer",
            goal="Write concise final answers.",
            tools=["writing.summarize"],
            permissions=["write"],
            execution_policy=ExecutionPolicy(max_steps=3, max_tool_calls=2),
        ),
    ]


def test_orchestrator_decomposes_goal_and_assigns_steps_to_matching_agents():
    orchestrator = Orchestrator(agents=_agents(), tools=_registry())

    plan = orchestrator.plan("Research SQLite and summarize the answer")

    assert isinstance(plan, Plan)
    assert [step.kind for step in plan.steps] == ["research", "synthesis"]
    assert plan.steps[0].agent_name == "researcher"
    assert plan.steps[1].agent_name == "writer"
    assert plan.budget["max_steps"] == 6


def test_orchestrator_executes_plan_with_reflection_and_citations():
    orchestrator = Orchestrator(agents=_agents(), tools=_registry())
    plan = orchestrator.plan("Research AgentWeb and summarize")

    result = orchestrator.execute(plan)

    assert result.status == "completed"
    assert result.final_output["claim_type"] == "factual"
    assert result.final_output["citations"] == ["source:local"]
    assert result.reflection["passed"] is True
    assert [message.kind for message in result.messages] == ["delegate", "delegate", "critique", "aggregate"]


def test_orchestrator_enforces_step_budget_to_prevent_runaway_loops():
    tiny = AgentDefinition(
        name="tiny",
        role="researcher",
        goal="Do one thing only.",
        tools=["research.search"],
        permissions=["research"],
        execution_policy=ExecutionPolicy(max_steps=1, max_tool_calls=1),
    )
    orchestrator = Orchestrator(agents=[tiny], tools=_registry())
    plan = Plan(goal="oversized", steps=[TaskStep(id="s1", kind="research", instruction="one", agent_name="tiny"), TaskStep(id="s2", kind="research", instruction="two", agent_name="tiny")])

    with pytest.raises(ValidationError) as exc:
        orchestrator.execute(plan)

    assert "max_steps" in str(exc.value)


def test_collaboration_messages_define_delegation_critique_and_aggregation_protocol():
    message = CollaborationMessage(
        sender="orchestrator",
        recipient="researcher",
        kind="delegate",
        task_id="task-1",
        payload={"instruction": "Find sources"},
    )

    assert message.to_dict()["kind"] == "delegate"
    assert message.to_dict()["payload"]["instruction"] == "Find sources"


def test_conflict_resolver_marks_contradictory_outputs_as_uncertain():
    resolver = ConflictResolver()

    resolved = resolver.resolve([
        {"answer": "The policy allows exports", "confidence": 0.9, "citations": ["a"]},
        {"answer": "The policy forbids exports", "confidence": 0.8, "citations": ["b"]},
    ])

    assert resolved["claim_type"] == "uncertain"
    assert resolved["conflict"] is True
    assert "competing_conclusions" in resolved["warnings"]
    assert resolved["citations"] == ["a", "b"]
