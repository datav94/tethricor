# Framework Evolution — from "hardened harness CLI" to a plug-and-play harness framework

> **Note:** there is no default sandbox provider — `remote-runtime` is the generic,
> always-installed provider name (`enterprise-runtime` is kept registered as a
> deprecated alias). The technical analysis below (OSS sandbox landscape, license
> findings, architecture) is the source of truth for the provider framework's design.

> Status: **largely implemented** (2026-07-02). Companion to `DESIGN_NOTES.md` and
> `IMPLEMENTATION_PLAN.md`. This document assessed framework maturity and the roadmap;
> v0–v3 (§7) are now built:
> - **v0** — interfaces + registries + conformance kit (`shim/tethricor_runtime/interfaces.py`,
>   `registry.py`, `model.py`, `testing.py`).
> - **v1** — the `tethricor` SDK (`shim/tethricor/`, `Harness` facade + typed results),
>   entry-point discovery, `runtime.provider` in the schema + `init --sandbox`.
> - **v2** — OSS `SandboxProvider` packages `providers/tethricor-sandbox-microsandbox` and
>   `providers/tethricor-sandbox-e2b` (conformance-gated), adapter task-intake, and
>   observability callbacks.
> - **v3** — open harness/provider registries (no closed schema enum),
>   `remote-runtime` as the generic always-available provider name (`enterprise-runtime`
>   kept as a deprecated alias), cloud-neutral `k8s` deployment target with opt-in
>   identity federation, Apache-2.0 licensing.
>
> **Deferred (roadmap):** typed **live** skills/MCP catalog resolution (skills/mcp stay
> free-form for v1 per DESIGN_NOTES A1), the **TypeScript SDK**, and automatic
> provisioning of a harness's own toolchain into its sandbox execution profile (see
> `docs/FRAMEWORK_GUIDE.md` §13). Daytona is **not** adopted (AGPL-3.0 +
> frozen OSS repo — legal/maintenance risk).

## 1. The target: a LangChain-style abstraction for harnesses

LangChain made model usage plug-and-play with three things:

1. **Stable interfaces** (`BaseChatModel`) that all providers implement.
2. **Provider packages** (`langchain-openai` → `AzureChatOpenAI`, etc.) shipped
   independently and discovered via a registry / `init_chat_model(...)` factory.
3. **A library API** you `import` and call — not a CLI you shell out to.

The Tethricor equivalent should let a developer say, roughly:

```python
from tethricor import Harness

# harness, model routing, and sandbox backend are all swappable "providers"
h = Harness(
    harness="hermes",                 # -> HarnessAdapter registry
    model="gpt-4o-standard",          # -> Gateway/model routing
    sandbox="remote-runtime",         # -> SandboxProvider registry (or "e2b", "microsandbox", ...); required, no default
    source="https://github.com/org/repo.git",
)
result = h.run("Refactor the auth module and add tests")
result.changed_files.save("changes.zip")     # code-OUT
for event in result.events:                   # streamed stdout/stderr/exit
    ...
```

…with the **same** guarantee we enforce today: every command is forwarded to an
isolated sandbox over REST; the harness never executes code in its own container; LLM
and MCP traffic go through AgentGateway (`.cursorrules` #1/#2).

There are **three plug-and-play axes**, directly analogous to LangChain's model axis:

| Axis | LangChain analogue | Tethricor today |
|---|---|---|
| **Harness adapter** (accept task, call LLM, invoke tools, execute) | – | `shim/tethricor_runtime/adapters.py` (env-only, 5 adapters) |
| **Sandbox provider** (session / exec / stream / artifact) | – | `shim/tethricor_runtime/runtime_client.py` (one hardcoded REST client) |
| **Model / gateway routing** | `BaseChatModel` providers | `model.routing_profile` (AgentGateway alias, env base URL) |

## 2. Maturity assessment — what already exists

The building blocks of a framework are largely present; they are just wired for a
single-CLI, single-runtime use case rather than exposed as an extensible library.

| Framework capability | Status | Evidence |
|---|---|---|
| Declarative, versioned config contract | **Strong** | `schemas/harness-config-schema.json` (`apiVersion: tethricor.enterprise/v1`), `cli/tethricor_cli/models.py` |
| Harness registry + adapter indirection | **Partial** | `profiles.HARNESSES`, `adapters.ADAPTERS`, `adapter_for()` (feynman→pi) |
| Sandbox contract (session/exec/SSE/artifact) | **Strong** | `api-spec/sandbox-execution-contract.yaml`, `runtime_client.py`, mock parity in `local-dev/` |
| Execution forwarding (no local exec) | **Strong** | `orchestrator.run_task`, enforced/verified in `tests/test_e2e_security.py` |
| Gateway-neutral model routing + key scrub | **Partial** | `adapters.session_env()` scrubs provider keys, sets `OPENAI_BASE_URL` |
| Packaging into hardened images | **Strong** | `docker/Dockerfile.*-hardened`, `image-manifest.yaml`, `manifest.resolve_image()` |
| Multi-target injection | **Strong** | `generators/` (local/aks/aci/job) + `webhook/` mutating admission |
| Typed result + event stream (internal) | **Partial** | `orchestrator.TaskResult`, SSE event dicts |
| Local parity test doubles | **Strong** | `local-dev/mock_sandbox.py`, `mock_mcp.py`, `mock_gateway.py` |
| Test/verification discipline | **Strong** | 42 tests across CLI/webhook/shim/mocks/e2e |

**Bottom line:** we already have a config contract, an adapter registry, a sandbox
*contract*, and enforcement — the skeleton of a framework. What's missing is the
*extensibility surface* (public SDK, provider interfaces, plugin discovery) and the
*depth* of the adapters (real per-harness integration, multiple sandbox backends).

## 3. Gap analysis — what's missing to be plug-and-play

Prioritized from highest leverage to lowest.

1. **No programmatic SDK.** The product is a CLI + an injected sidecar. There is no
   importable `tethricor` package with a `Harness` facade. LangChain's whole value is
   "import and call." → *Build a stable Python library (`tethricor`/`tethricor-sdk`) wrapping the
   shim orchestrator; TS SDK later.*
2. **No formal provider interfaces + registries for all three axes.** Adapters and the
   runtime client are concrete, not abstract. → *Introduce `HarnessAdapter`,
   `SandboxProvider`, and `ModelRouter` abstract base classes, each with a registry.*
3. **No plugin/discovery mechanism.** Adding a harness or sandbox means editing core.
   LangChain uses separate `pip`-installable provider packages. → *Register providers
   via Python **entry points** (e.g. groups `tethricor.harnesses`, `tethricor.sandboxes`) so a
   third party ships `tethricor-sandbox-e2b` without touching core.*
4. **Adapters are shallow.** `adapters.py` only sets env vars; it does not actually
   drive each harness's real integration surface (Pi JSONL/RPC, OpenHands remote
   runtime, Goose MCP, etc.) or implement the per-harness **output profile**. → *Flesh
   out the "four concerns" (task intake, LLM call, tool/MCP invocation, execution) per
   adapter.*
5. **Single hardcoded sandbox.** Only the enterprise agent-runtime is supported. → *Add
   sandbox providers behind the `SandboxProvider` interface (§4/§5).*
6. **Untyped capability model.** `skills`/`mcp` are free-form strings. → *Type them and
   resolve against a live catalog (already flagged in DESIGN_NOTES A1).*
7. **No provider conformance suite.** A framework needs a shared test kit every provider
   must pass so third parties can self-certify. → *Ship `tethricor.testing` with contract
   tests (the mock already exercises the full contract — promote it to a reusable kit).*
8. **No public, typed result/event/session API.** Internal `TaskResult` + event dicts
   are not a documented, stable surface. → *Define typed `Event`, `TaskResult`,
   `SandboxSession` in the SDK.*
9. **Static image manifest & no code-API stability contract.** `image-manifest.yaml`
   is a file, not a service; the config `apiVersion` is versioned but the code API is
   not. → *Version the SDK (semver) and consider a manifest service.*
10. **No in-framework observability hooks & single language.** No callback/tracing
    interface; Python-only. → *Add callback hooks (delegating to AgentGateway/OTel) and
    a TS SDK later.*

## 4. Target architecture — three pluggable axes

```
                         ┌──────────────────────────────┐
   developer code / CLI  │            tethricor SDK          │
        Harness(...)     │   facade + typed results     │
                         └──────────────┬───────────────┘
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
     HarnessAdapter registry    SandboxProvider registry     ModelRouter registry
   (hermes, pi, openhands,     (remote-runtime [no default],    (gateway alias;
    goose, opencode, …)         e2b, microsandbox, …)            direct-azure local)
             │                   gvisor/kata on k8s …)                │
             └──────────── all conform to a stable contract ─────────┘
                         + a shared conformance test kit (tethricor.testing)
```

- **`SandboxProvider`** is just the interface our `RuntimeClient` already implements:
  `create_session(profile, repo_url, ttl) → exec(argv) → stream_events() →
  download_artifact() → delete()`. Making it an ABC lets us drop in OSS backends (§5).
- **`HarnessAdapter`** maps a harness onto `{gateway, mcp, sandbox}` and owns the four
  concerns + the output profile.
- **`ModelRouter`** resolves `model.routing_profile` to an OpenAI-compatible endpoint
  (AgentGateway in prod; the local escape hatch in dev).
- **Discovery** via entry points so providers are independently installable packages.

Crucially, this is *additive*: today's shim orchestrator becomes the reference
implementation of `HarnessAdapter` + `SandboxProvider`, wrapped by the SDK facade.

## 5. Open-source sandbox environments — adopt, don't build

Per the request, we should **integrate existing OSS sandboxes** rather than develop our
own. All of these are consumed **behind the `SandboxProvider` interface over their REST
control planes**, so `.cursorrules` #1 still holds — execution is forwarded to an
isolated backend, never run in the harness container. The enterprise agent-runtime
remains the **default** provider; these are alternatives selected by config/flag.

### 5.1 Landscape (2026)

| Provider | License | Isolation | Self-host | Azure/AKS fit | Notes |
|---|---|---|---|---|---|
| **Enterprise agent-runtime** (ours) | internal | provider-configurable | yes (owned) | native | Default; the contract we already target. |
| **E2B** (`e2b-dev/E2B`) | Apache-2.0 | Firecracker microVM (~150 ms) | yes, but heavy (Terraform + Nomad/Consul) | **weak** — infra officially GCP/AWS; **Azure not supported**, no nested-virt on AKS | Best DX + strongest isolation; ephemeral, no GPU. Great for **dev/managed**, poor for on-prem Azure self-host. |
| **Daytona** (`daytonaio/daytona`) | **AGPL-3.0** | OCI/Docker (+ Kata/Firecracker/VM classes) (<90 ms) | yes (Docker Compose; customer-managed compute in your cloud) | **good** (BYOC) | Persistent workspaces + snapshots + GPU + clean REST/SDK. **Caveat:** OSS repo *unmaintained since Jun 2026* (core went private); AGPL is an enterprise-licensing review item. |
| **microsandbox** (`superradcompany/microsandbox`) | Apache-2.0 | libkrun/KVM microVM (<100 ms) | yes, local-first, rootless, embeddable | **good on KVM nodes**; libkrun-via-`crun` runs as a normal pod | Real microVM isolation with no server; ships an **MCP server** + agent skills; SDKs Py/TS/Rust/Go. **Beta (pre-1.0)** — breaking changes. |
| **Beam / beta9** | AGPL-3.0 | gVisor/runc | yes (Helm) | good | GPU, built-in orchestration. AGPL. |
| **Arrakis** | AGPL-3.0 | Cloud Hypervisor + snapshot/restore | yes | medium | Snapshot-heavy; younger. |
| **Modal Sandboxes** | proprietary | gVisor | **no** (managed only) | **no BYOC/on-prem** | GPU-in-sandbox leader, but **disqualified** for Azure/on-prem compliance. Reference only. |
| **gVisor (runsc)** | Apache-2.0 | user-space syscall filter | yes | **native on AKS** (RuntimeClass) | Not a sandbox *service* — a runtime for our own runtime pods (defense-in-depth). |
| **Kata Containers** | Apache-2.0 | lightweight VM per pod | yes | **native on AKS** (RuntimeClass / confidential containers) | Same: hardens the pods running the runtime/sandbox. |

### 5.2 Recommendation

1. **Keep the enterprise agent-runtime as the default provider.** It already satisfies
   the contract and the security posture. Everything below is opt-in.
2. **Adopt as pluggable `SandboxProvider` packages (adopt, don't build):**
   - **`microsandbox` — primary OSS pick for real local isolation.** Apache-2.0,
     rootless, MCP-native, KVM microVMs. Use it to **replace the local mock** so
     `--target local` gets *genuine* microVM isolation, and as an AKS option on
     KVM-capable node pools via libkrun+`crun` (runs like a normal pod). Pin a version
     (beta) and gate behind a conformance run.
   - **`e2b` — developer/managed pick.** Apache-2.0, best DX, strongest isolation. Use
     for developer laptops / non-Azure CI where its hosted or GCP/AWS self-host is fine.
     Flag the **Azure self-host gap** — not for on-prem Azure prod.
   - **`daytona` — optional, for persistent/GPU workspaces.** Only after an **AGPL
     legal review** and given the *unmaintained OSS repo* risk; consume via its REST API
     as customer-managed compute.
3. **Harden the pods that run any in-cluster runtime/sandbox** with **gVisor or Kata
   `RuntimeClass`** on AKS — orthogonal defense-in-depth, not a provider.
4. **Do not adopt Modal** for the enterprise path (no BYOC/on-prem). Keep as a comparison.

### 5.3 `.cursorrules` alignment

- **#1 (no local exec):** every provider is reached over REST/WS and runs code in an
  isolated backend; the harness container still never executes task code. OSS providers
  are *additional isolated backends*, not a local-exec escape hatch.
- **#2 (gateway):** unaffected — LLM/MCP routing stays on AgentGateway regardless of
  sandbox provider.
- **#3 (sidecar) / #4 (config contract):** unchanged; `runtime.provider` becomes a new,
  platform-validated field (see §6) while images/security stay platform-locked.

## 6. Config surface changes (backward-compatible)

Add an optional, platform-validated provider selector; default preserves today's
behavior.

```yaml
runtime:
  provider: remote-runtime   # required, no default: remote-runtime | e2b | microsandbox | your own
  profile: python312
  timeout_seconds: 600
```

Rules: `provider` is validated against the installed `SandboxProvider` registry; the
memory/insecure providers remain refused for non-local targets (already enforced by the
webhook); provider **credentials/endpoints are platform-injected**, never in
`harness.yaml`.

## 7. Phased roadmap

**Framework v0 — extract the interfaces (no behavior change)**
- Promote `RuntimeClient` to a `SandboxProvider` ABC + `enterprise-runtime` impl.
- Formalize `HarnessAdapter` / `ModelRouter` ABCs + registries.
- Extract the mock's contract checks into a reusable `tethricor.testing` conformance kit.

**Framework v1 — the SDK + plugin discovery**
- Ship an importable `tethricor` package with the `Harness` facade, typed `Event`/`TaskResult`.
- Entry-point discovery (`tethricor.harnesses`, `tethricor.sandboxes`, `tethricor.models`).
- `runtime.provider` in the schema + CLI `--sandbox` flag.

**Framework v2 — real depth**
- Adopt `microsandbox` and `e2b` provider packages (conformance-gated); swap the local
  mock for microsandbox behind a flag.
- Flesh out per-harness adapters (Pi RPC, OpenHands remote runtime, Goose MCP) + output
  profiles.
- Typed skills/MCP catalog resolution; observability callbacks (OTel/LangSmith-style);
  TS SDK.

## 8. Risks & open items

- **Licensing:** Daytona/Beam/Arrakis are **AGPL-3.0** — requires legal review before
  distribution/self-host. E2B/microsandbox/gVisor/Kata are Apache-2.0 (clean).
- **E2B on Azure:** self-host infra does not officially target Azure — do not promise
  on-prem Azure E2B; use managed/GCP/AWS or another provider there.
- **microsandbox maturity:** pre-1.0 beta; libkrun `main` is a pre-stable 1.0 API — pin
  versions and gate on the conformance kit.
- **Daytona OSS:** core development moved private (Jun 2026); the public repo is frozen —
  treat as "consume the frozen AGPL build or the API," not "track upstream."
- **Scope creep vs. thin-abstraction charter:** the SDK/plugin work is genuinely new
  surface area; sequence it behind the v1 deliverables already shipped, and keep the
  enterprise runtime the default so nothing regresses.
