# Agent Prompts Library

> **Note:** these prompts are historical — they document the original phase-by-phase
> build and may reference since-renamed concepts (e.g. `enterprise-runtime`, now
> `remote-runtime`). Phases 1–9 are done; if you're extending Tethricor today, read
> `.cursorrules` first, not these prompts verbatim.

Copy and paste these prompts into your IDE chat (Cursor, Cline, Roo Code) to trigger
specific blocks of work reliably.

> **Reconciled 2026-07-01** with `IMPLEMENTATION_PLAN.md` and `DESIGN_NOTES.md`.
> Always have the agent read `DESIGN_NOTES.md` (source of truth for decisions) and the
> current phase in `IMPLEMENTATION_PLAN.md` before coding.

### Context primer (run first)
> "Read `docs/agent_context/PROJECT_CONTEXT.md`, `docs/agent_context/DESIGN_NOTES.md`,
> `docs/agent_context/IMPLEMENTATION_PLAN.md`, and (for framework work)
> `docs/agent_context/FRAMEWORK_EVOLUTION.md`. Tethricor is a thin abstraction over the
> existing platform (LLM gateway, MCP/skills, identity/auth, sandbox runtime service).
> Do not invent new sandbox/gateway/auth systems — consume the existing ones. Obey the
> engineering constraints in `.cursorrules` #5–#8."

### Trigger Phase 0 (Upstream deps — coordination, not local build)
> "Summarize the three agent-runtime dependencies from IMPLEMENTATION_PLAN Phase 0
> (`repoUrl` git-clone, language profiles `python312`/`rust`/`go`/`polyglot-dev`, and a
> binary artifact download endpoint). Draft issue descriptions for the agent-runtime
> team, referencing `DESIGN_NOTES.md` §7/§8."

### Trigger Phase 1 (Schemas & Contracts)
> "Begin Phase 1. Create `schemas/harness-config-schema.json` for `harness.yaml` with:
> `harness.type` (enum: hermes, pi, feynman, openhands, goose, opencode), `harness.version`,
> `model.routing_profile` (+ optional `model.direct_azure_openai` that must be rejected
> for non-local targets), free-form `skills` and `mcp.servers`, `runtime.profile` +
> `runtime.timeout_seconds`, `source.repo_url`/`source.ref`, and `output.mode`
> (`zip-download`). Do NOT include deployment target (it's a CLI flag). Then vendor the
> agent-runtime OpenAPI to `api-spec/sandbox-execution-contract.yaml` and add only the
> artifact download endpoint. Add one example `harness.yaml` per harness type."

### Trigger Phase 2 (CLI Builder)
> "Phase 2. Create `cli/` with a `typer` + `pydantic` CLI `tethricor`. `init`
> prompts for harness type/version, skills, mcp servers, routing profile, and source
> repo, then writes and schema-validates `harness.yaml`, applying the harness→default
> `runtime.profile` map. `local-dev --target local|aks|aci|job` generates target
> artifacts from the same config; for `local` emit a `docker-compose.yaml` with app +
> hardened sidecar + local mocks, and strip `direct_azure_openai` for non-local targets.
> Resolve images via the platform manifest (never developer-overridable)."

### Trigger Phase 3 (Mock Servers)
> "Phase 3. Build `local-dev/mock-sandbox.py` (FastAPI) that MIRRORS the agent-runtime
> contract: `/healthz`, `/v1/profiles`, session create/get/delete, async `exec` (202),
> SSE `exec/{id}/events` (`stdout|stderr|exit|error`), and the artifact download
> endpoint — memory-style semantics. Build `local-dev/mock-mcp.py` (minimal MCP over
> HTTP/SSE). Wire both into the CLI's docker-compose."

### Trigger Phase 4 (Injection — Webhook + injectors)
> "Phase 4. Write a Kubernetes Mutating Webhook (FastAPI or Go) that, on the enablement
> label + `harness.yaml` ConfigMap, injects the hardened harness sidecar (image from the
> manifest), mounts Azure Workload Identity, and strips insecure configs. Add
> generation-time injectors for `aci`/`job`. Enforce egress default-deny except
> {AgentGateway, agent-runtime}, read-only root fs, non-root, and refuse the `memory`
> provider for non-local targets."

### Trigger Phase 5 (Image Hardening + shim)
> "Phase 5. Write hardened Dockerfiles for hermes, pi (also serves feynman), openhands,
> goose, opencode: non-root, read-only root fs, minimal base. Add the execution shim
> that forwards ALL code execution to the agent-runtime (create session with git clone →
> exec 202 → subscribe SSE → run the adapter output profile that git-diff-zips changed
> files to the artifact endpoint → delete session; one session per task, heartbeat TTL,
> handle 410). For Hermes, disable messaging gateway, autonomous skill-creation, and
> cron. Route all LLM/MCP via AgentGateway."

### Trigger Phase 6 (E2E + security verification)
> "Phase 6. Run the local E2E: init → local-dev → execute a task → confirm code is
> cloned in and changed files come back as a zip. Verify egress is default-deny, no
> execution runs inside the harness container, and the `memory` provider is refused for
> non-local targets. Then repeat the happy path on aks, aci, and job."

---
> **Framework phases (7–9): read `FRAMEWORK_EVOLUTION.md` first, and obey `.cursorrules`
> #5–#8 — tests for every requirement (incl. the conformance kit), no bloat/duplication,
> modern well-licensed deps only, local-E2E + prod-ready, and NO regressions to Phases
> 1–6 (keep enterprise agent-runtime the default).**

### Trigger Phase 7 (Framework v0 — extract interfaces)
> "Phase 7. Without changing behavior, promote `runtime_client.RuntimeClient` to a
> `SandboxProvider` ABC + an `enterprise-runtime` impl, and formalize `HarnessAdapter`
> and `ModelRouter` ABCs + registries by refactoring the EXISTING `adapters.py`/routing
> (reuse, don't duplicate). Extract the mock's contract checks into a reusable
> `tethricor.testing` conformance kit and show enterprise-runtime + the mock pass it. All 42
> existing tests must stay green."

### Trigger Phase 8 (Framework v1 — SDK + plugin discovery)
> "Phase 8. Ship an importable `tethricor` package with a `Harness` facade + typed
> `Event`/`TaskResult`/`SandboxSession`; make the CLI a thin wrapper (no logic fork). Add
> entry-point discovery (`tethricor.harnesses`/`tethricor.sandboxes`/`tethricor.models`). Add optional
> `runtime.provider` to the schema (default `enterprise-runtime`) + CLI `--sandbox` flag,
> validated against the registry. Add SDK/registry/back-compat tests."

### Trigger Phase 9 (Framework v2 — OSS providers + adapter depth)
> "Phase 9. Adopt microsandbox (primary) and E2B (dev/managed) as separate
> `SandboxProvider` packages, each gated on the conformance kit; allow swapping the local
> mock for microsandbox behind a flag (do NOT build a sandbox; Daytona only after AGPL
> review). Deepen per-harness adapters (Pi RPC, OpenHands remote runtime, Goose MCP) +
> output profiles. Add typed skills/MCP catalog resolution and observability callbacks.
> Each provider must pass the conformance kit; add a microsandbox local E2E."
