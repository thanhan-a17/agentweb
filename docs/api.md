# AgentWeb API Reference

AgentWeb exposes an executable SDK-style API facade in `agentweb.api.AgentWebAPI`. It returns HTTP-like envelopes:

```json
{"status_code": 200, "body": {}}
```

This is intentionally server-agnostic. A future ASGI/HTTP wrapper can map the same endpoint contracts to real HTTP without changing core behavior.

## Authentication

The local SDK facade does not implement network authentication. Production HTTP deployments must add authentication and authorization before exposing these endpoints across a network. Store secrets outside source code.

## Common status codes

| Code | Meaning |
|---:|---|
| 200 | Success |
| 201 | Created |
| 202 | Accepted/queued |
| 207 | Partial/degraded research result |
| 400 | Invalid request schema or configuration |
| 404 | Unknown endpoint, agent, or task |
| 502 | Fetch completed but no usable source was produced |

## `GET /v1/health`

Returns application/API/schema version information.

Response:

```json
{"status": "ok", "api_version": "v1", "app_version": "0.1.0", "schema_version": 2}
```

## `GET /v1/services`

Lists configured discovery services and subject coverage.

```json
{"services": [{"name": "pubmed", "subjects": ["medicine", "biology", "clinical"], "weight": 0.8}]}
```

## `GET /v1/agents`

Lists stored agent definitions plus runtime status.

## `POST /v1/agents`

Creates or replaces an agent definition.

Request schema:

```json
{
  "name": "string, required",
  "role": "string, required",
  "goal": "string, required",
  "tools": ["string"],
  "permissions": ["string"],
  "memory": {"scope": "workspace"},
  "model": {"provider": "local", "model": "test", "temperature": 0},
  "execution_policy": {"max_steps": 4, "max_runtime_seconds": 30, "max_tool_calls": 2}
}
```

## `GET /v1/agents/{name}`

Returns one agent definition.

## `POST /v1/agents/{name}/pause`

Marks an agent as paused without deleting its definition.

## `POST /v1/agents/{name}/resume`

Marks a paused agent as active.

## `DELETE /v1/agents/{name}`

Deletes an agent definition and associated runtime state.

## `POST /v1/tasks`

Creates a queued task record for background/asynchronous runners.

```json
{"task_id": "task-1", "goal": "Research a topic"}
```

## `GET /v1/tasks/{task_id}`

Returns task status, result/error state, timestamps, and recorded tool calls.

## `POST /v1/tasks/{task_id}/cancel`

Requests cancellation by marking the task as `cancelled`. A worker daemon should honor this before starting or between steps.

## `POST /v1/search`

Searches selected or inferred services.

Request schema:

```json
{
  "query": "string, required",
  "max_results": "integer, optional, default 8",
  "timeout": "integer, optional, default 20",
  "services": ["optional list of service names"]
}
```

Example:

```python
from agentweb.api import AgentWebAPI

api = AgentWebAPI(store_path="agentweb.sqlite")
response = api.handle("POST", "/v1/search", {
    "query": "clinical trial retinal disease",
    "services": ["pubmed", "openalex"],
    "max_results": 5
})
```

Response:

```json
{
  "query": "clinical trial retinal disease",
  "results": [
    {"title": "...", "url": "https://pubmed.ncbi.nlm.nih.gov/...", "snippet": "...", "source": "pubmed"}
  ]
}
```

## `POST /v1/fetch`

Fetches and extracts one URL.

Request schema:

```json
{
  "url": "string, required",
  "timeout": "integer, optional, default 20",
  "max_chars": "integer, optional, default 12000",
  "use_jina": "boolean, optional, default true",
  "use_browser": "boolean, optional, default false",
  "use_camoufox": "boolean, optional, default false"
}
```

Response body is `FetchResult.to_dict()` with URL, final URL, source, title, text, links, metadata, tactics, warnings, elapsed time, and quality score.

## `POST /v1/research`

Searches, fetches, scores, and returns an evidence pack.

Request schema:

```json
{
  "query": "string, required",
  "max_results": "integer, optional, default 6",
  "timeout": "integer, optional, default 20",
  "max_chars": "integer, optional, default 6000",
  "use_camoufox": "boolean, optional, default true",
  "services": ["optional list of service names"]
}
```

Response body includes `query`, `generated_at`, `status`, `subject_profile`, `warnings`, `search_results`, `sources`, `rejected_sources`, and `answer_pack.evidence`.

## Error shape

Expected user-facing failures return a body like:

```json
{"error": "search_request.query: required field missing"}
```

Production network wrappers should not expose stack traces, secrets, or internal-only debugging data in this error field.
