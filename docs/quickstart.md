# AgentWeb quickstart

## Prerequisites

- Python 3.11+
- No API keys required for the core local workflows.
- Optional: Camoufox/browser tooling if you want browser fallback for blocked pages.

## Install

```bash
python -m pip install -e '.[dev]'
agentweb --version
```

Expected output:

```text
AgentWeb 0.1.0
```

## Run the test suite

```bash
python -m pytest -q
python -m compileall agentweb
```

Expected output includes all tests passing and no compile errors.

## Basic commands

```bash
agentweb services --format markdown
agentweb search "clinical trial metformin aging" --service pubmed --service openalex
agentweb fetch https://example.com --format markdown
agentweb research "sparse autoencoders interpretability" --format json
```

## Local API facade

AgentWeb exposes an SDK-style API facade without requiring a web server:

```python
from agentweb.api import AgentWebAPI

api = AgentWebAPI(store_path="./agentweb.sqlite")
print(api.handle("GET", "/v1/health", {}))
```

## Environment variables

Core AgentWeb does not require credentials. If future service adapters need secrets, store them in environment variables or a deployment secret manager. Never commit keys. Use `[REDACTED]` in examples and logs.
