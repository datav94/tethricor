# Project Context: Tethricor

> **Note:** this document describes Tethricor's current architecture — no default LLM
> gateway, no default sandbox provider, cloud-neutral `k8s` deployment target, open
> harness/provider registries.

## What is Tethricor?
Just as LiteLLM standardized the fractured model provider landscape, this platform standardizes the **Agent Harness runtime**. We provide developers with an interface to easily attach any open-source AI harness (e.g., OpenHands, Pi, Goose) to their applications via a standardized sidecar architecture, without rewriting their application logic.

## The Architecture
We use the **Kubernetes Sidecar Pattern**:
1. **Client App Container:** The developer's application. It sends a task (e.g., `{"task": "analyze data"}`) to `localhost`.
2. **Harness Sidecar Container:** An injected open-source harness that receives the task.
3. **LLM Gateway:** The harness routes its LLM requests out to a configured, OpenAI-compatible LLM gateway (your own, or a self-hosted proxy like LiteLLM/Portkey/Kong AI Gateway) for routing, billing, and PII scrubbing. No vendor is hardcoded.
4. **MCP Server:** The harness fetches tools/skills from an MCP server reached through the same gateway.
5. **Sandbox Runtime:** When the harness tries to run code/commands, a hardened shim intercepts the execution and forwards it via WebSockets/REST to a pluggable `SandboxProvider` — a service you self-host or operate, or an opt-in OSS isolation package.

## Deployment Lifecycle
- **Local:** Developers use a CLI to generate a `harness.yaml` and a `docker-compose.yaml` to test the sidecar and app together locally.
- **Cloud (any Kubernetes cluster):** Developers deploy their app to Kubernetes (AKS, GKE, EKS, self-managed — the webhook is pure `AdmissionReview`, no cloud dependency). A Mutating Webhook reads the `harness.yaml`, strips insecure configs, and auto-injects the hardened Harness Sidecar into the developer's pod. Cloud identity federation (e.g. Azure Workload Identity) is opt-in via the `k8s`/`aks` generator's `identity_mode`, not assumed.
- **Azure-specific (opt-in):** `aci`/`job` targets generate Azure Container Instances / Container Apps Jobs artifacts directly, for organizations already on Azure. There is no fabricated AWS/GCP equivalent — use `k8s` for a cloud-neutral deployment.

## Framework direction (provider abstractions)
Tethricor is a **plug-and-play framework** with three swappable provider axes behind
stable interfaces (see `FRAMEWORK_EVOLUTION.md`):

1. **HarnessAdapter** — maps a harness (hermes/pi/openhands/goose/opencode, or a
   custom-registered one) onto `{gateway, mcp, sandbox}` and owns task intake, LLM call,
   tool/MCP invocation, and the output profile. (Today: `shim/tethricor_runtime/adapters.py`.)
2. **SandboxProvider** — the existing session→exec→SSE→artifact→delete contract. There
   is **no default** — `remote-runtime` (a generic REST/SSE client) works against any
   compatible service; approved open-source sandboxes (microsandbox, E2B, …) are opt-in
   backends, always reached over REST/WS (never local execution). (Today:
   `shim/tethricor_runtime/runtime_client.py`.)
3. **ModelRouter** — resolves `model.routing_profile` to an OpenAI-compatible endpoint
   (your configured gateway in prod; local escape hatch in dev).

Providers are discovered via entry points so a new harness/sandbox ships as a separate
installable package without editing core. The work is **additive and backward-compatible**:
current behavior is the reference implementation of these interfaces. Engineering
constraints (tests, no bloat, modern permissively-licensed deps, local-E2E + prod-ready)
are in `.cursorrules` #5–#8 and `PRD.md` §3a.
