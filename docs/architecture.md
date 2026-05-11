# AgentWeb Architecture

## Overview

AgentWeb is a Python package and CLI for agent-ready web access plus extensible agent mechanics. The core rule is separation: generic framework logic lives separately from domain-specific services and from user-facing CLI code.

## Major components

### CLI layer: `agentweb/cli.py`

Responsibilities:

- parse commands and options
- expose `search`, `fetch`, `research`, and `services`
- serialize JSON or Markdown responses
- return meaningful exit codes (`0` success, `2` degraded/failed fetch or research, `1` unexpected CLI error)

### Retrieval and evidence layer: `agentweb/core.py`

Responsibilities:

- normalize URLs
- fetch web pages with realistic headers
- extract text, metadata, links, JSON-LD, and Next.js/RSC payloads
- call optional reader/browser fallbacks
- detect blocker/login/verification pages
- calculate source quality scores
- build research packs with usable and rejected sources

Primary data objects:

- `FetchResult`
- `SearchResult`
- `SearchService`
- `SubjectProfile`

### Mechanics layer: `agentweb/mechanics.py`

Responsibilities:

- define agent roles/configuration via `AgentDefinition`
- define runtime boundaries via `ExecutionPolicy`
- define tool/service contracts via `ToolSpec`
- register tools/services with `ToolRegistry`
- validate tool inputs and outputs against a JSON-Schema subset
- enforce agent tool allowlists and required permissions

Primary data objects:

- `AgentDefinition`
- `ExecutionPolicy`
- `ToolSpec`
- `ToolRegistry`

### Tests: `tests/`

Responsibilities:

- lock down CLI behavior
- verify extraction and source quality gates
- verify service routing across subject areas
- verify mechanics behavior: schema validation, permission checks, and serializable agent policy

## Service boundaries

AgentWeb treats every external source as a service adapter behind a common `SearchResult` contract.

Current discovery adapters:

| Service | Boundary | Subject use |
|---|---|---|
| DuckDuckGo HTML | unauthenticated HTML endpoint | general web |
| Wikipedia OpenSearch | public JSON API | encyclopedic/humanities |
| Wikidata | public JSON API | entities/facts |
| OpenAlex | public JSON API | scholarly/science |
| Crossref | public JSON API | scholarly/citations |
| arXiv | public Atom API | preprints/science |
| PubMed E-utilities | public JSON API | medicine/biology/clinical |
| GitHub Search | public JSON API | software/code |
| Hacker News Algolia | public JSON API | tech/startups |

Optional fetch fallbacks:

| Service | Boundary | Runtime responsibility |
|---|---|---|
| Jina Reader | public reader endpoint | cleaner article extraction |
| `agent-browser` | local executable if installed | rendered page snapshots |
| Camoufox | optional Python dependency | bot-resistant browser rendering |

## Data flows

### `search`

1. CLI receives query and optional `--service` filters.
2. `core.infer_subject_profile()` chooses service adapters unless explicit services are supplied.
3. `core.search_web()` runs selected providers concurrently.
4. Results are deduplicated by canonical URL.
5. Results are balanced across providers to avoid one source dominating.
6. CLI emits JSON or Markdown.

### `fetch`

1. CLI receives URL and fetch options.
2. `core.fetch_url()` normalizes URL and performs direct HTTP fetch.
3. Extractors gather visible text, title, metadata, links, structured data, and framework payloads.
4. Optional fallbacks run when text is thin or blocked.
5. Quality and blocker checks classify the result.
6. CLI emits JSON or Markdown and returns success/degraded exit code.

### `research`

1. CLI receives query and optional services.
2. `search` flow discovers candidate sources.
3. Top results are fetched concurrently.
4. Fetch results are scored.
5. Usable sources and rejected sources are separated.
6. Evidence snippets are extracted from usable sources.
7. CLI emits a research pack.

### Tool invocation through mechanics

1. A `ToolSpec` is registered with name, schemas, permissions, timeout, failure modes, usage constraints, and handler.
2. An `AgentDefinition` declares allowed tool names and permissions.
3. `ToolRegistry.invoke()` checks agent authorization.
4. Input payload is validated before handler execution.
5. Handler executes.
6. Output is validated before returning to the caller.

## External dependencies

Runtime package dependencies:

- `requests`

Development/test dependencies:

- `pytest`

Optional runtime executables/dependencies:

- `agent-browser`
- `camoufox`

## Runtime responsibilities

AgentWeb core is responsible for:

- deterministic local validation
- clear degraded states
- source citation metadata
- safe extension contracts
- avoiding hardcoded subject-domain assumptions where configuration can express the same behavior

AgentWeb core is not currently responsible for:

- hosted authentication
- tenant isolation
- database persistence
- background worker lifecycle
- model provider billing
- distributed tracing infrastructure

Those are explicit roadmap boundaries, not hidden production claims.

## Extension model

Add a new subject domain by adding configuration/routing terms and service adapters that return `SearchResult`.

Add a new service/tool by registering a `ToolSpec` with `ToolRegistry`. The core orchestrator should depend on the registry contract, not concrete tool code.

Add a new CLI/admin command by wiring the generic registry or core function in `agentweb/cli.py`; avoid embedding domain-specific branches in the CLI.
