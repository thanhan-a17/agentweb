# AgentWeb Requirements Specification

## Product meaning

**AgentWeb** is a local-first web and agent service layer for AI agents. Its job is to turn a broad user request into safe, source-backed work by combining discovery services, retrieval, tool execution, domain routing, and auditable agent mechanics.

**Advanced mechanics** means reusable framework behavior, not one-off scripts:

- configurable agent definitions
- tool/service registration
- input and output schema validation
- permission checks before tool execution
- execution budgets and review policies
- subject/domain routing
- source-backed retrieval and evidence packs
- documented extension points

**Services** are external or internal capabilities exposed behind stable contracts. Examples: web search, PubMed search, arXiv search, GitHub repository search, file parsing, memory retrieval, model providers, and task runners.

**Flexible** means a deployment can add or remove tools, domains, model settings, permissions, and workflow policies without rewriting the core execution path.

**Coverage for all subject matters** means AgentWeb must not hardcode itself around software engineering or startup research. It must support generic discovery plus domain-specific routing/configuration for medicine, science, law/policy, business/finance, education, creative work, operations, customer support, and future domains.

## Current implementation scope

AgentWeb currently provides:

- CLI commands for `search`, `fetch`, `research`, and `services`.
- No-key discovery services across general web, encyclopedic, scholarly, medical, software, and startup sources.
- Fetch extraction for HTML, metadata, JSON-LD, links, Next.js/RSC payloads, Jina Reader fallback, and optional browser/Camoufox fallback.
- Research evidence packs with source quality checks and rejected-source reporting.
- A mechanics module with agent definitions, execution policies, tool/service specs, schema validation, permission enforcement, and tool invocation.
- A versioned SQLite persistence module for agent definitions, task state, tool call records, and audit logs.

## Target capabilities

### Agents

An agent definition must include:

- `name`
- `role`
- `goal`
- allowed `tools`
- `permissions`
- memory settings
- model settings
- execution policy such as max steps, runtime, tool calls, cost, and review requirement

### Tools and services

Every registered tool/service must declare:

- name
- description
- input schema
- output schema
- permissions
- timeout
- known failure modes
- usage constraints
- executable handler or adapter

AgentWeb must validate tool inputs before execution and validate tool outputs before later agent consumption.

### Domain routing

AgentWeb must infer or accept explicit domain configuration and route requests to appropriate tools/services. Current service routing covers:

- general web: DuckDuckGo HTML
- encyclopedic/humanities/entities: Wikipedia, Wikidata
- scholarly/science: OpenAlex, Crossref, arXiv
- medicine/biology/clinical: PubMed
- software/code: GitHub, Hacker News
- startup/market/tech signal: Hacker News, GitHub

### Safety and reliability

AgentWeb should prefer bounded execution over clever runaway behavior:

- reject invalid tool inputs
- reject invalid tool outputs
- deny unauthorized tools
- expose timeout and budget policies
- mark degraded research instead of pretending success
- keep blocker/login-wall pages out of evidence packs
- document known limitations rather than presenting stubs as production systems

## Non-goals for the current package

These are target roadmap items, not current completed behavior:

- hosted multi-tenant auth
- production HTTP API server
- distributed task queues
- persistent database migrations
- full model-provider orchestration
- browser UI
- legal/medical/financial professional advice automation

## Success examples

A working AgentWeb deployment should be able to:

1. Search PubMed for a clinical topic and return structured medical source results.
2. Search arXiv/Crossref/OpenAlex for a scientific research topic.
3. Search GitHub/Hacker News for software tooling research.
4. Fetch a messy web page and emit clean cited text with warnings.
5. Register a new domain tool with schemas and permissions, then reject invalid or unauthorized calls.
