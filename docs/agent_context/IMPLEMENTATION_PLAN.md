# Implementation Plan

> **Note:** the "v1 scope at a glance" and phase checklists below reflect current
> reality; other sections (harness catalog research, resolved design questions) are
> historical and dated as such.

Follow these phases sequentially. Do not move to a new phase until the current one is
tested and verified.

> **Status (2026-07-03):** Phases 1–9 are implemented and verified (84 tests passing
> across CLI, mock runtime, webhook, shim, SDK, discovery, OSS sandbox providers,
> mocks, and cross-cutting security — including custom harness registration, the
> cloud-neutral `k8s` target, and the `remote-runtime`/`enterprise-runtime` alias).
> Phase 0 lists three **upstream** sandbox runtime dependencies tracked with whichever
> team owns your sandbox backend. Two Phase 9 items are **deliberately deferred** to
> the roadmap (typed live skills/MCP catalog; TypeScript SDK) — see Phase 9 below and
> `FRAMEWORK_EVOLUTION.md`.

> **Reconciled 2026-07-01** with `DESIGN_NOTES.md`. Tethricor is a **thin developer-facing
> abstraction** over your organization's AI platform (an OpenAI-compatible LLM gateway,
> an MCP-compatible tool/skills server, your identity provider, and optionally a remote
> sandbox execution service). Tethricor *consumes/integrates* those; it *builds* only
> the config contract, CLI, hardened harness images + exec shim, and the injectors. See
> `DESIGN_NOTES.md` §1 for the build-vs-consume split and §7 for the (illustrative)
> runtime API shape.

## v1 scope at a glance
- **Harnesses (open registry, not a closed enum):** built-in adapters for `hermes, pi,
  feynman, openhands, goose, opencode` — **5 adapters, 6 types** (`pi` and `feynman`
  share the Pi adapter; Feynman = Pi + `research` profile). See `DESIGN_NOTES.md` §3A.
  Custom harnesses register via `tethricor_runtime.adapters.register_harness` or the
  `tethricor.harnesses` entry point and are usable immediately, no schema change.
- **Deployment targets (CLI `--target`):** cloud-neutral `local`, `k8s`; `aks` (k8s +
  Azure Workload Identity, back-compat name); `aci`/`job` (explicitly Azure-specific,
  opt-in). **Functions/WebJobs are descoped for v1.**
- **Code IN:** git clone into the sandbox session (`repoUrl`, read-only token).
  **Code OUT:** zip of changed files via a sandbox artifact **download endpoint**
  (fallback: base64-zip over stdout). No git write-back.
- **LLM + MCP:** routed through your configured LLM gateway (OpenAI-compatible
  assumption, no vendor hardcoded); local testing may use a direct-Azure-OpenAI escape
  hatch that is stripped for non-local targets.
- **Sandbox provider (`runtime.provider`):** no default — choose explicitly.
  `remote-runtime` (generic REST/SSE client, always installed) works against any
  compatible service; `microsandbox`/`e2b` are opt-in real-isolation packages.
- **Security invariants:** execution ALWAYS forwarded to the sandbox provider (never run
  in the harness container); egress default-deny except `{gateway, sandbox runtime}`;
  read-only root fs; non-root; **never** the runtime `memory` provider outside CI.

## Phase 0: Upstream agent-runtime dependencies (EXTERNAL — track, don't build here)
These live in whatever sandbox control-plane service you operate and gate parts of
later phases. Socialize early with the runtime team.
- [ ] **`repoUrl` git-clone** implemented at session create (currently a reserved,
      unimplemented field). Unblocks code-IN.
- [ ] **Language profiles + hardened images** added to `internal/profiles`
      (`python312`, `rust`, `go`, `polyglot-dev`) and discoverable via `GET /v1/profiles`.
      Unblocks running our harnesses' executed code.
- [ ] **Binary artifact download endpoint** (e.g. `GET /v1/sessions/{id}/artifacts/{name}`
      → `application/zip`). Unblocks code-OUT (primary path). Fallback if not delivered:
      base64-zip over the existing SSE stdout channel.

## Phase 1: Schemas & Contracts
- [x] Create `schemas/harness-config-schema.json` (JSON Schema) for `harness.yaml`.
      Fields (see `DESIGN_NOTES.md` §4 strawman):
  - `apiVersion` (`tethricor.enterprise/v1`), `kind` (`HarnessConfig`).
  - `harness.type` (enum: hermes|pi|feynman|openhands|goose|opencode), `harness.version`.
  - `model.routing_profile` (string alias); optional `model.direct_azure_openai`
    (**local-only** escape hatch — schema/validation must reject it for non-`local`
    `--target`).
  - `skills` (free-form list of strings — v1), `mcp.servers` (free-form refs — v1).
    Keep opaque so a future live-catalog validator can resolve without schema changes.
  - `runtime.profile` (must validate against agent-runtime `GET /v1/profiles`),
    `runtime.timeout_seconds`.
  - `source.repo_url`, `source.ref` (code IN).
  - `output.mode` (`zip-download`; fallback `stdout-changed-files`).
  - **NOT** in the file: deployment target (CLI `--target` flag) and platform-injected
    security/identity/image fields (locked, developer cannot set).
- [x] Sandbox execution contract: **reuse the existing agent-runtime OpenAPI** from
      whatever sandbox control-plane service you operate — do NOT invent one.
      Reference copy at `api-spec/sandbox-execution-contract.yaml`, extended only with the
      new artifact **download** endpoint (Phase 0). Contract shape (DESIGN_NOTES §7):
      sessions → async `exec` (`202`) → SSE events (`stdout|stderr|exit|error`) → delete;
      error envelope `{"error":{"code","message"}}`.
- [x] Provide a canonical example `harness.yaml` per harness type.

## Phase 2: The Developer CLI
- [x] Build a Python CLI (`tethricor`) using `Typer` + `pydantic`.
- [x] `tethricor init` — interactively prompts for harness type, version, skills,
      mcp servers, model routing profile, source repo; writes a valid `harness.yaml`;
      validates against the Phase-1 schema. Applies the **harness→default runtime.profile**
      map (hermes/openhands→`python312`; pi/feynman/opencode→`node20`; goose→`rust`).
- [x] `tethricor local-dev` — generates artifacts for a chosen `--target`
      (`local|aks|aci|job`), keeping `harness.yaml` portable (target is a flag, not a
      field). For `local`, emits a `docker-compose.yaml` wiring app + hardened sidecar +
      local mocks (Phase 3). Strips/blocks the `direct_azure_openai` escape hatch for any
      non-`local` target.
- [x] Resolve `harness.type`+`harness.version` → hardened image via the platform image
      **manifest** (never developer-overridable).

## Phase 3: Local Mock Environment (parity doubles only)
- [x] `local-dev/mock-sandbox.py` (FastAPI) that **mirrors the agent-runtime contract**
      (DESIGN_NOTES §7): `/healthz`, `/v1/profiles`, session create/get/delete,
      async `exec` (`202`), SSE `exec/{id}/events` with `stdout|stderr|exit|error`, and
      the artifact **download** endpoint. Implements `memory`-style semantics.
      (Supersedes the old "single POST returns stdout" mock.)
- [x] `local-dev/mock-mcp.py` — minimal MCP server (HTTP/SSE) serving dummy tools,
      standing in for the enterprise MCP reached via AgentGateway.
- [x] CLI `local-dev` docker-compose binds the sidecar to these local mocks and a
      mock/echo AgentGateway (or direct-Azure-OpenAI escape hatch).

## Phase 4: Injection — AKS Mutating Webhook + all-target injectors
- [x] Kubernetes **Mutating Webhook** (Python/FastAPI or Go) handling `AdmissionReview`:
      on the enablement label/annotation (+ `harness.yaml` ConfigMap), inject the correct
      **hardened harness sidecar** (image resolved from the manifest), mount identity
      (Azure Workload Identity → OIDC), and **strip insecure configs**.
- [x] Injectors for the other targets (generation-time, from the same `harness.yaml`):
      `local`→docker-compose; `aci`/`job`→ACI container group / Container Apps Job spec.
- [x] **Enforce platform-locked security** at injection for every target:
      egress **default-deny except `{AgentGateway, agent-runtime}`**, `readOnlyRootFs`,
      `runAsNonRoot`, and refuse any config pointing at the runtime `memory` provider
      for non-`local` targets.

## Phase 5: Image Hardening (Dockerfiles) + exec shim
- [x] Hardened Dockerfiles for the v1 harness set (5 adapters):
      `docker/Dockerfile.hermes-hardened`, `.pi-hardened` (also serves `feynman` via the
      `research` profile), `.openhands-hardened`, `.goose-hardened`, `.opencode-hardened`.
- [x] Strict pod security: non-root user, read-only root fs, minimal base.
- [x] **Execution shim** replacing each harness's native execution/terminal backends so
      ALL code exec is forwarded to the agent-runtime (never run locally). The shim is
      **session-oriented + async + streaming**: create session (with `source.repo_url`
      clone) → `exec` (`202`) → subscribe SSE → on completion, run the adapter **output
      profile** that `git diff`-zips changed files and exposes them via the artifact
      download endpoint; then `DELETE` the session. One session **per task**; heartbeat
      to extend TTL; handle `410 session_expired`.
- [x] Per-harness hardening notes: **Hermes** — disable messaging gateway, autonomous
      skill-creation, cron; **all** — strip provider keys and route LLM/MCP via
      AgentGateway; override native sandboxes (Docker/Modal/SSH/etc.) → agent-runtime.

## Phase 6: End-to-end + security verification
- [x] E2E on `local`: `init` → `local-dev` → run a task → code cloned in, changed files
      returned as a zip.
- [x] Verify egress default-deny (only AgentGateway + agent-runtime reachable).
- [x] Verify no execution path runs inside the harness container and `memory` provider
      is refused for non-`local`.
- [x] Repeat happy-path on `aks`, then `aci`/`job`.

## Framework evolution phases (plug-and-play; additive & backward-compatible)
Source of truth: `FRAMEWORK_EVOLUTION.md` (§4 architecture, §5 sandbox providers,
§6 config, §7 roadmap). **Guardrails for ALL phases below** (`.cursorrules` #5–#8):
every requirement ships with tests (incl. the provider **conformance kit**); no code
bloat or duplication (extract shared logic once, smallest change that works); only
current, well-maintained, appropriately-licensed deps (AGPL needs review); everything
runs **local E2E** (mocks / `docker-compose.test.yaml`) AND stays deployable to
`local|aks|aci|job` with the enterprise agent-runtime as the **default** provider.

### Phase 7: Framework v0 — extract interfaces (no behavior change) — DONE
- [x] Promote `runtime_client.RuntimeClient` to a `SandboxProvider` ABC + an
      `enterprise-runtime` implementation (the current client, unchanged behavior).
      → ABCs in `shim/tethricor_runtime/interfaces.py`; `RuntimeClient(SandboxProvider)`;
      registry in `shim/tethricor_runtime/registry.py` (orchestrator resolves via it).
- [x] Formalize `HarnessAdapter` and `ModelRouter` ABCs + in-process registries by
      refactoring the existing `adapters.py`/routing — **reuse, don't duplicate**.
      → `Adapter(HarnessAdapter)`; new `GatewayRouter(ModelRouter)` in `model.py` now
      owns the LLM base-URL env (removed the inline duplication in `session_env`).
- [x] Extract the mock's contract checks into a reusable conformance kit; prove
      `enterprise-runtime` + the mock both pass it. Existing tests stay green.
      → `shim/tethricor_runtime/testing.assert_sandbox_conformance` (moves to `tethricor.testing`
      in Phase 8); `shim/tests/test_conformance.py`. Suite now 45 passing.

### Phase 8: Framework v1 — SDK + plugin discovery — DONE
- [x] Shipped the importable `tethricor` package (co-located in the shim distribution) with a
      `Harness` facade + typed `Event` / `TaskResult` / `SandboxSession` (`shim/tethricor/`).
      The sidecar CMD (`tethricor_runtime.__main__`) now delegates to `tethricor.cli:main` — single
      code path, no logic fork. Endpoint defaults centralized in `config.py` constants.
- [x] Entry-point discovery (`shim/tethricor/discovery.py`) for provider packages across all
      three axes (`tethricor.sandboxes`, `tethricor.harnesses`, `tethricor.models`); loaded idempotently
      at `import tethricor`. Added `adapters.register_harness` and a model-router registry in
      `model.py` (`register_router`/`get_router`, `TETHRICOR_MODEL_ROUTER`-selectable default).
- [x] Added optional `runtime.provider` to the schema (default `enterprise-runtime`,
      non-empty, validated at generation/run time not statically) and to the Pydantic
      `Runtime` model (`exclude_none` keeps existing configs byte-for-byte). Added
      `tethricor init --sandbox` with soft registry validation (falls back to the
      built-in default when the SDK isn't installed). `memory`/insecure providers stay
      refused for non-local via the webhook (unchanged).
- [x] Tests: `shim/tests/test_sdk.py` (Harness E2E, `from_config`, `open_session`),
      `shim/tests/test_discovery.py` (three-axis discovery + model-router selection),
      CLI back-compat + `--sandbox` cases in `cli/tests/test_cli.py`. Suite now 56 passing.

### Phase 9: Framework v2 — adopt OSS providers + adapter depth — DONE (with noted deferrals)
- [x] Adopted **microsandbox** (Apache-2.0, primary) and **E2B** (Apache-2.0, dev/managed)
      as separate `SandboxProvider` packages under `providers/`, each self-registering via
      the `tethricor.sandboxes` entry point and **gated on the conformance kit**
      (`tethricor_runtime.testing.assert_sandbox_conformance`). Do **not** build a sandbox —
      both translate our contract onto the upstream backend (microsandbox REST;
      E2B via a lazily-imported SDK seam). Conformance runs hermetically against in-package
      fakes that reuse shared test-double exec/zip helpers in `tethricor_runtime.testing`
      (no KVM/keys in CI). Daytona intentionally **not** adopted (AGPL + unmaintained OSS).
- [x] Deepened per-harness adapters: **task intake** (`HarnessAdapter.run_argv`) turns a
      natural-language task into each harness's conventional launch command (Hermes/Pi/
      OpenHands/Goose/opencode `entrypoint` + `task_arg`), with explicit-argv passthrough;
      richer integration env (Pi JSONL/RPC, OpenHands remote runtime, Goose MCP transport).
      `Harness.run(task_or_argv)` now accepts either.
- [x] **Observability callbacks** (`tethricor_runtime.observability.Callbacks`, OTel/LangSmith-style
      lifecycle hooks) threaded through `orchestrator.run_task` (the old `on_event` is kept
      as sugar over the same path); exported as `tethricor.Callbacks`.
- [ ] **Deferred (roadmap, not built):** typed skills/MCP **live-catalog** resolution
      (DESIGN_NOTES A1 keeps skills/mcp free-form for v1 until the catalog service exists)
      and the **TypeScript SDK** (large new surface; sequence after Python SDK adoption).
      Deferred deliberately to avoid speculative, untestable code (`.cursorrules` #5–#8).
- [x] Tests: microsandbox + E2B each pass the conformance kit
      (`providers/*/tests/test_*_conformance.py`); adapter task-intake and callback
      lifecycle tests (`shim/tests/test_phase9.py`). Suite now 65 passing. Real-backend
      E2E on `local` via microsandbox needs a KVM host — documented as an integration
      (non-CI) step in the provider README.

## Cross-cutting invariants (apply to every phase)
- **Security-first (`.cursorrules` #1):** execution is ALWAYS forwarded to the
  agent-runtime; the harness container never executes code/bash locally.
- **Gateway enforcement (`.cursorrules` #2):** all LLM/MCP calls go through AgentGateway;
  no hardcoded provider SDK endpoints (local escape hatch excepted, and stripped for
  non-local).
- **Sidecar pattern (`.cursorrules` #3):** harness runs alongside the app container
  (except the generation-time targets, which compose the same shape at build time).
- **Config as contract (`.cursorrules` #4):** `harness.yaml` validated against the
  Phase-1 JSON schema; developer declares intent, platform enforces security.

## Traceability
Every decision here is sourced in `DESIGN_NOTES.md`: reframing §1–2; harness list §3A;
targets §3B; schema §4; runtime contract §7; resolved/accepted decisions and the three
upstream deps §8 (A1–A8).
