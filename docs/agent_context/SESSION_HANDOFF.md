# Session Handoff — Tethricor

> **Purpose.** A single, self-contained brief so a new agent/developer can continue this
> work cold. Read this first, then the companion docs it points to. Last updated:
> **2026-07-03**. State: **Phases 1–9 implemented and verified (84 tests passing)**;
> two Phase-9 items deliberately deferred (see §7). Open harness/provider registries,
> no default sandbox provider, cloud-neutral `k8s` deployment target, and Apache-2.0
> licensing are all current, standing design decisions — see §6.

---

## 1. What Tethricor is (in one paragraph)

Tethricor is a **thin developer-facing abstraction** on top of your organization's own
AI platform. It is **not** a new platform, and it is **not tied to any one vendor's
stack** — it consumes whatever OpenAI-compatible **LLM gateway** you already run (LLM +
MCP egress), your own **identity provider**, and, optionally, a **remote sandbox
execution service** you self-host or operate. Tethricor lets a developer declare
*intent* in a `harness.yaml`; the platform then packages a hardened agent **harness**
(Hermes/Pi/OpenHands/Goose/opencode, or your own registered adapter), injects it as a
**sidecar**, routes all LLM/MCP traffic through your gateway, and **forwards every code
execution to the configured sandbox provider** — the harness never executes task code in
its own container.

On top of that CLI/sidecar product, Tethricor also grew into a **plug-and-play framework**
(LangChain-style): an importable `tethricor` SDK with three swappable provider axes
(**harness adapter**, **sandbox provider**, **model router**), each discoverable via
Python entry points and gated by a shared conformance kit. None of the three axes has a
"blessed" default — every axis is either chosen explicitly (`--sandbox`, `--type`,
`TETHRICOR_MODEL_ROUTER`) or, for the harness/sandbox axes, dynamically validated against
whatever's installed/registered rather than a closed schema enum.

**Non-negotiable invariants (from `.cursorrules`):**
1. **No local execution.** Task code/bash is always forwarded to an isolated sandbox
   backend over REST; never run in the harness container.
2. **Gateway-only.** All LLM/MCP calls go through your configured LLM gateway (any
   OpenAI-compatible endpoint); no hardcoded provider SDK endpoints (a
   `direct_azure_openai` escape hatch exists for **local dev only** and is stripped for
   non-local targets).
3. **Sidecar pattern** for injection.
4. **Config as contract.** `harness.yaml` is validated against a JSON Schema; developers
   declare intent, platform-managed fields are rejected. `harness.type` and
   `runtime.provider` are registry-validated at run time, not closed enums.
5–8. **Engineering rules:** every requirement tested; no code bloat/duplication; only
   modern/well-maintained/permissively-licensed deps (Apache-2.0 project — AGPL excluded
   by default); must be testable locally E2E **and** production-ready.

---

## 2. Current status at a glance

| Area | State |
|---|---|
| Phases 1–6 (contract, CLI, mocks, injection, hardened images + shim, E2E/security) | **Done** |
| Phase 7 (Framework v0 — interfaces + registries + conformance kit) | **Done** |
| Phase 8 (Framework v1 — `tethricor` SDK + entry-point discovery + `runtime.provider`) | **Done** |
| Phase 9 (Framework v2 — OSS sandbox providers + adapter depth + observability) | **Done, 2 items deferred** |
| Open harness/provider registries, no default sandbox provider, `k8s` target, Apache-2.0 | **Done** — see §6 |
| Test suite | **84 passing** (`python -m pytest cli/tests webhook/test_app.py local-dev shim/tests tests providers -q`) |
| Deferred (roadmap) | Typed **live** skills/MCP catalog resolution; **TypeScript SDK**; automatic harness-toolchain provisioning into sandbox profiles (known gap, see `docs/FRAMEWORK_GUIDE.md` §13) |
| Upstream deps (Phase 0) | 3 items owned by whichever team operates your sandbox runtime backend (see §8) |

Authoritative living docs (read in this order):
- `docs/FRAMEWORK_GUIDE.md` — the complete, diagram-driven architecture reference.
- `docs/agent_context/PROJECT_CONTEXT.md` — architecture + build-vs-consume split.
- `docs/agent_context/IMPLEMENTATION_PLAN.md` — phases (all checked off through 9) + invariants.
- `docs/agent_context/DESIGN_NOTES.md` — every decision + open questions (A1–A8) — historical design-exploration notes.
- `docs/agent_context/FRAMEWORK_EVOLUTION.md` — framework maturity, OSS sandbox landscape, roadmap v0–v3.
- `docs/TESTING.md` — how to test (tool suite, full local stack, real harness later).
- `PRD.md` — product requirements incl. §3a engineering principles.

---

## 3. Repository map (what lives where)

```
tethricor/
├─ .cursorrules                         # the 8 hard rules (read this)
├─ LICENSE, NOTICE                      # Apache-2.0
├─ PRD.md                               # product requirements + engineering principles
├─ README.md                            # quickstart (CLI + SDK + providers)
├─ docs/FRAMEWORK_GUIDE.md              # complete diagram-driven architecture reference
├─ docker-compose.test.yaml             # self-contained offline E2E stack (code IN/OUT)
├─ schemas/harness-config-schema.json   # THE contract for harness.yaml (additionalProperties:false;
│                                       #   harness.type/runtime.provider are open, registry-validated)
├─ api-spec/sandbox-execution-contract.yaml  # the sandbox execution OpenAPI + artifact-download addition
├─ examples/harness.*.yaml              # canonical config per built-in harness type
│
├─ cli/tethricor_cli/                # the `tethricor` CLI
│  ├─ cli.py                            # init / validate / local-dev (+ required --sandbox, --image override)
│  ├─ models.py                         # Pydantic models (strict); harness.type is `str`, not a closed Literal
│  ├─ schema.py, profiles.py, manifest.py, security.py
│  ├─ generators/                       # local.py=compose.py, k8s.py (cloud-neutral), aks.py (k8s+azure identity, thin wrapper)
│  │  └─ azure/                         # aci.py, job.py — explicitly Azure-specific, opt-in
│  └─ data/image-manifest.yaml          # harness type+version -> hardened image (placeholder registry: replace with your own)
│
├─ shim/                                # ONE distribution (tethricor) shipping TWO packages:
│  ├─ tethricor_runtime/                        # the runtime shim (sidecar CMD) + framework internals
│  │  ├─ interfaces.py                  # ABCs: SandboxProvider, HarnessAdapter, ModelRouter (+ exceptions)
│  │  ├─ runtime_client.py              # reference SandboxProvider (generic REST/SSE client, any compatible service)
│  │  ├─ adapters.py                    # 5 built-in harness adapters + register_harness() for custom ones
│  │  ├─ model.py                       # ModelRouter registry (GatewayRouter default; TETHRICOR_MODEL_ROUTER)
│  │  ├─ registry.py                    # SandboxProvider registry: remote-runtime (canonical), enterprise-runtime (deprecated alias)
│  │  ├─ orchestrator.py                # run_task: create→exec→stream→artifact→delete (+ callbacks)
│  │  ├─ observability.py               # Callbacks lifecycle hooks (OTel/LangSmith-style)
│  │  ├─ config.py                      # Settings.from_env + endpoint default constants
│  │  ├─ testing.py                     # conformance kit + reusable test-double exec/zip helpers
│  │  └─ __main__.py                    # thin delegator to tethricor.cli:main (single code path)
│  └─ tethricor/                             # the public SDK facade
│     ├─ __init__.py                    # exports Harness/Event/TaskResult/SandboxSession/Callbacks; runs discovery
│     ├─ harness.py                     # Harness facade — `sandbox` is a REQUIRED kwarg (no default)
│     ├─ types.py                       # typed Event / TaskResult / SandboxSession
│     ├─ discovery.py                   # entry-point loader (tethricor.sandboxes/harnesses/models)
│     └─ cli.py                         # task-runner entrypoint (posture + run)
│
├─ providers/                           # pluggable SandboxProvider packages (adopt OSS, don't build)
│  ├─ tethricor-sandbox-microsandbox/        # real-isolation OSS pick (libkrun/KVM microVM); REST translation
│  └─ tethricor-sandbox-e2b/                 # dev/managed pick (Firecracker); SDK seam, lazy import
│
├─ docker/Dockerfile.*-hardened         # 5 hardened harness images (non-root, ro-rootfs, shim entrypoint)
├─ docker/Dockerfile.harness-local      # test-only shim image used by docker-compose.test.yaml
├─ local-dev/                           # parity doubles: mock_sandbox / mock_mcp / mock_gateway (+ tests)
├─ webhook/                             # Kubernetes mutating admission webhook (works on any cluster; opt-in identity federation)
├─ test-harness/                        # sample harness.yaml + sample repo + out/ for the compose stack
└─ tests/test_e2e_security.py           # cross-cutting security + E2E invariants
```

---

## 4. The three plug-and-play axes (framework model)

All three are ABCs in `shim/tethricor_runtime/interfaces.py`, each with a registry and
entry-point group. This is the extensibility surface. **None has a default** — every
axis must be resolved to a concrete name, either by the caller (`--sandbox`, `Harness(sandbox=...)`)
or by falling back to the always-installed generic option (`remote-runtime`).

| Axis | ABC | Registry | Entry-point group | Ships with |
|---|---|---|---|---|
| **Sandbox** (session/exec/stream/artifact) | `SandboxProvider` | `tethricor_runtime/registry.py` | `tethricor.sandboxes` | `remote-runtime` (generic, always installed; `enterprise-runtime` is a deprecated alias), `microsandbox`, `e2b` |
| **Harness** (task→launch, env hardening) | `HarnessAdapter` | `tethricor_runtime/adapters.py` | `tethricor.harnesses` | hermes, pi, feynman(→pi), openhands, goose, opencode — plus anything registered via `register_harness` |
| **Model routing** (→ OpenAI-compatible URL) | `ModelRouter` | `tethricor_runtime/model.py` | `tethricor.models` | `gateway` (default, `TETHRICOR_MODEL_ROUTER`-selectable) |

- **Discovery**: `import tethricor` calls `tethricor.discovery.load_plugins()` once, populating all
  three registries from installed entry points. Third parties ship a package (e.g.
  `tethricor-sandbox-foo`) with `[project.entry-points."tethricor.sandboxes"] foo = "pkg:make_provider"`.
- **Conformance**: any `SandboxProvider` must pass
  `tethricor_runtime.testing.assert_sandbox_conformance(...)`. Both OSS providers are gated on it
  against in-package **fake backends** that reuse `run_in_workspace` / `zip_workspace`
  from `tethricor_runtime.testing` (hermetic — no KVM/keys in CI).
- **Custom harnesses**: `tethricor_runtime.adapters.register_harness(name, adapter)` (or
  a `tethricor.harnesses` entry point) makes a harness usable immediately by both the SDK
  and the CLI — `harness.type` in the JSON schema is an open string, validated against
  the live registry, not a closed enum. Caveat: your `runtime.profile`/sandbox image
  still needs the harness's own toolchain installed (see `docs/FRAMEWORK_GUIDE.md` §13).

**Contract shapes** (what a provider must return/raise):
- `create_session(profile, *, ttl_seconds, repo_url, ref, metadata) -> {"id","state","profile"}` (`state` ∈ {pending,running}).
- `start_exec(...) -> {"id": exec_id}`; `stream_events(...)` yields `{"type": stdout|stderr|exit|error, "data"|"code"}` terminating on `exit`.
- `download_artifact(session, name) -> bytes` (a zip of changed files = **code OUT**).
- Errors raise `RuntimeError_(code, message, status)`; HTTP 410 → `SessionExpired`. Bad
  profile → status 400; deleted/unknown session → 404.

---

## 5. How to build, test, run

**Setup (editable installs so SDK + discovery work):**
```bash
python -m pip install -e cli
python -m pip install -e shim                      # installs BOTH tethricor_runtime and tethricor
python -m pip install -r local-dev/requirements.txt
python -m pip install -e providers/tethricor-sandbox-microsandbox
python -m pip install -e providers/tethricor-sandbox-e2b
```

**Full test suite (83 tests, ~4s, no containers):**
```bash
python -m pytest cli/tests webhook/test_app.py local-dev shim/tests tests providers -q
```

**Full offline E2E stack (proves code IN/OUT, no private registry):**
```bash
docker compose -f docker-compose.test.yaml up --build
# watch for: "harness task complete" and "[artifact] wrote /out/changes.zip"
unzip -l test-harness/out/changes.zip   # README.md modified + GENERATED.txt new
docker compose -f docker-compose.test.yaml down -v
```

**CLI generation:**
```bash
tethricor init --yes --type hermes --version 0.17.0 --repo-url <url> --sandbox remote-runtime
tethricor validate harness.yaml
tethricor local-dev harness.yaml --target local --out-dir tethricor-out   # or k8s|aks|aci|job
# A harness type with no image-manifest.yaml entry needs --image <your-image> too.
# Fallback if the console script isn't on PATH: python -m tethricor_cli.cli ...
```

**SDK usage (`sandbox` is required — no default):**
```python
from tethricor import Harness
h = Harness(harness="hermes", model="gpt-4o-standard",
            sandbox="remote-runtime", source="https://github.com/org/repo.git")
result = h.run("Refactor the auth module and add tests")   # or an explicit argv list
print(result.ok, result.exit_code)
```

**Gotchas / environment notes:**
- `tethricor`/`tethricor_runtime` are only on the pytest sys.path unless you `pip install -e shim`.
  The SDK quickstart and `tethricor --sandbox <plugin>` validation need the install.
- Windows line endings bit us once: SSE decode uses `.rstrip("\r\n")` in `mock_sandbox.py`.
- `httpx.ASGITransport` is async-only here — shim tests run a **real uvicorn** server via
  the `base_url` fixture in `shim/tests/conftest.py`. Mirror that pattern for new provider
  fakes (see `providers/*/tests/`).
- Pytest needs **unique test-file basenames** across the session (that's why provider
  tests are `test_microsandbox_conformance.py` / `test_e2b_conformance.py`).
- The no-local-exec security scan (`tests/test_e2e_security.py`) exempts `tethricor_runtime/
  testing.py` (the test kit) — keep `subprocess` out of every **other** `tethricor_runtime/*.py`.
- `--sandbox` and `--type` are both required for `tethricor init` in non-interactive
  (`--yes`) mode now — there's no default for either.

---

## 6. Key design decisions already made (don't relitigate without cause)

From `DESIGN_NOTES.md` (see it for full historical rationale):
- **skills/mcp are free-form strings in v1** (validate against a live catalog later — keep
  designs forward-compatible). (A1)
- **`model.routing_profile`** is the v1 abstraction (gateway alias, OpenAI-compatible
  assumption, no vendor hardcoded), with a **local-only** `direct_azure_openai` escape
  hatch that is **stripped for non-local targets**. (A-model)
- **`deployment.target`** is a CLI flag at generation time (`local|k8s|aks|aci|job`);
  Azure Functions/WebJobs were **descoped** for v1. (A7) `aci`/`job` are Azure-specific
  and stay that way (no fabricated AWS/GCP equivalents); `k8s` is the cloud-neutral path.
- **Code IN** = git clone into the sandbox session. **Code OUT** = **zip of changed files**
  via the artifact download endpoint (NOT git commit/PR; not stdout). (A2)
- **`runtime.provider`** (Phase 8) selects the sandbox backend; **required, no default**,
  validated against the installed registry (not statically). `remote-runtime` is the
  generic always-available name; `enterprise-runtime` is kept as a deprecated alias for
  back-compat.
- **`harness.type`** is an open, registry-validated string, not a closed schema enum —
  custom adapters plug in without a schema change.
- **Daytona NOT adopted** (AGPL-3.0 + OSS repo frozen Jun 2026). E2B has an **Azure
  self-host gap** — dev/managed only, not on-prem Azure prod. microsandbox is the primary
  on-prem-capable OSS pick (beta — pin versions).
- **License: Apache-2.0.** See `LICENSE`/`NOTICE`.

---

## 7. Deferred work (the immediate roadmap)

Deliberately **not** built, to avoid speculative/untestable code (rules #5–#8). Pick up
in this order:

1. **Typed live skills/MCP catalog resolution.** Today `skills`/`mcp` are free-form.
   Introduce a `CatalogResolver` interface + entry-point group, resolve against a live
   MCP/skills catalog, and tighten the schema. Keep free-form fallback for offline/dev.
   (Traceable to DESIGN_NOTES A1.)
2. **TypeScript SDK.** Mirror the `tethricor` Python facade (Harness + typed results) for TS
   consumers. Large new surface — sequence after Python SDK adoption; share the OpenAPI
   contract in `api-spec/`.
3. **Real-backend provider E2E (integration, non-CI).** microsandbox on a KVM host; live
   E2B with keys. CI stays hermetic (fakes); add an opt-in integration lane.
4. **Deepen adapters further if needed.** `run_argv` uses each harness's *conventional*
   launch command (`entrypoint` + `task_arg`) — verify/pin against each harness's real CLI
   as they're actually integrated; wire per-harness output profiles (`pre_artifact_argv`)
   if a harness writes outputs somewhere the runtime's changed-file zip misses.
5. **gVisor/Kata RuntimeClass** hardening for the pods running any in-cluster
   runtime/sandbox (defense-in-depth on k8s) — orthogonal, not a provider.
6. **Sandbox-profile harness provisioning (known gap).** A harness's own toolchain needs
   to already be present wherever its forwarded command executes; nothing automates
   getting it there today (see `docs/FRAMEWORK_GUIDE.md` §13). Fixing it means extending
   the `SandboxProvider.create_session` contract with an optional per-session image
   override, which is real new interface surface across every provider + the conformance
   kit, deliberately not built without being asked.

---

## 8. Upstream dependencies (Phase 0 — owned by whoever operates your sandbox runtime)

The shim/contract assume a real sandbox backend provides these; they are **not** built
in this repo, and which team owns them depends on what you point `remote-runtime` (or
your own `SandboxProvider`) at:
1. **Repo clone at session create** (`repoUrl`/`ref`) — code IN.
2. **Language/tooling profiles** returned by `GET /v1/profiles` (python312, node20, rust, …).
3. **Artifact download endpoint** returning a **zip of changed files** — code OUT
   (`GET /v1/sessions/{id}/artifacts/{name}`; see `api-spec/`).

The local `mock_sandbox.py` implements all three so everything is testable offline today.

---

## 9. Working agreement for future changes

- **Read `.cursorrules` + `PROJECT_CONTEXT.md` + `IMPLEMENTATION_PLAN.md`** before coding;
  don't jump phases.
- **Every change ships with tests**; run the full suite green before claiming done.
- **No bloat/duplication** — reuse `tethricor_runtime` internals; the SDK/CLI are thin facades
  over the orchestrator (single code path). The shim `__main__` delegates to `tethricor.cli`.
- **Security first**: never add a local-execution path to the runtime packages; keep LLM/
  MCP on the gateway; keep `additionalProperties:false` on the schema.
- **Additive only, no hardcoded defaults**: don't reintroduce a "blessed" default
  sandbox/gateway/cloud; new providers/targets are opt-in, and Azure-specific targets
  (`aci`/`job`) stay clearly labeled as such rather than disguised as generic.
- Update the relevant doc(s) in `docs/agent_context/` when you change behavior, and check
  off the plan.

---

## 10. Deep history

The full design conversation (reframing Tethricor, harness research, contract decisions,
phase-by-phase build) is captured across the docs above. For decision provenance, prefer
`DESIGN_NOTES.md` (§1–§8) and `FRAMEWORK_EVOLUTION.md`; they are the source of truth over
any single chat.
