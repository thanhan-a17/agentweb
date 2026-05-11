# AgentWeb Extension Examples

## Add a new subject domain

A domain is routing configuration plus one or more services. Keep the routing generic and avoid making the CLI branch on domain-specific behavior.

Example: education domain

1. Add query terms to `_select_search_services()` in `agentweb/core.py`:

```python
(("lesson", "curriculum", "rubric", "learning objective", "pedagogy"), {"duckduckgo", "wikipedia"})
```

2. If the domain needs a dedicated source, implement an adapter that returns `list[SearchResult]`:

```python
def _search_eric(query: str, max_results: int, timeout: int) -> list[SearchResult]:
    ...
    return [SearchResult(title, url, snippet, "eric")]
```

3. Register it in `_search_service_registry()`:

```python
"eric": SearchService("eric", _search_eric, ("education", "research"), 0.8)
```

4. Add tests proving subject routing and result parsing.

## Add a new agent role

Agent roles are data, not subclasses.

```python
from agentweb.mechanics import AgentDefinition, ExecutionPolicy

agent = AgentDefinition(
    name="policy_reviewer",
    role="critic",
    goal="Review policy claims and flag uncertainty.",
    tools=["web.search", "law.fetch"],
    permissions=["public_web", "legal_sources"],
    memory={"short_term": True, "long_term": False, "scope": "task"},
    model={"provider": "local", "model": "review-model", "temperature": 0},
    execution_policy=ExecutionPolicy(max_steps=6, max_runtime_seconds=180, max_tool_calls=8, require_review=True),
)
```

The orchestrator should enforce `tools`, `permissions`, and `execution_policy` before executing work.

## Add a new tool/service

```python
from agentweb.mechanics import ToolRegistry, ToolSpec

registry = ToolRegistry()

registry.register(
    ToolSpec(
        name="finance.lookup_ticker",
        description="Look up public ticker metadata.",
        input_schema={
            "type": "object",
            "required": ["ticker"],
            "properties": {"ticker": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["ticker", "name"],
            "properties": {
                "ticker": {"type": "string"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        permissions=["finance_public_data"],
        timeout_seconds=5,
        failure_modes=["not_found", "rate_limited", "network_error"],
        usage_constraints=["public market data only", "not investment advice"],
        handler=lambda payload: {"ticker": payload["ticker"], "name": "Example Corp"},
    )
)
```

AgentWeb validates inputs before the handler runs and validates outputs before a caller can consume the result.
