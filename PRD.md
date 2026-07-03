# Product Requirements Document (PRD)

## Project: Universal Harness Abstraction Layer (Tethricor - Harness as a Service)

### 1. Overview

The Universal Harness Abstraction Layer is an open-source developer platform capability
that allows developers to integrate various AI Agent Harnesses (e.g., OpenHands, Pi,
Goose) into their applications via a standardized "plug-and-play" interface. It
abstracts the execution environment, enforcing security, centralized MCP (Model Context
Protocol) tool serving, and LLM API gateway routing — against whatever OpenAI-compatible
gateway, MCP server, and sandbox execution backend the adopting organization already
runs, not a specific vendor's stack.

### 2. Objectives

- **Decouple App Logic from Agent Execution:** Developers write standard tasks; the platform injects the requested execution harness.
- **Enforce Security via Architecture:** Prevent developers from bypassing security controls by using Kubernetes Mutating Webhooks and sandboxed execution environments, without assuming a specific isolation technology.
- **Seamless Developer Experience:** Provide an interactive CLI/UI to generate `harness.yaml` configurations that work interchangeably between local Docker environments and Kubernetes (any cluster — AKS, GKE, EKS, self-managed), with Azure-specific opt-in targets (Container Instances, Container Apps Jobs) for organizations already on Azure.
- **Plug-and-play framework (evolution):** Beyond the CLI + hardened images, expose a lean, importable framework where **harnesses, sandbox backends, and model routing are swappable providers** behind stable interfaces — the LangChain-for-harnesses model. Third parties add a provider as a separate installable package (via entry-point discovery) without modifying core. See `docs/agent_context/FRAMEWORK_EVOLUTION.md` for the architecture, gap analysis, and phased roadmap.

### 3. Core Features

- **Interactive Harness Configurator:** CLI/UI tool that generates sidecar configurations based on requested harnesses and skills.
- **Kubernetes Mutating Webhook:** Automatically injects the correct hardened harness container as a sidecar into the developer's pod upon deployment to any Kubernetes cluster.
- **Sandbox Forcing:** Hardened base images that override open-source execution tools (like local bash) to force remote execution inside a pluggable sandbox runtime — no isolation backend is bundled or assumed by default.
- **Gateway-neutral LLM routing:** Built-in routing for all LLM calls to pass through an OpenAI-compatible gateway (your own, or a self-hosted proxy such as LiteLLM, Portkey, or Kong AI Gateway) for token tracking, PII scrubbing, and cost management.
- **Pluggable Sandbox Providers:** A `SandboxProvider` abstraction (the session/exec/SSE/artifact contract) with no default backend — `remote-runtime` is a generic REST/SSE client you point at whatever you operate, and adoption of **existing** open-source sandboxes (e.g. microsandbox, E2B) as opt-in backends — never building our own sandbox. All providers are reached over REST/WS; execution is never local (`.cursorrules` #1).
- **Programmatic SDK + provider registries:** An importable `tethricor` package with a `Harness` facade and typed results/events, plus entry-point registries for the three provider axes (harness / sandbox / model). CLI remains a thin wrapper over the same SDK.

### 3a. Engineering Principles (non-negotiable)

All framework work must satisfy these (mirrored in `.cursorrules` #5–#8):

1. **Tested requirements:** every requirement in `FRAMEWORK_EVOLUTION.md` ships with automated tests, including a reusable **provider conformance kit**.
2. **Lean, no duplication:** reuse existing modules; one home for shared logic; smallest change that works; no speculative abstractions.
3. **Modern, permissively-licensed dependencies only:** current, well-maintained components; AGPL and other copyleft licenses are excluded by default (this is an Apache-2.0 project) unless explicitly approved after review; justify each addition.
4. **Local E2E + production-ready:** runnable end-to-end locally (mocks / `docker-compose.test.yaml`) and deployable to `local`/`k8s`/`aks`/`aci`/`job` without breaking existing behavior; no provider or cloud is hardcoded as the default.

### 4. Out of Scope (For Now)

- Cross-harness memory state resumption (transferring half-completed tasks from OpenHands to Goose).
- Normalizing frontend UI for different agent paradigms (chat vs. autonomous workspace).
- Automatic provisioning of a chosen harness's own toolchain into its sandbox execution
  image/profile — today the operator is responsible for ensuring the `runtime.profile`
  a harness runs under actually has that harness installed.
- Fabricated AWS/GCP equivalents of the Azure-specific `aci`/`job` targets; the
  cloud-neutral path is `k8s`.

### 5. Security Constraints & Known Limitations

Please see `SECURITY_RISKS.md` for a detailed breakdown of egress constraints and mitigation strategies.
