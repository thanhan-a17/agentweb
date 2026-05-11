"""Core AgentWeb mechanics: agents, execution policy, and tool/service registry.

This module is deliberately dependency-light. It provides the generic extension
surface for domain tools without tying AgentWeb to one subject matter or one
orchestrator implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


class AgentWebError(Exception):
    """Base class for expected AgentWeb mechanics errors."""


class ValidationError(AgentWebError):
    """Raised when a tool input or output fails schema validation."""


class PermissionDenied(AgentWebError):
    """Raised when an agent is not allowed to invoke a tool."""


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ExecutionPolicy:
    """Boundaries that prevent runaway or unsafe agent execution."""

    max_steps: int = 8
    max_runtime_seconds: int = 300
    max_tool_calls: int = 16
    max_cost_usd: float | None = None
    require_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentDefinition:
    """Configurable agent role definition.

    The orchestrator can persist this object and enforce its tools, permissions,
    model, memory, and execution policy at runtime.
    """

    name: str
    role: str
    goal: str
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["execution_policy"] = self.execution_policy.to_dict()
        return data


@dataclass(frozen=True)
class ToolSpec:
    """A registered tool/service contract.

    Schemas intentionally use a tiny JSON-Schema subset for zero-dependency
    validation: object/string/integer/number/boolean/array, required, properties,
    items, enum, and additionalProperties=false.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[str]
    timeout_seconds: int
    failure_modes: list[str]
    usage_constraints: list[str]
    handler: ToolHandler | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "permissions": list(self.permissions),
            "timeout_seconds": self.timeout_seconds,
            "failure_modes": list(self.failure_modes),
            "usage_constraints": list(self.usage_constraints),
        }


class ToolRegistry:
    """Runtime registry for tools and service adapters."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not spec.description:
            raise ValidationError("Tool name and description are required")
        if spec.name in self._tools:
            raise ValidationError(f"Tool already registered: {spec.name}")
        if spec.handler is None:
            raise ValidationError(f"Tool has no executable handler: {spec.name}")
        validate_schema(spec.input_schema, {}, schema_name=f"{spec.name}.input_schema", validate_schema_shape=True)
        validate_schema(spec.output_schema, {}, schema_name=f"{spec.name}.output_schema", validate_schema_shape=True)
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValidationError(f"Unknown tool: {name}") from exc

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._tools[name].public_dict() for name in sorted(self._tools)]

    def invoke(self, name: str, payload: dict[str, Any], *, agent: AgentDefinition | None = None) -> dict[str, Any]:
        spec = self.get(name)
        self._authorize(spec, agent)
        validate_schema(spec.input_schema, payload, schema_name=f"{name}.input")
        assert spec.handler is not None  # register() enforces this; keeps type checkers happy.
        output = spec.handler(payload)
        validate_schema(spec.output_schema, output, schema_name=f"{name}.output")
        return output

    def _authorize(self, spec: ToolSpec, agent: AgentDefinition | None) -> None:
        if agent is None:
            return
        if spec.name not in agent.tools:
            raise PermissionDenied(f"Agent {agent.name!r} cannot invoke unauthorized tool {spec.name!r}")
        missing = sorted(set(spec.permissions) - set(agent.permissions))
        if missing:
            raise PermissionDenied(f"Agent {agent.name!r} lacks permissions for {spec.name!r}: {', '.join(missing)}")


def validate_schema(
    schema: dict[str, Any],
    value: Any,
    *,
    schema_name: str = "value",
    validate_schema_shape: bool = False,
) -> None:
    """Validate a value against AgentWeb's small JSON-Schema subset."""
    if not isinstance(schema, dict):
        raise ValidationError(f"{schema_name}: schema must be an object")
    if validate_schema_shape:
        _validate_schema_shape(schema, schema_name)
        return
    _validate_value(schema, value, schema_name)


def _validate_schema_shape(schema: dict[str, Any], path: str) -> None:
    schema_type = schema.get("type", "object")
    if schema_type not in {"object", "string", "integer", "number", "boolean", "array", "null"}:
        raise ValidationError(f"{path}: unsupported schema type {schema_type!r}")
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise ValidationError(f"{path}.properties must be an object")
        for key, subschema in schema["properties"].items():
            _validate_schema_shape(subschema, f"{path}.properties.{key}")
    if "items" in schema:
        _validate_schema_shape(schema["items"], f"{path}.items")
    if "required" in schema and not isinstance(schema["required"], list):
        raise ValidationError(f"{path}.required must be a list")


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> None:
    expected = schema.get("type", "object")
    if expected == "object":
        if not isinstance(value, dict):
            raise ValidationError(f"{path}: expected object")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValidationError(f"{path}.{key}: required field missing")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate_value(properties[key], item, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValidationError(f"{path}.{key}: unexpected field")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise ValidationError(f"{path}: expected array")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_value(item_schema, item, f"{path}[{index}]")
        return
    if expected == "string" and not isinstance(value, str):
        raise ValidationError(f"{path}: expected string")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValidationError(f"{path}: expected integer")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise ValidationError(f"{path}: expected number")
    if expected == "boolean" and not isinstance(value, bool):
        raise ValidationError(f"{path}: expected boolean")
    if expected == "null" and value is not None:
        raise ValidationError(f"{path}: expected null")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: expected one of {schema['enum']!r}")
