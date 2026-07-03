# Tethricor

A **thin developer-facing abstraction** over your organization's existing AI platform:
an OpenAI-compatible **LLM gateway**, an **MCP-compatible tool/skills server**, your
**identity provider**, and — optionally — a **remote sandbox execution service** you
already operate. Tethricor lets a developer declare *intent* in a `harness.yaml`, and
the platform enforces security: it injects a hardened agent **harness sidecar** next to
the app, routes all LLM/MCP traffic through your gateway, and forwards **all** code
execution to a pluggable sandbox backend — the harness never runs code locally.

Harnesses, sandbox backends, and model routing are swappable **providers**
(LangChain-style): built-in adapters cover Hermes/Pi/Feynman/OpenHands/Goose/OpenCode,
and third parties add a harness, sandbox, or model router as a separate installable
package via Python entry points — no core edits.

> Tethricor *consumes/integrates* the platform components above; it only *builds* the
> config contract, the CLI, the hardened images + exec shim, and the injectors. See
> `docs/agent_context/DESIGN_NOTES.md` §1 and `ARCHITECTURE.md`.

**New here?** [`docs/FRAMEWORK_GUIDE.md`](docs/FRAMEWORK_GUIDE.md) is the complete,
diagram-driven explanation of how everything fits together — architecture, the
three-axis plugin model, the task lifecycle, every deployment target, and the
security model. This README stays focused on getting something running quickly.

Licensed under [Apache-2.0](LICENSE).

## Repository layout

| Path | What it is |
|---|---|
| `schemas/harness-config-schema.json` | JSON Schema contract for `harness.yaml` (developer declares intent; platform-managed fields are rejected). `harness.type`/`runtime.provider` are registry-validated at run time, not closed enums — custom adapters/providers plug in without a schema change. |
| `api-spec/sandbox-execution-contract.yaml` | The sandbox execution OpenAPI contract + the Tethricor artifact-download addition (code OUT). |
| `examples/harness.*.yaml` | Canonical `harness.yaml` per built-in harness type. |
| `cli/` | The `tethricor` CLI (`init` / `validate` / `local-dev`) + per-target generators (`local`, `k8s`, `aks`, and the Azure-specific `aci`/`job` under `generators/azure/`). |
| `local-dev/` | Local parity doubles: `mock_sandbox.py` (a sandbox execution service double), `mock_gateway.py` (an LLM gateway double), and `mock_mcp.py`. |
| `webhook/` | Kubernetes mutating admission webhook that injects the hardened sidecar (works on AKS, GKE, EKS, kind, minikube — pure `AdmissionReview`, no cloud-specific dependencies). |
| `shim/` | The execution shim (`tethricor_runtime`) **and** the importable `tethricor` SDK (`Harness` facade + typed results + entry-point discovery). |
| `providers/` | Pluggable `SandboxProvider` packages: `tethricor-sandbox-microsandbox`, `tethricor-sandbox-e2b` (conformance-gated, entry-point discovered). |
| `docker/` | Hardened Dockerfiles for the 5 harness adapters. |
| `tests/` | Cross-cutting end-to-end + security verification. |
| `docs/agent_context/` | `PROJECT_CONTEXT`, `IMPLEMENTATION_PLAN`, `DESIGN_NOTES`, `PROMPTS_LIBRARY`, `FRAMEWORK_EVOLUTION` — this project's build history (see the banner in each for context on what's changed since). |

## v1 scope

- **Harnesses** (`harness.type`): built-in adapters for `hermes, pi, feynman, openhands,
  goose, opencode` (5 adapters, 6 types — Feynman rides the Pi adapter). Not a closed
  set: register your own via `tethricor_runtime.adapters.register_harness` or the
  `tethricor.harnesses` entry point.
- **Sandbox providers** (`runtime.provider`): no default — choose explicitly.
  `remote-runtime` (generic REST/SSE client, always available) works against any
  compatible service, including the bundled `mock_sandbox.py` for local dev.
  `microsandbox`/`e2b` are opt-in real-isolation packages; add your own the same way.
- **Deployment targets** (`--target`): cloud-neutral `local` and `k8s`; `aks` (Kubernetes
  + Azure Workload Identity, back-compat name); `aci`/`job` (explicitly Azure-specific,
  opt-in — no fabricated AWS/GCP equivalents).
- **Code IN:** git clone into the sandbox session. **Code OUT:** zip of changed files
  via the sandbox's artifact download endpoint.
- **Security invariants:** execution always forwarded to the sandbox provider; egress
  default-deny except `{gateway, sandbox runtime}`; read-only rootfs; non-root.

## Quickstart (local)

```bash
# 1. Install the CLI + core (editable) and the local mocks' deps
pip install -e cli -e shim
pip install -r local-dev/requirements.txt

# 2. Scaffold a validated harness.yaml. --sandbox is required -- there's no default;
#    remote-runtime is the always-available generic REST client (used here against the
#    bundled mock-sandbox local double; see providers/ for real-isolation options).
tethricor init --yes \
  --type hermes --version 0.17.0 \
  --repo-url https://github.com/your-org/your-repo.git \
  --sandbox remote-runtime

# 3. Validate it against the schema contract
tethricor validate harness.yaml

# 4. Generate the local docker-compose bundle (app + hardened sidecar + mocks)
tethricor local-dev harness.yaml --target local --out-dir tethricor-out

# 5. Bring it up
docker compose -f tethricor-out/local/docker-compose.yaml up --build
```

Generate deployment artifacts for other targets by changing `--target`:

```bash
tethricor local-dev harness.yaml --target k8s   --out-dir tethricor-out  # cloud-neutral: ConfigMap + labeled Deployment + egress NetworkPolicy
tethricor local-dev harness.yaml --target aks   --out-dir tethricor-out  # same, + Azure Workload Identity federation
tethricor local-dev harness.yaml --target aci   --out-dir tethricor-out  # Azure Container Instances (Azure-specific)
tethricor local-dev harness.yaml --target job   --out-dir tethricor-out  # Azure Container Apps Job (Azure-specific)
```

For `k8s`/`aks`, the sidecar is injected at admission time by the mutating webhook
(`webhook/deploy/webhook.yaml`), not by the CLI.

A harness type with no `image-manifest.yaml` entry (e.g. a custom-registered adapter)
needs `--image <your-hardened-image>` passed to `local-dev` explicitly.

## Using the `tethricor` SDK (plug-and-play)

Beyond the CLI, Tethricor ships an importable framework. Harness, model routing, and sandbox
backend are swappable providers (LangChain-style). `sandbox` is required — there's no default:

```python
from tethricor import Harness

h = Harness(
    harness="hermes",                 # HarnessAdapter registry
    model="gpt-4o-standard",          # ModelRouter (your LLM gateway)
    sandbox="remote-runtime",         # SandboxProvider registry ("microsandbox", "e2b", …)
    source="https://github.com/org/repo.git",
)
result = h.run("Refactor the auth module and add tests")  # or an explicit argv list
print(result.ok, result.exit_code)
for event in result.events:           # typed stdout/stderr/exit
    ...
```

Third-party **sandbox providers** are separate pip-installable packages discovered via
the `tethricor.sandboxes` entry point (no core edits):

```bash
pip install -e shim ./providers/tethricor-sandbox-microsandbox   # real microVM isolation
tethricor init --sandbox microsandbox ...                        # validated against the registry
```

Any provider must pass the shared conformance kit
(`tethricor_runtime.testing.assert_sandbox_conformance`). See `docs/agent_context/FRAMEWORK_EVOLUTION.md`.

**Bringing your own harness:** register a `HarnessAdapter` (either directly via
`tethricor_runtime.adapters.register_harness`, or as a `tethricor.harnesses` entry
point in your own package) and it's immediately usable by name through both the SDK and
the CLI — no schema change needed. What the adapter gives you is task launch + env
hardening (how to turn a task string into your harness's CLI invocation, and how its
LLM/MCP/provider-key env gets set); it does *not* normalize the harness's own agent
loop or prompting, and your `runtime.profile`/sandbox image still needs your harness's
own toolchain installed for it to actually run — Tethricor doesn't provision that for
you automatically yet (see `docs/FRAMEWORK_GUIDE.md` §13 for the detail).

### Local-only: run without a gateway (direct Azure OpenAI)

If you don't have an LLM gateway set up yet, an isolated **local-dev utility**
(`tethricor.direct_azure`) can point the SDK straight at Azure OpenAI. It is opt-in and
does not change the default gateway routing:

```python
from tethricor import Harness, use_direct_azure_openai

use_direct_azure_openai(
    endpoint="https://<resource>.openai.azure.com",
    deployment="gpt-4o",
    api_key="...",            # or set AZURE_OPENAI_API_KEY
)
Harness("hermes", sandbox="remote-runtime", source="https://github.com/org/repo.git").run("do the thing")
```

> **Security:** this bypasses the LLM gateway and is for **local development only**
> (`.cursorrules` #2). The API key is never read from `harness.yaml`, and the CLI/webhook
> still strip `model.direct_azure_openai` for every non-`local` target, so it cannot leak
> into `k8s`/`aks`/`aci`/`job` deployments. Call `tethricor.direct_azure.disable()` to
> revert to gateway routing.

## Running the tests

```bash
python -m pytest cli/tests webhook/test_app.py local-dev shim/tests tests providers -q
```

The suite covers the schema/CLI, the mock sandbox runtime (live SSE + artifact
round-trip), the webhook admission logic, the shim (full clone→exec→zip→delete against
a live server), and the cross-cutting security invariants (egress default-deny, no
in-container execution, `memory`-provider refusal, escape-hatch stripping).

## Status

All build phases (1–9) in `docs/agent_context/IMPLEMENTATION_PLAN.md` are implemented and
verified (84 tests). This includes the framework evolution: the `tethricor` SDK + plugin
discovery (v1) and OSS `SandboxProvider` packages + adapter depth + observability
callbacks (v2). Two v2 items are **deliberately deferred** to the roadmap: a typed
**live** skills/MCP catalog and the **TypeScript SDK**.

No default cloud and no default sandbox backend are assumed anywhere — pick a
`runtime.provider` explicitly, use the cloud-neutral `k8s` target or the Azure-specific
`aks`/`aci`/`job` ones, and register custom harnesses/providers via the open registries.
The one known gap worth knowing up front: a chosen harness's own toolchain must already
be present wherever its sandbox session runs — Tethricor doesn't provision that for you
yet (see `docs/FRAMEWORK_GUIDE.md` §13).
