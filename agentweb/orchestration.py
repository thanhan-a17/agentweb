"""Planning, orchestration, collaboration, and conflict resolution for AgentWeb."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .mechanics import AgentDefinition, ToolRegistry, ValidationError
from .safety import classify_output_claims

StepKind = Literal["research", "analysis", "compose", "review", "action"]
MessageKind = Literal["delegate", "result", "critique", "aggregate", "escalate"]


@dataclass(frozen=True)
class TaskStep:
    id: str
    kind: StepKind
    instruction: str
    agent_name: str
    tool_name: str | None = None
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: list[TaskStep]
    revision: int = 1
    budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "revision": self.revision, "budget": dict(self.budget), "steps": [s.to_dict() for s in self.steps]}


@dataclass(frozen=True)
class CollaborationMessage:
    sender: str
    recipient: str
    kind: MessageKind
    task_id: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    final_output: dict[str, Any]
    step_outputs: list[dict[str, Any]]
    messages: list[CollaborationMessage]
    reflection: dict[str, Any]


class ConflictResolver:
    """Resolve competing agent outputs without pretending certainty."""

    contradiction_markers = (("allows", "forbids"), ("true", "false"), ("yes", "no"), ("safe", "unsafe"))

    def resolve(self, outputs: list[dict[str, Any]]) -> dict[str, Any]:
        citations: list[str] = []
        answers = [str(item.get("answer") or item.get("summary") or "") for item in outputs if item]
        for item in outputs:
            for citation in item.get("citations", []) or []:
                if citation not in citations:
                    citations.append(citation)
        conflict = self._has_conflict(answers)
        if not outputs:
            return {"answer": "No agent outputs were produced.", "claim_type": "uncertain", "conflict": False, "warnings": ["empty_outputs"], "citations": []}
        if conflict:
            return {
                "answer": "Agents produced competing conclusions; review the cited evidence before acting.",
                "claim_type": "uncertain",
                "conflict": True,
                "warnings": ["competing_conclusions"],
                "citations": citations,
                "alternatives": answers,
            }
        answer = answers[-1] if answers else ""
        return {"answer": answer, "claim_type": classify_output_claims(answer)["claim_type"], "conflict": False, "warnings": [], "citations": citations}

    def _has_conflict(self, answers: list[str]) -> bool:
        lowered = [a.lower() for a in answers]
        joined = "\n".join(lowered)
        for left, right in self.contradiction_markers:
            if left in joined and right in joined:
                return True
        return len(set(a.strip() for a in lowered if a.strip())) > 1 and any("forbid" in a or "allow" in a for a in lowered)


class Orchestrator:
    """Dependency-light orchestrator for deterministic local workflows.

    It decomposes goals into typed steps, assigns them to role-matched agents,
    invokes registered tools, records collaboration messages, and runs a final
    self-review pass. No LLM calls anywhere.
    """

    def __init__(self, *, agents: list[AgentDefinition], tools: ToolRegistry, resolver: ConflictResolver | None = None) -> None:
        self.agents = {agent.name: agent for agent in agents}
        self.tools = tools
        self.resolver = resolver or ConflictResolver()

    def plan(self, goal: str) -> Plan:
        goal = goal.strip()
        if not goal:
            raise ValidationError("goal: required")
        steps: list[TaskStep] = []
        if self._needs_research(goal):
            agent = self._agent_for("researcher")
            steps.append(TaskStep(id="step-1", kind="research", instruction=goal, agent_name=agent.name, tool_name=agent.tools[0] if agent.tools else None))
        if self._needs_composition(goal) or not steps:
            agent = self._agent_for("writer", fallback_role="analyst")
            steps.append(
                TaskStep(
                    id=f"step-{len(steps) + 1}",
                    kind="compose",
                    instruction=f"Compose result for: {goal}",
                    agent_name=agent.name,
                    tool_name=agent.tools[0] if agent.tools else None,
                    depends_on=[steps[-1].id] if steps else [],
                )
            )
        max_steps = sum(agent.execution_policy.max_steps for agent in self.agents.values())
        max_tool_calls = sum(agent.execution_policy.max_tool_calls for agent in self.agents.values())
        return Plan(goal=goal, steps=steps, budget={"max_steps": max_steps, "max_tool_calls": max_tool_calls})

    def revise_plan(self, plan: Plan, feedback: str) -> Plan:
        if not feedback.strip():
            return plan
        steps = list(plan.steps)
        agent = self._agent_for("critic", fallback_role="researcher")
        steps.append(TaskStep(id=f"step-{len(steps) + 1}", kind="review", instruction=feedback, agent_name=agent.name, tool_name=agent.tools[0] if agent.tools else None))
        return Plan(goal=plan.goal, steps=steps, revision=plan.revision + 1, budget=dict(plan.budget))

    def execute(self, plan: Plan) -> ExecutionResult:
        self._enforce_plan_budget(plan)
        outputs: list[dict[str, Any]] = []
        messages: list[CollaborationMessage] = []
        citations: list[str] = []
        for step in plan.steps:
            agent = self._agent(step.agent_name)
            messages.append(CollaborationMessage("orchestrator", agent.name, "delegate", step.id, {"instruction": step.instruction, "tool": step.tool_name}))
            output = self._run_step(step, agent, outputs)
            outputs.append(output)
            for citation in output.get("citations", []) or []:
                if citation not in citations:
                    citations.append(citation)
        resolved = self.resolver.resolve(outputs)
        resolved["citations"] = resolved.get("citations") or citations
        reflection = self.reflect(resolved, outputs)
        messages.append(CollaborationMessage("reviewer", "orchestrator", "critique", "reflection", reflection))
        messages.append(CollaborationMessage("orchestrator", "user", "aggregate", "final", resolved))
        status = "completed" if reflection["passed"] else "needs_review"
        return ExecutionResult(status=status, final_output=resolved, step_outputs=outputs, messages=messages, reflection=reflection)

    def reflect(self, final_output: dict[str, Any], step_outputs: list[dict[str, Any]]) -> dict[str, Any]:
        warnings = list(final_output.get("warnings", []))
        passed = bool(final_output.get("answer")) and not final_output.get("conflict")
        if final_output.get("claim_type") == "factual" and not final_output.get("citations"):
            warnings.append("factual_claim_without_citation")
            passed = False
        return {"passed": passed, "warnings": warnings, "checked_steps": len(step_outputs)}

    def _run_step(self, step: TaskStep, agent: AgentDefinition, previous_outputs: list[dict[str, Any]]) -> dict[str, Any]:
        if not step.tool_name:
            return {"answer": step.instruction, "citations": []}
        if step.kind == "compose":
            text = "\n".join(str(item.get("summary") or item.get("answer") or "") for item in previous_outputs) or step.instruction
            tool_output = self.tools.invoke(step.tool_name, {"text": text}, agent=agent)
            return {"answer": tool_output.get("summary", ""), "summary": tool_output.get("summary", ""), "citations": self._citations(previous_outputs)}
        tool_output = self.tools.invoke(step.tool_name, {"query": step.instruction}, agent=agent)
        return {"answer": tool_output.get("summary", ""), **tool_output}

    def _enforce_plan_budget(self, plan: Plan) -> None:
        counts: dict[str, int] = {}
        for step in plan.steps:
            counts[step.agent_name] = counts.get(step.agent_name, 0) + 1
        for agent_name, count in counts.items():
            agent = self._agent(agent_name)
            if count > agent.execution_policy.max_steps:
                raise ValidationError(f"plan exceeds max_steps for {agent_name}: {count} > {agent.execution_policy.max_steps}")

    def _agent(self, name: str) -> AgentDefinition:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise ValidationError(f"Unknown agent: {name}") from exc

    def _agent_for(self, role: str, fallback_role: str | None = None) -> AgentDefinition:
        for agent in self.agents.values():
            if agent.role == role:
                return agent
        if fallback_role:
            for agent in self.agents.values():
                if agent.role == fallback_role:
                    return agent
        if self.agents:
            return next(iter(self.agents.values()))
        raise ValidationError(f"No agent available for role: {role}")

    @staticmethod
    def _needs_research(goal: str) -> bool:
        text = goal.lower()
        return any(word in text for word in ("research", "find", "source", "compare", "analyze", "what", "why", "how"))

    @staticmethod
    def _needs_composition(goal: str) -> bool:
        text = goal.lower()
        return any(word in text for word in ("summarize", "write", "answer", "explain", "report", "brief"))

    @staticmethod
    def _citations(outputs: list[dict[str, Any]]) -> list[str]:
        citations: list[str] = []
        for output in outputs:
            for citation in output.get("citations", []) or []:
                if citation not in citations:
                    citations.append(citation)
        return citations
