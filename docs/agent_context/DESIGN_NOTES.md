# Design Notes — Tethricor Scope & `harness.yaml` Brainstorm

> **Note:** the decisions and rationale below are historical design-exploration notes,
> not current instruction — treat `.cursorrules` and `PROJECT_CONTEXT.md` as the source
> of truth for what's current.

> Living note capturing decisions from the scope brainstorm. Supplements `PRD.md`.
> Status: **draft / in discussion**. Update as questions below get answered.

## 1. Core Reframing: Tethricor is a thin abstraction, not a platform

The enterprise AI platform already exists in a separate repository. Tethricor is an
**offering / developer-facing façade** on top of it. Tethricor therefore *consumes and
integrates* far more than it *builds*.

| Capability | Owner | Tethricor responsibility |
|---|---|---|
| LLM routing, token tracking, PII scrub, cost | Internal LLM Gateway product (exists) | Consume — point sidecars at it, don't rebuild |
| MCP + skills serving | Enterprise AI platform (exists) | Consume — reference catalog entries in config |
| Auth (Azure AD OIDC / OAuth) | Existing auth layer (exists) | Integrate — sidecar must acquire/forward a token |
| Agent runtime / real sandbox | Agent runtime env (exists) | Integrate — forward code execution to its API |
| `mock-sandbox.py`, `mock-mcp.py` | Tethricor (local only) | Dummies emulating the two above for local parity |
| `harness.yaml` + JSON schema | **Tethricor** | Build |
| CLI (`init`, `local-dev`) | **Tethricor** | Build |
| Hardened harness images + exec shim | **Tethricor** | Build |
| AKS Mutating Webhook + injectors | **Tethricor** | Build |

**Implication:** the local `mock-sandbox` and `mock-mcp` are test doubles only. In
production, sidecars talk to the real AgentGateway, MCP/skills platform, and agent
runtime. Tethricor must *conform to those existing APIs*, not invent new ones.

## 2. Resolved / de-scoped items (from initial gap analysis)

- **UI** — de-scoped for now; CLI is sufficient. Revisit later.
- **LLM gateway product specifics** — resolved. The internal LLM gateway handles routing
  OOTB; Tethricor only needs a `routing_profile` pointer/alias, no SDK config.
- **Sandbox execution contract** — do **not** invent. **Resolved:** the real
  agent-runtime API is now known (see §7). The Phase-1 OpenAPI and `mock-sandbox.py`
  must mirror it (sessions + async exec + SSE event stream).
- **MCP server design** — resolved as a build item; becomes an *integration* item
  (endpoint + protocol to point at). Mock retained for local only.
- **Auth / observability / cost tracking** — resolved by AgentGateway + existing
  Azure AD OIDC/OAuth. Residual Tethricor work: sidecar identity acquisition
  (Azure Workload Identity → OIDC token → AgentGateway).
- **Egress control** — simplified. Because all LLM + MCP + code-exec traffic flows
  through AgentGateway and the runtime, the egress allowlist collapses to two
  internal endpoints: `{AgentGateway, agent-runtime}`. Webhook can enforce a
  default-deny by default.

## 3. Still open (active design topics)

### A. Multi-harness support (adapter/plugin model)
Do not hardcode harness types. Each harness differs in how it (a) accepts a task,
(b) calls the LLM, (c) invokes tools, (d) executes code. Tethricor needs a **per-harness
adapter** mapping those four concerns onto `{AgentGateway, MCP, agent-runtime}`.
`harness.yaml` then just names a harness + capability profile.

#### v1 Recommended harness list (supported-adapter enum)
The initial supported set. All are standalone (sidecar-injectable), model-agnostic
(route via AgentGateway), and MCP-capable. Frameworks (LangGraph/CrewAI) and
security/browser tiers are explicitly deferred past v1.

| # | `harness.type` | Repo / source | Lang | Category | Adapter notes |
|---|---|---|---|---|---|
| 1 | `hermes` | `github.com/nousresearch/hermes-agent` | Python | General / self-improving | Disable messaging gateway, autonomous skill-creation, cron; override terminal backends → sandbox. |
| 2 | `pi` | `pi.dev` (`@earendil-works/pi-coding-agent`) | Node/TS | Coding (minimal) | Integrate via RPC/JSONL mode; override Gondolin/Docker/OpenShell → sandbox. |
| 3 | `feynman` | `feynman.is` | Node/TS | Research | **Pi adapter + `research` profile** (not a separate core); redirect Docker/Modal/RunPod → runtime. |
| 4 | `openhands` | `github.com/All-Hands-AI/OpenHands` | Python | Autonomous SWE | Docker/chroot sandbox native; MCP-friendly; K8s-aware — override sandbox → enterprise runtime. |
| 5 | `goose` | Block / Linux Foundation (AAIF) | Rust | General / MCP-first | MCP-first, per-team allowlist + audit logs; override execution extensions → sandbox. |
| 6 | `opencode` | `github.com/anomalyco/opencode` (MIT) | TS | Coding | Model-agnostic, MCP + LSP + sub-agents, server mode; override exec → sandbox. |

Notes:
- Feynman shares the Pi adapter core, so v1 = **5 adapters** covering **6 harness
  types** (`pi` and `feynman` both map to the Pi adapter).
- Every entry requires the hardening shim (override native execution → Proprietary
  Sandbox) and gateway-neutral routing (strip provider keys → AgentGateway).
- Deferred to later tiers: orchestration frameworks (library mode), security/pentest
  agents (Gideon, pentest-ai, ...), browser/computer-use agents (Browser Use,
  Stagehand, Skyvern, ...).

#### Confirmed classification (harness vs. model)
| Name | Verdict | Notes |
|---|---|---|
| **Hermes** (`github.com/nousresearch/hermes-agent`) | **Harness** (Python) | Self-improving agent; model-agnostic; MCP + skills + cron + subagents built in. **NOT** the Hermes model family. |
| **Pi** (`pi.dev`, `@earendil-works/pi-coding-agent`) | **Harness** (Node/TS) | Minimal terminal coding agent; SDK + RPC (stdin/stdout JSONL) + extensions/skills. |
| **Feynman** (`feynman.is`) | **Harness = Pi derivative** | Research agent **built on Pi**; ships as **Pi skills** + alphaXiv. Model as a Pi *profile*, not a separate adapter core. |
| **OpenHands, SWE-agent, Aider** | Harness (software-eng) | Candidates, not yet confirmed in scope. |
| **Goose** | Harness (general, MCP-native) | Candidate, not yet confirmed. |

Key consequences:
1. **Hermes name is overloaded.** Nous publishes both *Hermes models* and the
   *Hermes agent*. Keep them on separate `harness.yaml` axes: `harness.type: hermes`
   vs. `model.routing_profile: <a-hermes-model-alias>`. They must never collide.
2. **Feynman is Pi + research skills**, not a distinct core. Likely modeled as the
   **Pi adapter + `research` profile**, so one adapter serves both coding-Pi and
   Feynman. Reduces adapter count.

#### Per-harness security/integration notes
All three are model-agnostic (strip provider keys → route via AgentGateway) and all
three ship their own execution/terminal backends that MUST be overridden by the
hardening shim to force the proprietary sandbox:
- **Hermes:** local, Docker, SSH, Singularity, Modal, Daytona backends. Extra egress
  surface — messaging gateways (Telegram/Discord/Slack/WhatsApp/Signal) and bundled
  Git Bash. Hardened image must **disable messaging gateway + autonomous skill
  creation + cron** by default.
- **Pi:** Gondolin, Docker, OpenShell backends. RPC/JSONL mode is a clean, scriptable
  integration surface for the sidecar.
- **Feynman:** Docker, Modal, RunPod compute targets for experiments — all must be
  redirected to the enterprise runtime.

#### Candidate harness catalog (market research, 2026)
Sourced from 2026 ecosystem surveys. Two architectural classes matter for Tethricor:
- **Standalone harnesses** = own process + agent loop → *injectable as a sidecar*
  (the Tethricor sweet spot).
- **Frameworks/libraries** = SDKs the developer *builds an app with* → embedded in
  the app container, not injected. Supporting these is a different integration mode
  (library, not sidecar). Flagged below as `[framework]`.

General / coding (model-agnostic, MCP-capable — strong sidecar fits):
| Harness | Lang | Notes / Tethricor fit |
|---|---|---|
| **OpenHands** (ex-OpenDevin) | Python | Autonomous, Docker/chroot sandbox, MCP-friendly, K8s support, Planning Mode. Production default; strong enterprise fit. |
| **Goose** (Block → Linux Foundation/AAIF) | Rust | MCP-first, 70+ extensions, 15+ providers, per-team allowlist + audit logs. Excellent fit. |
| **OpenCode** (`anomalyco/opencode`, MIT) | TS | Model-agnostic, MCP + LSP + sub-agents, has server mode. Strong fit. |
| **Aider** | Python | Git-native pair programmer; monolithic tools, **native exec (no sandbox)** → hardening shim essential. |
| **gocode** | Go | Single 12MB binary, MCP client+server, API-server mode, 200+ models. Very easy to harden/deploy. Newer — vet maturity. |
| **muxd** | Go | Daemon+client, persistent sessions, self-extending tools. Daemon model fits sidecar. Newer — vet. |
| **OpenClaw** | — | Velocity leader, Anthropic-style loop, foundation governance. (Hermes migrates *from* OpenClaw.) |
| **Cline / Continue** | TS | Primarily IDE extensions; have CLI/SDK. Weaker sidecar fit. |
| **Codex CLI / Gemini CLI / Qwen Code** | — | Vendor-leaning (OpenAI/Google/Qwen); less aligned with gateway-neutral routing. |
| **SWE-agent / mini-SWE-agent** | Python | Research/benchmark baseline; single-issue fixing. Useful for eval, not production. |
| **Plandex, Open Interpreter** | — | Planning / code-execution niche agents. |

Multi-agent orchestration `[framework]` (embed in app, not sidecar):
| Framework | Notes |
|---|---|
| **LangGraph** | Graph/state-machine; production standard, checkpointing, HITL, LangSmith observability. |
| **CrewAI** | Role-based, fast prototyping, 100+ tools, Pydantic outputs. MIT. |
| **AutoGen → AG2 / Microsoft Agent Framework (MAF)** | AutoGen in maintenance; AG2 is the drop-in fork, MAF the Azure/.NET successor. |
| **Smolagents** (HF) `[framework]` | Code-first single-agent, data/research scripts. |
| **Haystack** `[framework]` | RAG / large-document synthesis. |

Specialized / domain-specific (high governance value — sandbox + egress lockdown
directly justify these):
| Domain | Candidates | Notes |
|---|---|---|
| Research | **Feynman** (in scope), | Pi-based research agent. |
| Security / pentest | **Gideon** (dual-mode SecOps/red-team, auditable), **pentest-ai** (MCP, 17 agents, 205 tools), **AIRecon** (offline Kali sandbox), **AgentShield** (DAST/CrewAI) | Run exploit tooling → *exactly* what sandbox forcing + egress deny is designed to contain. High value, high risk. |
| Browser / computer-use | **Browser Use** (Py) `[framework]`, **Stagehand** (TS/Playwright) `[framework]`, **Skyvern** (vision-first), **Mantis**, **Agent TARS** | Need explicit browser-egress policy; don't fit pure sandbox model. |
| Data analysis | **Smolagents**, **Haystack** `[framework]` | Overlap with orchestration frameworks. |

> Caveat: star counts / maturity vary and some (gocode, muxd, several pentest agents)
> are newer. Vet license, governance, and maintenance before admitting to the
> supported-adapter enum.

Recommended v1 shortlist to discuss (strong sidecar fit + enterprise posture):
**OpenHands, Goose, OpenCode** alongside the already-chosen **Hermes, Pi, Feynman**.
Defer frameworks (LangGraph/CrewAI) to a separate "library mode," and treat
security/browser agents as a later specialized tier once egress policy is proven.

### B. Non-AKS Azure targets (one config, multiple injectors)

Decision (updated 2026-07-01): **v1 targets = `local`, `aks`, `aci`, `job`**, selected
via the CLI `--target` flag. One `harness.yaml`, several injectors. **Azure Functions /
WebJobs are DESCOPED for v1** (see A7).

| Target | `--target` | Injection mechanism |
|---|---|---|
| Local Docker | `local` | CLI generates `docker-compose` (generation-time) |
| AKS | `aks` | Mutating Webhook (admission-time) |
| ACI / Container Apps Jobs | `aci` / `job` | CLI/IaC generates multi-container group spec (generation-time) |
| ~~Functions / WebJobs~~ | ~~`function`~~ | **Descoped for v1** — no sidecar possible; would need a central hosted-endpoint pattern. Revisit later. |

## 4. `harness.yaml` design axes

Guiding principle (from `.cursorrules` #4 and PROJECT_CONTEXT "strips insecure
configs"): **developer declares *intent*; platform *enforces* security.** Fields
split into developer-owned vs. platform-injected/locked.

Strawman (updated with v1 decisions):

```yaml
apiVersion: tethricor.enterprise/v1        # contract is versioned
kind: HarnessConfig

harness:
  type: goose                          # from supported-adapter enum
  version: "1.x"                       # resolves to a hardened image tag (platform-controlled)

model:
  # v1: routing_profile is a free abstraction; migrates to AgentGateway model
  # aliases in a later version once the gateway team's deployment lands.
  routing_profile: "gpt-4o-standard"
  # LOCAL TESTING ONLY escape hatch — direct-to-Azure-OpenAI when AgentGateway
  # is not available locally. MUST be rejected/stripped for non-local targets.
  # direct_azure_openai:
  #   endpoint: https://<resource>.openai.azure.com
  #   deployment: gpt-4o

skills:                                # v1: FREE-FORM list of strings
  - code-review                        #   (later: validated against live catalog)
  - jira

mcp:
  servers: [enterprise-default]        # v1: FREE-FORM refs (later: catalog-validated)

runtime:                               # execution forwarding target (agent-runtime)
  profile: python312                   # must be one of agent-runtime GET /v1/profiles
  timeout_seconds: 600

source:                                # code IN — v1: git clone at session create
  repo_url: "https://git.enterprise/org/app.git"
  ref: main                            # read-only clone token injected by platform

output:                                # code OUT — v1: zip of changed files, download-ready
  mode: zip-download                   # via runtime artifact download endpoint (upstream dep)
                                       # optional local fast-path: shared mounted volume
                                       # NO git write-back; fallback: base64-zip over stdout

# NOTE: deployment target is NOT a harness.yaml field. It is a CLI flag at
# generation time (`--target local|aks|aci|job`) so one config stays portable
# across all targets. (Functions/WebJobs descoped for v1.)

# --- platform-injected / developer cannot override ---
# security: { egress: deny-all-except: [agentgateway, runtime], readOnlyRootFs: true, runAsNonRoot: true }
# identity: workload-identity ref for Azure AD OIDC
```

Schema decisions (v1) — RESOLVED:
1. **`skills` / `mcp` are free-form** in v1. Design must leave room to swap in
   **live-catalog validation** later (keep the fields as opaque string refs so a
   future validator can resolve them without a schema change).
2. **`routing_profile` is the abstraction** for v1. Migrates to AgentGateway model
   aliases later. Provide a **local-testing-only** direct-to-Azure-OpenAI route;
   it must be stripped/rejected for any non-local `--target`.
3. **`deployment.target` is a CLI flag**, not a config field — keeps `harness.yaml`
   portable across local/AKS/ACI/Job/Function.

## 5. Inputs needed to proceed — ALL RESOLVED
1. ~~The **agent-runtime execution API** shape.~~ **Done** — documented in §7.
2. ~~Whether **AgentGateway exposes model aliases**.~~ **Resolved** — v1 uses the
   `routing_profile` abstraction; alias migration deferred to a later version.
3. ~~Confirm Hermes = model vs. harness; identify Pi/Feynman; set v1 harness list.~~
   **Done** — v1 supported set locked: `hermes, pi, feynman, openhands, goose,
   opencode` (5 adapters, 6 types). See "v1 Recommended harness list" above.
4. ~~Priority on **non-AKS targets**.~~ **Done** — all targets are v1 scope (§3B).

## 6. Next steps (unblocked)
- Turn the strawman into a real `harness.yaml` + `schemas/harness-config-schema.json`.
- Draft `api-spec/sandbox-execution-contract.yaml` (OpenAPI) mirroring §7.
- Build `local-dev/mock-sandbox.py` implementing the §7 routes (incl. SSE).
- Reconcile `IMPLEMENTATION_PLAN.md`: add adapter model, egress default, all-target
  injectors, and the local-only direct-Azure-OpenAI route; align Phase-5 hardened
  images with the v1 harness list.

## 7. Sandbox execution API (source of truth)

This section documents the sandbox execution contract: a **control plane for
short-lived agent sandbox sessions**. The Tethricor exec shim forwards to it; the Phase-1
OpenAPI and `mock-sandbox.py` mirror this contract — see `api-spec/sandbox-execution-contract.yaml`
for the canonical, vendored copy.

Base: chi router; middleware = RequestID, RealIP, Recoverer. Server sets
`ReadTimeout=0`, `WriteTimeout=0` (no global HTTP timeout — required for SSE).

| Method | Route | Purpose | Success |
|---|---|---|---|
| GET | `/healthz` | Liveness | `200 {"status":"ok"}` |
| GET | `/v1/profiles` | List runtime profiles | `200 {"profiles":[...]}` |
| POST | `/v1/sessions` | Create session | `201 Session` |
| GET | `/v1/sessions/{sessionID}` | Get session | `200 Session` |
| DELETE | `/v1/sessions/{sessionID}` | Delete + reclaim | `204` |
| POST | `/v1/sessions/{sessionID}/exec` | Start async exec | `202 ExecRecord` |
| GET | `/v1/sessions/{sessionID}/exec/{execID}/events` | **SSE** exec stream | `text/event-stream` |

Payload schemas:
- **CreateSessionRequest**: `{ profile (required), ttlSeconds?, repoUrl?, metadata? }`.
  `repoUrl` is **reserved / not implemented** (future git-clone). `metadata` = string map.
- **Session**: `{ id, profile, state, createdAt, expiresAt, metadata? }`.
  `state ∈ {pending, running, failed, stopped}`.
- **ExecRequest**: `{ argv (required), cwd?, env?, timeoutSec? }`. **No `stdin`.**
  `argv` is executed directly (no shell unless `argv[0]` is a shell).
- **ExecRecord**: `{ id, sessionId, createdAt, exitCode? }`.
- **ExecEvent** (SSE): `{ type, data?, code? }`, `type ∈ {stdout, stderr, exit, error}`.
  Frames: `data: <json>\n\n`; stream ends on `type=="exit"` (carries `code`).

Execution model: `POST /v1/sessions` (profile) → `POST .../exec` (argv, async `202`)
→ `GET .../exec/{execID}/events` (SSE). Error envelope
`{"error":{"code","message"}}`; mapping `ErrNotFound→404`, `ErrInvalidInput→400`,
`ErrNotSupported→501`, `ErrSessionExpired→410`, else `500`.

### Providers (`AGENT_RUNTIME_PROVIDER`)
| Provider | Behavior | Exec/SSE |
|---|---|---|
| `memory` | Runs commands **in the API host process** (CI/demos). TTL 30m. | ✅ (⚠️ not isolated) |
| `docker` | One container per session (`docker` CLI), `-w /workspace`, keep-alive loop, tracking labels. TTL 45m. | ✅ |
| `aci` | One Azure Container Instances group per session (`DefaultAzureCredential`). TTL 45m. | ❌ **501 not implemented** |

### Profiles (`GET /v1/profiles`)
Current set: **`minimal`, `skills-minimal`, `git`, `node20`, `skill-security-runner`**.
Default images: alpine 3.20 / alpine 3.20 / alpine-git / node:20-alpine /
skill-security-runner. Overridable via `AGENT_RUNTIME_PROFILE_IMAGES` (JSON map).
`skill-security-runner` is reserved for scheduled security-scanning catalog scans.

### Config / auth
- Env: `AGENT_RUNTIME_LISTEN`, `AGENT_RUNTIME_PROVIDER`, `AGENT_RUNTIME_DOCKER_BIN`,
  `AZURE_*`, `AGENT_RUNTIME_ACI_IMAGE`, `AGENT_RUNTIME_ACI_SKU`.
- **Auth is an explicit non-goal**: *"User authentication in this service (caller must
  protect network)."* → The runtime is **network-trusted**; access control lives at the
  network/mesh/gateway layer, not a bearer token on the runtime. (Answers §8 Q5.)
- Non-goals: full K8s orchestration (future), persistent volumes, long-running agents,
  ACI exec/SSE.

### Implications for Tethricor (important)
1. **Mirror this contract** (`api-spec/sandbox-execution-contract.yaml`) as the Phase-1
   sandbox contract; `mock-sandbox.py` implements memory-provider semantics.
2. Exec shim is **session-oriented + async + streaming** (create → exec → SSE), not a
   single blocking POST. The old PROMPTS_LIBRARY "single POST returns stdout" mock is
   **superseded**.
3. **Profile gap**: the runtime only ships `node20` for language toolchains. Our v1
   harnesses need Python (Hermes/OpenHands), Node/TS (Pi/Feynman/OpenCode), Rust
   (Goose). We must **contribute new profiles + hardened images** (or supply them via
   `AGENT_RUNTIME_PROFILE_IMAGES`) — this is a concrete cross-repo dependency.
4. **No `stdin`, no cancel/kill, no workspace file I/O, no persistent volumes.** These
   constrain how harnesses run: no interactive REPL exec; cancellation = session
   delete or `timeoutSec`. Code **IN** = git clone via `repoUrl`; code **OUT** =
   zip of changed files via a runtime artifact download endpoint (see §8 A2 decision).
5. `runtime.profile` in `harness.yaml` must validate against `GET /v1/profiles`.
6. **Line-oriented output**: events are trimmed per-line, empty lines dropped, stdout/
   stderr not strictly interleaved, no binary — fine for logs, not for byte-exact I/O.

## 8. Open questions

### RESOLVED (§7)
- ~~Q1 Full payload schemas~~ — **Answered**: see §7.
- ~~Q3 stdin / cancel~~ — **Answered (as constraints)**: **no `stdin`, no cancel/kill**.
  Cancellation = `timeoutSec` or `DELETE` the session.
- ~~Q5 Runtime auth~~ — **Answered**: runtime has **no auth by design** ("caller must
  protect network"). Access control = network/mesh layer. Sidecar→runtime must be an
  allowlisted internal hop; no bearer token expected at the runtime itself.
- ~~Q6 Profiles~~ — **Answered**: `minimal, skills-minimal, git, node20,
  skill-security-runner`. **Gap identified** → see A1 below.

### Decided (recommendations accepted 2026-07-01)
> Architectural principle behind A4/A7: **the harness deployment target is decoupled
> from the sandbox provider** — harnesses everywhere call one central agent-runtime.

- **A1 — Language profiles/images. DECIDED.** Contribute new profiles upstream to
  the sandbox runtime (`python312`, `rust`, `go`, `polyglot-dev`) so
  they are discoverable via `GET /v1/profiles`; keep `AGENT_RUNTIME_PROFILE_IMAGES`
  as override only. Harness→default-profile map: hermes/openhands→`python312`;
  pi/feynman/opencode→`node20`; goose→`rust` (or `polyglot-dev`). Cross-repo dep.
- **A3 — Session lifecycle. DECIDED.** One runtime session **per harness task**. Shim
  heartbeats/extends TTL during a task and MUST `DELETE` on completion. On `410`
  mid-task: surface error, optionally auto-recreate + resume from last git commit.
- **A4 — ACI exec=501. DECIDED (via decoupling).** Run agent-runtime as a central
  service backed by `docker` (local) / K8s (prod); ACI/Job harnesses call that
  endpoint for exec. Avoid `AGENT_RUNTIME_PROVIDER=aci` until exec lands upstream.
- **A5 — AgentGateway surface. DECIDED (assumption).** Treat as OpenAI-compatible
  (`base_url` + bearer + `model`); one provider-profile indirection so
  gateway↔direct-Azure-OpenAI is a one-line switch. Confirm when gateway team ships.
- **A6 — MCP wiring. DECIDED.** Point harness MCP clients at the gateway MCP endpoint
  (HTTP/SSE), same network trust as LLM calls; `mcp.servers` stay free-form refs
  resolved at injection; `mock-mcp.py` for local.
- **A8 — Image/version governance. DECIDED.** Hardened harness images in enterprise
  ACR; `type`+`version`→image via a platform-maintained manifest (webhook + CLI read
  it), pinned by digest in prod, scan-gated, non-overridable by developers.

### Descoped
- **A7 — `function` / WebJobs target. DESCOPED for v1.** Skip Azure Functions/WebJobs
  entirely for now. Focus v1 on `local`, `aks`, `aci`, `job`. Revisit the central
  hosted-endpoint pattern in a later version.

### Decided — A2 Workspace / code I/O (2026-07-01)
**IN — Git clone.** Clone the developer's repo into the session at create time via the
runtime `repoUrl` field (needs the reserved field implemented upstream). A
**read-only** clone token suffices — the session never pushes back (security plus:
no repo write credentials in the sandbox).

**OUT — zip of changed files, download-ready (revised 2026-07-01; NOT git push/PR).**
The agent produces a **zip of changed files** made available for download. Chosen over
stdout streaming because it is binary-safe, a single clean artifact, and needs no
lossy-channel base64 envelope/chunking.

Delivery:
- **Primary — runtime artifact download endpoint (new upstream capability).** e.g.
  `GET /v1/sessions/{id}/artifacts/{name}` → `application/zip`. Works for BOTH local
  and the prod central-runtime model. This is the real upstream ask.
- **Optional — mounted volume (local/co-located ONLY).** For local docker dev a shared
  volume gives instant pickup. In the prod **central-runtime** model (A4) the session
  runs in the runtime's own infra, so the developer's pod cannot see that volume — the
  download endpoint is still required there. Volume = local fast-path, not general path.

How the zip is built: after the read-only clone, the adapter's **output profile** runs
a final in-session command that computes the changed set via `git diff`/`git status`
and zips only changed/added files to a known path (e.g. `/workspace/.tethricor-out/changes.zip`).
Still no push, no repo write credentials.

Upstream dependency: requires agent-runtime to add a **binary artifact download
endpoint** (departure from its current text/SSE-only surface) and, optionally,
volume-mount support. This is a **second** upstream ask on top of `repoUrl`-clone.

Fallback (if the download endpoint can't land in time): **base64 zip over stdout**
(single artifact, chunked JSONL records over the existing SSE channel) — no new
endpoint, but reintroduces size limits / chunking. Keep as contingency only.

### Security note (reinforces `.cursorrules` #1)
The runtime's `memory` provider runs commands **in the API host process** (no
isolation) and is default in some setups. Tethricor hardened sidecars/shims must target an
**isolated provider** (`docker`/ACI/future K8s), never `memory`, for any non-CI path.
