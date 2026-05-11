# AgentWeb deployment

AgentWeb is local-first and dependency-light. The default production-like deployment is a single container or VM process that imports the SDK facade and stores state in SQLite.

## Docker-style profile

A minimal runtime needs:

- Python 3.11+
- The `agentweb` package
- A writable SQLite path such as `/data/agentweb.sqlite`
- Environment variables for optional external services only

Example runtime command:

```bash
python -m pip install .
python - <<'PY'
from agentweb.api import AgentWebAPI
api = AgentWebAPI(store_path='/data/agentweb.sqlite')
print(api.handle('GET', '/v1/health', {}))
PY
```

## Configuration profiles

Recommended profiles:

- `development`: local SQLite, verbose logs, low budgets, mocked model/tool responses.
- `testing`: temporary SQLite, deterministic registered tools, no external network unless explicitly enabled.
- `production`: persistent SQLite volume, structured logs, strict input/upload limits, explicit service allowlist, secrets from environment variables.

## Persistence

Mount the SQLite database on durable storage. The schema is versioned by `schema_migrations`; migration instructions are in `docs/architecture.md`.

## Shutdown

Current runtime operations are synchronous and transactional. SQLite writes are committed inside context managers. Long-running task runners should cancel or mark queued/running tasks as `cancelled`/`interrupted` before process exit.

## Known deployment limits

- The repository currently ships an SDK/API facade, not a bundled HTTP server.
- Background execution primitives are represented in storage/API state, but a durable worker daemon is not bundled yet.
- Distributed tracing is represented through request/correlation IDs in API/storage boundaries, not an OpenTelemetry exporter.
